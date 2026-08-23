"""Persistent observer-only replay ledger for canonical and daily plans."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.independent_daily_tariff_adapter import (
    IndependentDailyTariffAdapter,
)
from picot.v2.power_history import PowerHistorySnapshot

SCHEMA_VERSION = 1
METHOD_VERSION = "planner-comparison-replay:v1"
REQUIRED_ROLES = frozenset(
    {
        "pv_generation",
        "household_load",
        "grid_import",
        "grid_export",
        "battery_charge",
        "battery_discharge",
    }
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


class PlannerComparisonLedger:
    """Freeze aligned decisions and replay both against one measured reality.

    This class has deliberately no callback into Candidate, Evaluation,
    Commitment or Execution.  Its files and dashboard view are evidence only.
    """

    def __init__(
        self,
        *,
        state_path: Path,
        history_path: Path,
        charge_efficiency: float = 1.0,
        discharge_efficiency: float = 1.0,
    ) -> None:
        if not 0.0 < charge_efficiency <= 1.0:
            raise ValueError("charge efficiency must be in (0, 1]")
        if not 0.0 < discharge_efficiency <= 1.0:
            raise ValueError("discharge efficiency must be in (0, 1]")
        self.state_path = state_path
        self.history_path = history_path
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency
        self._lock = Lock()
        self._state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {
                "schema_version": SCHEMA_VERSION,
                "dossiers": {},
                "pending_observers": {},
            }
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported planner comparison state")
        return value

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.writing")
        temporary.write_text(json.dumps(self._state, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.state_path)

    def register_canonical(
        self, snapshot: PlanningInputSnapshot, canonical_view: dict[str, object]
    ) -> None:
        chosen = canonical_view.get("planning_status", {})
        chosen = chosen.get("chosen_plan", {}) if isinstance(chosen, dict) else {}
        if not isinstance(chosen, dict) or not chosen.get("candidate_id"):
            return
        states = snapshot.current_storage_states
        limits = snapshot.storage_physical_limits
        if not states or not limits:
            return
        state = states[0]
        limit = next(
            (item for item in limits if item.execution_scope_id == state.execution_scope_id),
            limits[0],
        )
        horizon_end = snapshot.captured_at + timedelta(hours=24)
        try:
            tariffs = IndependentDailyTariffAdapter().build(
                snapshot,
                horizon_end=horizon_end,
            )
            prices = [
                {
                    "starts_at": _iso(item.starts_at),
                    "ends_at": _iso(item.ends_at),
                    "import_eur_per_kwh": item.import_eur_per_kwh,
                    "export_eur_per_kwh": item.export_eur_per_kwh,
                    "confidence": item.confidence,
                }
                for item in tariffs.intervals
            ]
            tariff_error = None
        except ValueError as exc:
            prices = []
            tariff_error = str(exc) or exc.__class__.__name__
        dossier = {
            "comparison_id": f"planner-comparison:{snapshot.snapshot_id}",
            "snapshot_id": snapshot.snapshot_id,
            "run_id": snapshot.run_id,
            "captured_at": _iso(snapshot.captured_at),
            "status": "awaiting_observer",
            "horizon_end": None,
            "canonical": {
                "candidate_id": chosen.get("candidate_id"),
                "family": chosen.get("family"),
                "reason": chosen.get("reason"),
                "confidence": chosen.get("confidence"),
                "charge_window_starts_at": chosen.get("charge_window_starts_at"),
                "charge_window_ends_at": chosen.get("charge_window_ends_at"),
            },
            "observer": None,
            "physical": {
                "initial_energy_wh": state.current_stored_energy_wh,
                "capacity_wh": state.usable_capacity_wh,
                "minimum_energy_wh": state.usable_capacity_wh * limit.minimum_soc,
                "target_energy_wh": state.usable_capacity_wh * limit.maximum_soc,
                "maximum_charge_power_w": limit.maximum_charge_input_power_w,
                "maximum_discharge_power_w": limit.maximum_discharge_output_power_w,
                "charge_efficiency": self.charge_efficiency,
                "discharge_efficiency": self.discharge_efficiency,
            },
            "prices": prices,
            "tariff_error": tariff_error,
            "measurements": {},
            "storage_samples": [
                {"at": _iso(state.measured_at), "energy_wh": state.current_stored_energy_wh}
            ],
            "stress_markers": [],
            "projection_state": "current",
            "stress_restart": None,
            "result": None,
            "observer_only": True,
            "selection_permitted": False,
            "commitment_permitted": False,
            "method_version": METHOD_VERSION,
        }
        with self._lock:
            dossiers = self._state.setdefault("dossiers", {})
            assert isinstance(dossiers, dict)
            latest_stress = self._state.get("latest_stress_marker")
            if (
                isinstance(latest_stress, dict)
                and isinstance(latest_stress.get("occurred_at"), str)
                and snapshot.captured_at >= _parse(latest_stress["occurred_at"])
                and snapshot.captured_at
                <= _parse(latest_stress["occurred_at"]) + timedelta(hours=2)
            ):
                dossier["stress_restart"] = {
                    "marker_id": latest_stress.get("marker_id"),
                    "latest_measured_storage_state_id": state.storage_state_id,
                    "latest_measured_energy_wh": state.current_stored_energy_wh,
                    "previous_simulated_state_reused": False,
                }
            dossiers.setdefault(snapshot.snapshot_id, dossier)
            pending = self._state.setdefault("pending_observers", {})
            if isinstance(pending, dict):
                observer = pending.pop(snapshot.snapshot_id, None)
                if isinstance(observer, dict):
                    self._attach_locked(dossiers[snapshot.snapshot_id], observer)
            self._save()

    def attach_observer(self, observer_view: dict[str, object]) -> None:
        snapshot_id = observer_view.get("snapshot_id")
        if not isinstance(snapshot_id, str):
            return
        candidates = observer_view.get("candidates")
        best = (
            next(
                (
                    item
                    for item in candidates
                    if isinstance(item, dict) and item.get("best_observation")
                ),
                None,
            )
            if isinstance(candidates, list)
            else None
        )
        with self._lock:
            dossiers = self._state.get("dossiers", {})
            dossier = dossiers.get(snapshot_id) if isinstance(dossiers, dict) else None
            if not isinstance(dossier, dict):
                pending = self._state.setdefault("pending_observers", {})
                if isinstance(pending, dict):
                    pending[snapshot_id] = observer_view
                    self._save()
                return
            self._attach_locked(dossier, observer_view, best=best)
            self._save()

    @staticmethod
    def _attach_locked(
        dossier: dict[str, Any],
        observer_view: dict[str, object],
        *,
        best: dict[str, object] | None = None,
    ) -> None:
        candidates = observer_view.get("candidates")
        if best is None and isinstance(candidates, list):
            best = next(
                (
                    item
                    for item in candidates
                    if isinstance(item, dict) and item.get("best_observation")
                ),
                None,
            )
        if observer_view.get("status") != "completed" or not isinstance(best, dict):
            dossier["status"] = "insufficient_data"
            dossier["result"] = {
                "reason": observer_view.get("reason") or "observer produced no unique best plan"
            }
            return
        dossier["observer"] = best
        dossier["horizon_end"] = best.get("horizon_end")
        dossier["status"] = "measuring"

    def ingest(self, snapshot: PlanningInputSnapshot, history: PowerHistorySnapshot) -> None:
        with self._lock:
            dossiers = self._state.get("dossiers", {})
            if not isinstance(dossiers, dict):
                return
            for dossier in dossiers.values():
                if not isinstance(dossier, dict) or dossier.get("status") != "measuring":
                    continue
                measurement_start = _parse(dossier["captured_at"]) - timedelta(
                    minutes=30
                )
                measurement_end = _parse(dossier["horizon_end"])
                measured = dossier.setdefault("measurements", {})
                assert isinstance(measured, dict)
                for series in history.series:
                    points = measured.setdefault(series.role, {})
                    if not isinstance(points, dict):
                        continue
                    for point in series.points:
                        if not measurement_start <= point.sampled_at <= measurement_end:
                            continue
                        points[point.evidence_id] = {
                            "at": _iso(point.sampled_at),
                            "power_w": point.power_w,
                            "semantics": series.history_semantics,
                        }
                for state in snapshot.current_storage_states:
                    if not measurement_start <= state.measured_at <= measurement_end:
                        continue
                    samples = dossier.setdefault("storage_samples", [])
                    sampled_at = _iso(state.measured_at)
                    if not any(item.get("at") == sampled_at for item in samples):
                        samples.append(
                            {
                                "at": sampled_at,
                                "energy_wh": state.current_stored_energy_wh,
                            }
                        )
                horizon = dossier.get("horizon_end")
                if isinstance(horizon, str) and snapshot.captured_at >= _parse(horizon):
                    self._close(dossier)
            self._save()

    def mark_stress(self, *, marker_id: str, occurred_at: datetime, note: str) -> dict[str, object]:
        if not marker_id.strip() or occurred_at.tzinfo is None:
            raise ValueError("stress marker identity and timezone are required")
        marker = {
            "marker_id": marker_id.strip(),
            "occurred_at": _iso(occurred_at),
            "note": note.strip()[:240],
        }
        attached = 0
        with self._lock:
            dossiers = self._state.get("dossiers", {})
            if isinstance(dossiers, dict):
                for dossier in dossiers.values():
                    if isinstance(dossier, dict) and dossier.get("status") == "measuring":
                        markers = dossier.setdefault("stress_markers", [])
                        if not any(
                            item.get("marker_id") == marker["marker_id"] for item in markers
                        ):
                            markers.append(marker)
                            dossier["projection_state"] = (
                                "superseded_by_manual_stress"
                            )
                            attached += 1
            self._state["latest_stress_marker"] = marker
            self._save()
        return {
            "status": "recorded",
            "marker": marker,
            "open_dossiers": attached,
            "observer_only": True,
        }

    def _close(self, dossier: dict[str, Any]) -> None:
        roles = dossier.get("measurements", {})
        missing = (
            sorted(REQUIRED_ROLES - set(roles))
            if isinstance(roles, dict)
            else sorted(REQUIRED_ROLES)
        )
        if missing:
            dossier["status"] = "insufficient_data"
            dossier["result"] = {"reason": "missing measured series", "missing_roles": missing}
        else:
            canonical = self._canonical_schedule(dossier)
            observer = dossier.get("observer", {}).get("intent_intervals", [])
            results = {
                "canonical": self._replay(dossier, canonical),
                "daily_observer": self._replay(dossier, observer),
            }
            if any(item.get("status") != "complete" for item in results.values()):
                dossier["status"] = "insufficient_data"
                dossier["result"] = {
                    "reason": "measurement coverage incomplete",
                    "planners": results,
                }
            else:
                left, right = results["canonical"], results["daily_observer"]
                left_financial = float(str(left["net_financial_result_eur"]))
                right_financial = float(str(right["net_financial_result_eur"]))
                winner = "equal"
                if left["reserve_respected"] != right["reserve_respected"]:
                    winner = "canonical" if left["reserve_respected"] else "daily_observer"
                elif abs(left_financial - right_financial) > 0.005:
                    winner = "canonical" if left_financial > right_financial else "daily_observer"
                dossier["status"] = "completed"
                dossier["result"] = {
                    "winner": winner,
                    "planners": results,
                    "same_measured_reality": True,
                    "measured_actual": self._actual_summary(dossier),
                }
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dossier, separators=(",", ":")) + "\n")

    @staticmethod
    def _canonical_schedule(dossier: dict[str, Any]) -> list[dict[str, object]]:
        start = _parse(dossier["captured_at"])
        end = _parse(dossier["horizon_end"])
        plan = dossier["canonical"]
        window_start = (
            _parse(plan["charge_window_starts_at"]) if plan.get("charge_window_starts_at") else end
        )
        window_end = (
            _parse(plan["charge_window_ends_at"]) if plan.get("charge_window_ends_at") else end
        )
        boundaries = sorted({start, end, max(start, window_start), min(end, window_end)})
        return [
            {
                "starts_at": _iso(a),
                "ends_at": _iso(b),
                "intent": "nom"
                if a >= window_start and b <= window_end
                else "household_support_only",
            }
            for a, b in zip(boundaries, boundaries[1:], strict=False)
            if a < b
        ]

    def _replay(
        self, dossier: dict[str, Any], schedule: list[dict[str, object]]
    ) -> dict[str, object]:
        physical = dossier["physical"]
        energy = physical["initial_energy_wh"]
        minimum = physical["minimum_energy_wh"]
        target = physical["target_energy_wh"]
        prices = dossier["prices"]
        total_cost = 0.0
        totals = {
            "grid_import_wh": 0.0,
            "grid_export_wh": 0.0,
            "battery_charge_input_wh": 0.0,
            "battery_discharge_output_wh": 0.0,
        }
        minimum_seen = energy
        target_reached_at = None
        for interval in schedule:
            start, end = _parse(str(interval["starts_at"])), _parse(str(interval["ends_at"]))
            pv = self._integrate(dossier, "pv_generation", start, end)
            load = self._integrate(dossier, "household_load", start, end)
            tariff = self._price(prices, start, end)
            if pv is None or load is None or tariff is None:
                return {"status": "insufficient_data", "interval": f"{_iso(start)}/{_iso(end)}"}
            direct = min(pv, load)
            surplus, deficit = pv - direct, load - direct
            intent = interval.get("intent")
            duration_h = (end - start).total_seconds() / 3600.0
            discharge_efficiency = physical["discharge_efficiency"]
            charge_efficiency = physical["charge_efficiency"]
            discharge_limit = physical["maximum_discharge_power_w"] * duration_h
            charge_limit = physical["maximum_charge_power_w"] * duration_h
            storage_output = 0.0
            if intent in {"nom", "household_support_only", "grid_requirement"}:
                available_output = max(0.0, energy - minimum) * discharge_efficiency
                storage_output = min(deficit, available_output, discharge_limit)
                energy -= storage_output / discharge_efficiency
                deficit -= storage_output
            storage_export = 0.0
            if intent == "storage_export":
                available_output = max(0.0, energy - minimum) * discharge_efficiency
                storage_export = min(
                    float(str(interval.get("storage_export_target_wh", 0.0))),
                    available_output,
                    discharge_limit,
                )
                energy -= storage_export / discharge_efficiency
            pv_charge = 0.0
            grid_charge = 0.0
            if intent in {"nom", "grid_requirement"}:
                room_input = max(0.0, target - energy) / charge_efficiency
                pv_charge = min(surplus, room_input, charge_limit)
                energy += pv_charge * charge_efficiency
                surplus -= pv_charge
                if intent == "grid_requirement":
                    grid_charge = min(
                        max(0.0, target - energy) / charge_efficiency,
                        charge_limit - pv_charge,
                    )
                    energy += grid_charge * charge_efficiency
            if target_reached_at is None and energy >= target - 0.5:
                target_reached_at = _iso(end)
            minimum_seen = min(minimum_seen, energy)
            import_price, export_price = tariff
            total_cost += (deficit + grid_charge) / 1000.0 * import_price
            total_cost -= (surplus + storage_export) / 1000.0 * export_price
            totals["grid_import_wh"] += deficit + grid_charge
            totals["grid_export_wh"] += surplus + storage_export
            totals["battery_charge_input_wh"] += pv_charge + grid_charge
            totals["battery_discharge_output_wh"] += (
                storage_output + storage_export
            )
        return {
            "status": "complete",
            "end_energy_wh": round(energy, 3),
            "minimum_energy_wh": round(minimum_seen, 3),
            "reserve_respected": minimum_seen >= minimum - 0.5,
            "target_reached": target_reached_at is not None,
            "target_reached_at": target_reached_at,
            "net_financial_result_eur": round(-total_cost, 4),
            "energy_totals": {
                key: round(value, 3) for key, value in totals.items()
            },
        }

    def _actual_summary(self, dossier: dict[str, Any]) -> dict[str, object]:
        start = _parse(dossier["captured_at"])
        end = _parse(dossier["horizon_end"])
        roles = {
            role: self._integrate(dossier, role, start, end)
            for role in sorted(REQUIRED_ROLES)
        }
        samples = sorted(
            dossier.get("storage_samples", []),
            key=lambda item: item.get("at", ""),
        )
        return {
            "energy_wh_by_role": {
                role: round(value, 3) if value is not None else None
                for role, value in roles.items()
            },
            "storage_energy_at_start_wh": (
                samples[0].get("energy_wh") if samples else None
            ),
            "storage_energy_at_end_wh": (
                samples[-1].get("energy_wh") if samples else None
            ),
            "stress_markers": list(dossier.get("stress_markers", [])),
        }

    @staticmethod
    def _integrate(
        dossier: dict[str, Any], role: str, start: datetime, end: datetime
    ) -> float | None:
        raw = dossier["measurements"].get(role, {})
        points = sorted((_parse(item["at"]), float(item["power_w"])) for item in raw.values())
        prior = [item for item in points if item[0] <= start]
        if not prior:
            return None
        relevant = [prior[-1], *(item for item in points if start < item[0] < end)]
        if relevant[-1][0] < end - timedelta(minutes=30):
            return None
        total = 0.0
        for index, (at, power) in enumerate(relevant):
            segment_start = max(start, at)
            segment_end = min(end, relevant[index + 1][0] if index + 1 < len(relevant) else end)
            if segment_end > segment_start:
                total += max(0.0, power) * (segment_end - segment_start).total_seconds() / 3600.0
        return total

    @staticmethod
    def _price(
        prices: list[dict[str, object]],
        start: datetime,
        end: datetime,
    ) -> tuple[float, float] | None:
        weighted_import = weighted_export = duration = 0.0
        for item in prices:
            left, right = (
                max(start, _parse(str(item["starts_at"]))),
                min(end, _parse(str(item["ends_at"]))),
            )
            if right > left:
                seconds = (right - left).total_seconds()
                weighted_import += seconds * float(
                    str(item["import_eur_per_kwh"])
                )
                weighted_export += seconds * float(
                    str(item["export_eur_per_kwh"])
                )
                duration += seconds
        if duration < (end - start).total_seconds() - 1:
            return None
        return weighted_import / duration, weighted_export / duration

    def dashboard_view(self) -> dict[str, object]:
        with self._lock:
            dossiers = self._state.get("dossiers", {})
            values = list(dossiers.values()) if isinstance(dossiers, dict) else []
            values.sort(key=lambda item: item.get("captured_at", ""), reverse=True)
            cutoff = datetime.now(UTC) - timedelta(hours=48)
            values = [
                item
                for item in values
                if isinstance(item.get("captured_at"), str)
                and _parse(item["captured_at"]) >= cutoff
            ]
            compact = [
                {
                    key: item.get(key)
                    for key in (
                        "comparison_id",
                        "snapshot_id",
                        "captured_at",
                        "horizon_end",
                        "status",
                        "canonical",
                        "observer",
                        "stress_markers",
                        "projection_state",
                        "stress_restart",
                        "result",
                    )
                }
                for item in values[:96]
            ]
        return {
            "observer_only": True,
            "selection_permitted": False,
            "commitment_permitted": False,
            "retention_hours": 48,
            "dossiers": compact,
            "method_version": METHOD_VERSION,
        }
