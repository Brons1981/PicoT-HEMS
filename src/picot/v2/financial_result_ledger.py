"""Persistent read-only settlement of measured battery and PicoT value."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

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
    ) -> dict[str, object]:
        """Replace today's partial settlement from canonical measured history."""
        result = self._evaluate(snapshot, history)
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
            return result
        states = snapshot.current_storage_states
        limits = snapshot.storage_physical_limits
        if not states or not limits:
            result["reason"] = "storage_physical_state_missing"
            return result
        segments = self._price_segments(
            snapshot.price_points,
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
            return result
        actual_cost = 0.0
        actual_import_cost = 0.0
        actual_export_revenue = 0.0
        no_battery_cost = 0.0
        load_only_cost = 0.0
        for start, end, import_rate, export_rate in segments:
            values = {role: self._integrate(series, start, end) for role, series in by_role.items()}
            if any(value is None for value in values.values()):
                result["reason"] = "measurement_coverage_incomplete"
                return result
            complete_values = {
                role: value for role, value in values.items() if value is not None
            }
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
            "baseline": "same_measured_pv_and_household_with_nom_battery_control",
        })
        return result

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
