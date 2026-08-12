"""Read-only closed-loop reality check for live household energy flow."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LiveFlowObserver:
    """Detect persistent discharge/export contradictions without control authority."""

    required_consecutive_samples: int = 3
    _mismatch_samples: int = 0

    @staticmethod
    def _number(event: dict[str, object], key: str) -> float | None:
        value = event.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def evaluate(self, event: dict[str, object]) -> dict[str, object]:
        """Return explainable raw and debounced flow observations for one poll."""

        grid_export_w = self._number(event, "grid_export_w")
        discharge_w = self._number(event, "zendure_discharge_power_w")
        pv_w = self._number(event, "goodwe_solar_power_w")
        evidence_complete = None not in (grid_export_w, discharge_w, pv_w)
        mismatch = bool(
            evidence_complete
            and grid_export_w is not None
            and discharge_w is not None
            and pv_w is not None
            and grid_export_w > 0.0
            and discharge_w > 0.0
            and pv_w > 0.0
        )
        if mismatch:
            self._mismatch_samples += 1
        else:
            self._mismatch_samples = 0
        persistent = self._mismatch_samples >= self.required_consecutive_samples
        status = "insufficient_evidence"
        recommendation = "observe"
        if evidence_complete:
            status = "discharge_while_exporting" if mismatch else "flow_consistent"
        if persistent:
            recommendation = "stop_discharge_and_reassess_pv_charge"
        return {
            "flow_observer_status": status,
            "flow_observer_raw_mismatch": mismatch,
            "flow_observer_persistent_mismatch": persistent,
            "flow_observer_consecutive_samples": self._mismatch_samples,
            "flow_observer_required_samples": self.required_consecutive_samples,
            "flow_observer_recommendation": recommendation,
            "flow_observer_grid_export_w": grid_export_w,
            "flow_observer_battery_discharge_w": discharge_w,
            "flow_observer_pv_power_w": pv_w,
            "flow_observer_control_change_allowed": False,
        }
