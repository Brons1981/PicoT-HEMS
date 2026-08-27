"""Persistent read-only settlement of measured battery and PicoT value."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from picot.domain.storage_energy_inventory import (
    StorageEnergyInventory,
    StorageEnergyLot,
)
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.independent_daily_tariff_adapter import (
    ENERGY_TAX_EX_VAT_EUR_PER_KWH,
    EXPORT_ADDITION_EUR_PER_KWH,
    EXPORT_TAX_TRANSITION,
    SUPPLIER_ADDITION_EX_VAT_EUR_PER_KWH,
    VAT_FACTOR,
)
from picot.v2.power_history import PowerHistorySeries, PowerHistorySnapshot

SCHEMA_VERSION = 1
METHOD_VERSION = "financial-result-ledger:v1"
REQUIRED_ROLES = frozenset({
    "pv_generation",
    "household_load",
    "grid_import",
    "grid_export",
    "battery_charge",
    "battery_discharge",
})


@dataclass(slots=True)
class _MutableStorageEnergyLot:
    source: str
    stored_energy_wh: float
    acquisition_cost_eur: float | None
    acquired_at: datetime
    evidence_ids: tuple[str, ...]


class FinancialResultLedger:
    """Settle measured results without authority over any PicoT planner."""

    def __init__(
        self,
        *,
        state_path: Path,
        wear_eur_per_discharge_kwh: float = 0.05,
        battery_purchase_eur: float = 2407.40,
        charge_efficiency: float = 1.0,
        discharge_efficiency: float = 1.0,
        local_timezone_name: str = "Europe/Amsterdam",
    ) -> None:
        if wear_eur_per_discharge_kwh < 0.0 or battery_purchase_eur <= 0.0:
            raise ValueError("financial settings must be non-negative")
        if not 0.0 < charge_efficiency <= 1.0:
            raise ValueError("charge efficiency must be in (0, 1]")
        if not 0.0 < discharge_efficiency <= 1.0:
            raise ValueError("discharge efficiency must be in (0, 1]")
        self.state_path = state_path
        self.wear_rate = wear_eur_per_discharge_kwh
        self.purchase_eur = battery_purchase_eur
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency
        self.local_timezone = ZoneInfo(local_timezone_name)
        self._lock = Lock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {"schema_version": SCHEMA_VERSION, "days": {}}
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported financial result state")
        return value

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.writing")
        temporary.write_text(json.dumps(self._state, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.state_path)

    def update(
        self,
        snapshot: PlanningInputSnapshot,
        history: PowerHistorySnapshot,
        *,
        price_points: tuple[PriceForecastPoint, ...] | None = None,
    ) -> dict[str, object]:
        """Replace today's partial settlement from canonical measured history."""
        result = self._evaluate(
            snapshot,
            history,
            price_points=(snapshot.price_points if price_points is None else price_points),
        )
        local_day = snapshot.captured_at.astimezone(self.local_timezone).date().isoformat()
        with self._lock:
            days = self._state.setdefault("days", {})
            assert isinstance(days, dict)
            days[local_day] = result
            self._save()
            return self._dashboard_view_locked()

    def dashboard_view(self) -> dict[str, object]:
        with self._lock:
            return self._dashboard_view_locked()

    def storage_energy_inventory(self) -> StorageEnergyInventory | None:
        """Return the latest measured cost basis without granting planner authority."""
        with self._lock:
            days = self._state.get("days", {})
            if not isinstance(days, dict):
                return None
            latest = max(
                (item for item in days.values() if isinstance(item, dict)),
                key=lambda item: str(item.get("day", "")),
                default=None,
            )
            if latest is None or latest.get("status") != "available":
                return None
            value = latest.get("storage_energy_inventory")
            if not isinstance(value, dict):
                return None
            return self._inventory_from_view(value)

    def _dashboard_view_locked(self) -> dict[str, object]:
        days = self._state.get("days", {})
        day_values = (
            [item for item in days.values() if isinstance(item, dict)]
            if isinstance(days, dict)
            else []
        )
        complete = [item for item in day_values if item.get("status") == "available"]
        cumulative_battery = sum(float(item["net_battery_value_eur"]) for item in complete)
        cumulative_picot = sum(float(item["net_picot_value_eur"]) for item in complete)
        latest = max(day_values, key=lambda item: str(item.get("day", "")), default=None)
        return {
            "available": latest is not None,
            "status": latest.get("status") if latest else "unavailable",
            "today": latest,
            "days": sorted(day_values, key=lambda item: str(item.get("day", ""))),
            "cumulative": {
                "net_battery_value_eur": round(cumulative_battery, 4),
                "net_picot_value_eur": round(cumulative_picot, 4),
                "battery_purchase_eur": self.purchase_eur,
                "remaining_eur": round(max(0.0, self.purchase_eur - cumulative_battery), 4),
                "repaid_fraction": max(0.0, min(1.0, cumulative_battery / self.purchase_eur)),
            },
            "wear_eur_per_discharge_kwh": self.wear_rate,
            "observer_only": True,
            "selection_permitted": False,
            "commitment_permitted": False,
            "method_version": METHOD_VERSION,
        }

    def _evaluate(
        self,
        snapshot: PlanningInputSnapshot,
        history: PowerHistorySnapshot,
        *,
        price_points: tuple[PriceForecastPoint, ...],
    ) -> dict[str, object]:
        local_day = snapshot.captured_at.astimezone(self.local_timezone).date().isoformat()
        result: dict[str, object] = {
            "day": local_day,
            "captured_at": snapshot.captured_at.astimezone(UTC).isoformat(),
            "starts_at": history.starts_at.astimezone(UTC).isoformat(),
            "ends_at": history.ends_at.astimezone(UTC).isoformat(),
            "status": "incomplete",
            "reason": None,
        }
        by_role = {item.role: item for item in history.series if item.points}
        missing = sorted(REQUIRED_ROLES - set(by_role))
        if history.status != "available" or missing:
            result["reason"] = "missing_measured_series"
            result["missing_roles"] = missing
            result["coverage_by_role"] = self._coverage_by_role(
                by_role,
                starts_at=history.starts_at,
            )
            return result
        states = snapshot.current_storage_states
        limits = snapshot.storage_physical_limits
        if not states or not limits:
            result["reason"] = "storage_physical_state_missing"
            return result
        segments = self._price_segments(
            price_points,
            history.starts_at,
            history.ends_at,
        )
        if not segments:
            result["reason"] = "price_coverage_incomplete"
            return result

        energy_by_role = {
            role: self._integrate(series, history.starts_at, history.ends_at)
            for role, series in by_role.items()
        }
        if any(value is None for value in energy_by_role.values()):
            result["reason"] = "measurement_coverage_incomplete"
            result["coverage_by_role"] = self._coverage_by_role(
                by_role,
                starts_at=history.starts_at,
            )
            return result
        actual_cost = 0.0
        actual_import_cost = 0.0
        actual_export_revenue = 0.0
        no_battery_cost = 0.0
        load_only_cost = 0.0
        household_source_wh = {"pv_direct": 0.0, "battery": 0.0, "grid": 0.0}
        household_source_value_eur = {
            "pv_direct": 0.0,
            "battery": 0.0,
            "grid": 0.0,
        }
        inventory_segments: list[
            tuple[datetime, datetime, float, float, dict[str, float]]
        ] = []
        for start, end, import_rate, export_rate in segments:
            values = {role: self._integrate(series, start, end) for role, series in by_role.items()}
            if any(value is None for value in values.values()):
                result["reason"] = "measurement_coverage_incomplete"
                return result
            complete_values = {
                role: value for role, value in values.items() if value is not None
            }
            inventory_segments.append(
                (start, end, import_rate, export_rate, complete_values)
            )
            interval_import_cost = (
                complete_values["grid_import"] * import_rate / 1000.0
            )
            interval_export_revenue = (
                complete_values["grid_export"] * export_rate / 1000.0
            )
            actual_import_cost += interval_import_cost
            actual_export_revenue += interval_export_revenue
            actual_cost += interval_import_cost - interval_export_revenue
            pv = complete_values["pv_generation"]
            load = complete_values["household_load"]
            direct_pv = min(pv, load)
            remaining_load = max(0.0, load - direct_pv)
            battery_to_load = min(
                complete_values["battery_discharge"],
                remaining_load,
            )
            grid_to_load = max(0.0, remaining_load - battery_to_load)
            source_energy = {
                "pv_direct": direct_pv,
                "battery": battery_to_load,
                "grid": grid_to_load,
            }
            for source, energy_wh in source_energy.items():
                household_source_wh[source] += energy_wh
                household_source_value_eur[source] += (
                    energy_wh * import_rate / 1000.0
                )
            no_battery_cost += (
                max(0.0, load - pv) * import_rate
                - max(0.0, pv - load) * export_rate
            ) / 1000.0
            load_only_cost += load * import_rate / 1000.0

        state = states[0]
        limit = next(
            (
                item
                for item in limits
                if item.execution_scope_id == state.execution_scope_id
            ),
            limits[0],
        )
        complete_energy_by_role = {
            role: value for role, value in energy_by_role.items() if value is not None
        }
        actual_charge = complete_energy_by_role["battery_charge"]
        actual_discharge = complete_energy_by_role["battery_discharge"]
        initial_energy = (
            state.current_stored_energy_wh
            - actual_charge * self.charge_efficiency
            + actual_discharge / self.discharge_efficiency
        )
        initial_energy = max(
            state.usable_capacity_wh * limit.minimum_soc,
            min(state.usable_capacity_wh * limit.maximum_soc, initial_energy),
        )
        inventory = self._build_storage_inventory(
            execution_scope_id=state.execution_scope_id,
            captured_at=snapshot.captured_at,
            measured_stored_energy_wh=state.current_stored_energy_wh,
            initial_stored_energy_wh=initial_energy,
            starts_at=history.starts_at,
            segments=inventory_segments,
            opening_inventory=self._prior_storage_inventory(local_day),
        )
        nom_cost, nom_discharge = self._simulate_nom(
            by_role=by_role,
            segments=segments,
            initial_energy_wh=initial_energy,
            minimum_energy_wh=state.usable_capacity_wh * limit.minimum_soc,
            maximum_energy_wh=state.usable_capacity_wh * limit.maximum_soc,
            maximum_charge_power_w=limit.maximum_charge_input_power_w,
            maximum_discharge_power_w=limit.maximum_discharge_output_power_w,
        )
        actual_wear = actual_discharge / 1000.0 * self.wear_rate
        nom_wear = nom_discharge / 1000.0 * self.wear_rate
        gross_battery = no_battery_cost - actual_cost
        net_battery = gross_battery - actual_wear
        gross_total_energy = load_only_cost - actual_cost
        net_total_energy = gross_total_energy - actual_wear
        gross_picot = nom_cost - actual_cost
        net_picot = gross_picot + nom_wear - actual_wear
        household_load_wh = sum(household_source_wh.values())
        source_value_kinds = {
            "pv_direct": "avoided_grid_import",
            "battery": "avoided_grid_import_gross",
            "grid": "energy_cost",
        }
        result.update({
            "status": "available",
            "reason": None,
            "actual_energy_cost_eur": round(actual_cost, 4),
            "grid_import_cost_eur": round(actual_import_cost, 4),
            "grid_export_revenue_eur": round(actual_export_revenue, 4),
            "load_only_energy_cost_eur": round(load_only_cost, 4),
            "gross_total_energy_value_eur": round(gross_total_energy, 4),
            "net_total_energy_value_eur": round(net_total_energy, 4),
            "no_battery_energy_cost_eur": round(no_battery_cost, 4),
            "nom_energy_cost_eur": round(nom_cost, 4),
            "grid_import_cost_and_export_net_eur": round(actual_cost, 4),
            "gross_battery_value_eur": round(gross_battery, 4),
            "battery_wear_eur": round(actual_wear, 4),
            "net_battery_value_eur": round(net_battery, 4),
            "gross_picot_value_eur": round(gross_picot, 4),
            "nom_wear_eur": round(nom_wear, 4),
            "net_picot_value_eur": round(net_picot, 4),
            "energy_kwh": {
                key: round(value / 1000.0, 4)
                for key, value in complete_energy_by_role.items()
            },
            "storage_energy_inventory": self._inventory_view(inventory),
            "household_energy_sources": {
                "household_load_kwh": round(household_load_wh / 1000.0, 4),
                "sources": [
                    {
                        "source": source,
                        "energy_kwh": round(household_source_wh[source] / 1000.0, 4),
                        "share": round(
                            household_source_wh[source] / household_load_wh,
                            6,
                        ) if household_load_wh > 0.0 else 0.0,
                        "value_eur": round(household_source_value_eur[source], 4),
                        "value_kind": source_value_kinds[source],
                    }
                    for source in ("pv_direct", "battery", "grid")
                ],
            },
            "baseline": "same_measured_pv_and_household_with_nom_battery_control",
            "coverage_by_role": self._coverage_by_role(
                by_role,
                starts_at=history.starts_at,
            ),
        })
        return result

    def _build_storage_inventory(
        self,
        *,
        execution_scope_id: str,
        captured_at: datetime,
        measured_stored_energy_wh: float,
        initial_stored_energy_wh: float,
        starts_at: datetime,
        segments: list[
            tuple[datetime, datetime, float, float, dict[str, float]]
        ],
        opening_inventory: StorageEnergyInventory | None,
    ) -> StorageEnergyInventory:
        """Replay measured flows into auditable source-and-cost lots.

        The opening balance is deliberately unknown. New PV energy is valued at
        foregone export revenue and grid energy at its measured import tariff.
        Discharge consumes the oldest physical lots; route selection may later
        value the cheapest *known* lots, but may never assign a price to unknown
        opening or reconciliation energy.
        """
        lots = [
            _MutableStorageEnergyLot(
                source=item.source,
                stored_energy_wh=item.stored_energy_wh,
                acquisition_cost_eur=item.acquisition_cost_eur,
                acquired_at=item.acquired_at,
                evidence_ids=item.evidence_ids,
            )
            for item in (opening_inventory.lots if opening_inventory is not None else ())
        ]

        def consume(stored_energy_wh: float) -> None:
            remaining = max(0.0, stored_energy_wh)
            while remaining > 1e-9 and lots:
                lot = lots[0]
                available = lot.stored_energy_wh
                taken = min(remaining, available)
                cost = lot.acquisition_cost_eur
                if cost is not None:
                    lot.acquisition_cost_eur = cost * (available - taken) / available
                lot.stored_energy_wh = available - taken
                remaining -= taken
                if lot.stored_energy_wh <= 1e-9:
                    lots.pop(0)

        opening_delta_wh = initial_stored_energy_wh - sum(
            item.stored_energy_wh for item in lots
        )
        if opening_delta_wh < -1.0:
            consume(-opening_delta_wh)
        elif opening_delta_wh > 1.0:
            lots.append(_MutableStorageEnergyLot(
                source="unknown",
                stored_energy_wh=opening_delta_wh,
                acquisition_cost_eur=None,
                acquired_at=starts_at,
                evidence_ids=("opening-storage-balance",),
            ))

        for start, end, import_rate, export_rate, values in segments:
            consume(values["battery_discharge"] / self.discharge_efficiency)
            charge_input_wh = values["battery_charge"]
            pv_surplus_wh = max(
                0.0,
                values["pv_generation"] - values["household_load"],
            )
            pv_input_wh = min(charge_input_wh, pv_surplus_wh)
            grid_input_wh = max(0.0, charge_input_wh - pv_input_wh)
            evidence = (
                f"measured-storage-flow:{start.astimezone(UTC).isoformat()}",
                f"tariff:{start.astimezone(UTC).isoformat()}",
            )
            for source, input_wh, rate in (
                ("pv", pv_input_wh, export_rate),
                ("grid", grid_input_wh, import_rate),
            ):
                stored_wh = input_wh * self.charge_efficiency
                if stored_wh <= 1e-9:
                    continue
                lots.append(_MutableStorageEnergyLot(
                    source=source,
                    stored_energy_wh=stored_wh,
                    acquisition_cost_eur=input_wh * rate / 1000.0,
                    acquired_at=end,
                    evidence_ids=evidence,
                ))

        accounted_wh = sum(item.stored_energy_wh for item in lots)
        delta_wh = measured_stored_energy_wh - accounted_wh
        if delta_wh < -1.0:
            consume(-delta_wh)
        elif delta_wh > 1.0:
            lots.append(_MutableStorageEnergyLot(
                source="unknown",
                stored_energy_wh=delta_wh,
                acquisition_cost_eur=None,
                acquired_at=captured_at,
                evidence_ids=("measured-storage-reconciliation",),
            ))
        reconciled_wh = sum(item.stored_energy_wh for item in lots)
        final_delta_wh = measured_stored_energy_wh - reconciled_wh
        if abs(final_delta_wh) > 1e-9 and lots:
            lots[-1].stored_energy_wh += final_delta_wh

        return StorageEnergyInventory(
            execution_scope_id=execution_scope_id,
            captured_at=captured_at,
            measured_stored_energy_wh=measured_stored_energy_wh,
            lots=tuple(
                StorageEnergyLot(
                    source=item.source,
                    stored_energy_wh=item.stored_energy_wh,
                    acquisition_cost_eur=item.acquisition_cost_eur,
                    acquired_at=item.acquired_at,
                    evidence_ids=item.evidence_ids,
                )
                for item in lots
                if item.stored_energy_wh > 1e-9
            ),
        )

    def _prior_storage_inventory(
        self,
        local_day: str,
    ) -> StorageEnergyInventory | None:
        days = self._state.get("days", {})
        if not isinstance(days, dict):
            return None
        previous = max(
            (
                item
                for day, item in days.items()
                if str(day) < local_day
                and isinstance(item, dict)
                and item.get("status") == "available"
                and isinstance(item.get("storage_energy_inventory"), dict)
            ),
            key=lambda item: str(item.get("day", "")),
            default=None,
        )
        if previous is None:
            return None
        value = previous["storage_energy_inventory"]
        assert isinstance(value, dict)
        return self._inventory_from_view(value)

    @staticmethod
    def _inventory_from_view(value: dict[str, object]) -> StorageEnergyInventory | None:
        raw_lots = value.get("lots")
        measured_stored_energy_wh = value.get("measured_stored_energy_wh")
        if not isinstance(raw_lots, list) or not isinstance(
            measured_stored_energy_wh,
            int | float | str,
        ):
            return None
        return StorageEnergyInventory(
            execution_scope_id=str(value["execution_scope_id"]),
            captured_at=datetime.fromisoformat(str(value["captured_at"])),
            measured_stored_energy_wh=float(measured_stored_energy_wh),
            lots=tuple(
                StorageEnergyLot(
                    source=str(item["source"]),
                    stored_energy_wh=float(item["stored_energy_wh"]),
                    acquisition_cost_eur=(
                        float(item["acquisition_cost_eur"])
                        if item.get("acquisition_cost_eur") is not None
                        else None
                    ),
                    acquired_at=datetime.fromisoformat(str(item["acquired_at"])),
                    evidence_ids=tuple(str(entry) for entry in item["evidence_ids"]),
                )
                for item in raw_lots
                if isinstance(item, dict)
            ),
        )

    @staticmethod
    def _inventory_view(inventory: StorageEnergyInventory) -> dict[str, object]:
        known_cost_eur = sum(
            float(item.acquisition_cost_eur or 0.0)
            for item in inventory.lots
            if item.acquisition_cost_eur is not None
        )
        return {
            "execution_scope_id": inventory.execution_scope_id,
            "captured_at": inventory.captured_at.isoformat(),
            "measured_stored_energy_wh": round(
                inventory.measured_stored_energy_wh, 6
            ),
            "known_stored_energy_wh": round(inventory.known_stored_energy_wh, 6),
            "unknown_stored_energy_wh": round(
                inventory.measured_stored_energy_wh
                - inventory.known_stored_energy_wh,
                6,
            ),
            "known_acquisition_cost_eur": round(known_cost_eur, 6),
            "method_version": inventory.method_version,
            "lots": [
                {
                    "source": item.source,
                    "stored_energy_wh": round(item.stored_energy_wh, 6),
                    "acquisition_cost_eur": (
                        round(item.acquisition_cost_eur, 6)
                        if item.acquisition_cost_eur is not None
                        else None
                    ),
                    "cost_eur_per_stored_kwh": (
                        round(item.cost_eur_per_stored_kwh, 6)
                        if item.cost_eur_per_stored_kwh is not None
                        else None
                    ),
                    "acquired_at": item.acquired_at.isoformat(),
                    "evidence_ids": list(item.evidence_ids),
                }
                for item in inventory.lots
            ],
        }

    @staticmethod
    def _coverage_by_role(
        by_role: dict[str, PowerHistorySeries],
        *,
        starts_at: datetime,
    ) -> dict[str, object]:
        return {
            role: {
                "point_count": len(series.points),
                "first_point_at": (
                    min(point.sampled_at for point in series.points)
                    .astimezone(UTC)
                    .isoformat()
                    if series.points
                    else None
                ),
                "last_point_at": (
                    max(point.sampled_at for point in series.points)
                    .astimezone(UTC)
                    .isoformat()
                    if series.points
                    else None
                ),
                "start_anchor_available": any(
                    point.sampled_at <= starts_at for point in series.points
                ),
            }
            for role, series in sorted(by_role.items())
        }

    @staticmethod
    def _price_segments(
        points: tuple[PriceForecastPoint, ...], starts_at: datetime, ends_at: datetime
    ) -> list[tuple[datetime, datetime, float, float]]:
        cursor = starts_at
        result = []
        for point in sorted(points, key=lambda item: item.starts_at):
            if point.ends_at <= starts_at or point.starts_at >= ends_at:
                continue
            start, end = max(starts_at, point.starts_at), min(ends_at, point.ends_at)
            if start != cursor or end <= start:
                return []
            import_rate = point.value_eur_per_kwh
            export_rate = import_rate
            if start >= EXPORT_TAX_TRANSITION:
                export_rate = import_rate - (
                    ENERGY_TAX_EX_VAT_EUR_PER_KWH + SUPPLIER_ADDITION_EX_VAT_EUR_PER_KWH
                ) * VAT_FACTOR + EXPORT_ADDITION_EUR_PER_KWH
            result.append((start, end, import_rate, export_rate))
            cursor = end
        return result if cursor == ends_at else []

    @staticmethod
    def _integrate(
        series: PowerHistorySeries, starts_at: datetime, ends_at: datetime
    ) -> float | None:
        points = tuple(sorted(series.points, key=lambda item: item.sampled_at))
        held = next((item for item in reversed(points) if item.sampled_at <= starts_at), None)
        cursor = starts_at
        watt_seconds = 0.0
        for point in points:
            if point.sampled_at <= starts_at:
                continue
            if point.sampled_at >= ends_at:
                break
            if held is None:
                return None
            duration = (point.sampled_at - cursor).total_seconds()
            watt_seconds += held.power_w * duration
            held = point
            cursor = point.sampled_at
        if held is None:
            return None
        watt_seconds += held.power_w * (ends_at - cursor).total_seconds()
        return max(0.0, watt_seconds / 3600.0)

    def _simulate_nom(
        self,
        *,
        by_role: dict[str, PowerHistorySeries],
        segments: list[tuple[datetime, datetime, float, float]],
        initial_energy_wh: float,
        minimum_energy_wh: float,
        maximum_energy_wh: float,
        maximum_charge_power_w: float,
        maximum_discharge_power_w: float,
    ) -> tuple[float, float]:
        energy = initial_energy_wh
        total_cost = 0.0
        total_discharge = 0.0
        for start, end, import_rate, export_rate in segments:
            pv = float(self._integrate(by_role["pv_generation"], start, end) or 0.0)
            load = float(self._integrate(by_role["household_load"], start, end) or 0.0)
            direct = min(pv, load)
            surplus, deficit = pv - direct, load - direct
            duration_h = (end - start).total_seconds() / 3600.0
            discharge = min(
                deficit,
                max(0.0, energy - minimum_energy_wh) * self.discharge_efficiency,
                maximum_discharge_power_w * duration_h,
            )
            energy -= discharge / self.discharge_efficiency
            deficit -= discharge
            charge = min(
                surplus,
                max(0.0, maximum_energy_wh - energy) / self.charge_efficiency,
                maximum_charge_power_w * duration_h,
            )
            energy += charge * self.charge_efficiency
            surplus -= charge
            total_discharge += discharge
            total_cost += (deficit * import_rate - surplus * export_rate) / 1000.0
        return total_cost, total_discharge
