"""Regime-aware closed-loop reality check for live household energy flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class LiveFlowObserver:
    """Validate live flow using ADR-042 control regimes and elapsed-time hysteresis."""

    green_limit_w: float = 50.0
    red_limit_w: float = 150.0
    red_timeout_s: float = 120.0
    grey_timeout_s: float = 300.0
    _active_regime: str | None = None
    _grey_started_at: datetime | None = None
    _red_started_at: datetime | None = None
    _contradiction_started_at: datetime | None = None

    @staticmethod
    def _number(event: dict[str, object], key: str) -> float | None:
        value = event.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _timestamp(event: dict[str, object]) -> datetime | None:
        raw = event.get("telemetry_updated_at") or event.get("captured_at")
        if not isinstance(raw, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    @staticmethod
    def _regime(event: dict[str, object]) -> str | None:
        raw = event.get("zendure_requested_mode") or event.get("zendure_actual_mode")
        if not isinstance(raw, str):
            return None
        mode = raw.strip().casefold()
        if mode in {"nul op de meter", "nom"}:
            return "delegated_bidirectional"
        if mode == "alleen slim ontladen":
            return "delegated_discharge_only"
        if mode == "alleen slim opladen":
            return "delegated_charge_only"
        if "standby" in mode:
            return "standby"
        if "handmatig" in mode and "ontla" in mode:
            return "forced_discharge"
        if "handmatig" in mode and ("opla" in mode or "laden" in mode):
            return "forced_charge"
        return None

    @staticmethod
    def _elapsed(started_at: datetime | None, now: datetime | None) -> float:
        if started_at is None or now is None:
            return 0.0
        return max(0.0, (now - started_at).total_seconds())

    def _reset_timers(self) -> None:
        self._grey_started_at = None
        self._red_started_at = None
        self._contradiction_started_at = None

    def evaluate(self, event: dict[str, object]) -> dict[str, object]:
        """Return explainable ADR-042 flow validation for one poll."""

        now = self._timestamp(event)
        regime = self._regime(event)
        if regime != self._active_regime:
            self._active_regime = regime
            self._reset_timers()

        grid_export_w = self._number(event, "grid_export_w")
        grid_import_w = self._number(event, "grid_import_w")
        discharge_w = self._number(event, "zendure_discharge_power_w")
        charge_w = self._number(event, "zendure_charge_power_w")
        pv_w = self._number(event, "goodwe_solar_power_w")
        signed_grid_w = None
        if grid_import_w is not None and grid_export_w is not None:
            signed_grid_w = grid_import_w - grid_export_w

        band = "unavailable"
        deviation_w: float | None = None
        contradiction = False
        status = "insufficient_evidence"
        recommendation = "observe"

        if regime == "delegated_discharge_only" and signed_grid_w is not None:
            deviation_w = abs(signed_grid_w)
            if deviation_w < self.green_limit_w:
                band = "green"
                self._grey_started_at = None
                self._red_started_at = None
            elif deviation_w <= self.red_limit_w:
                band = "grey"
                self._red_started_at = None
                self._grey_started_at = self._grey_started_at or now
            else:
                band = "red"
                self._grey_started_at = None
                self._red_started_at = self._red_started_at or now
            status = f"tracking_{band}"

        elif regime == "delegated_bidirectional":
            complete = None not in (grid_export_w, discharge_w, pv_w)
            if complete:
                contradiction = bool(
                    grid_export_w is not None
                    and discharge_w is not None
                    and pv_w is not None
                    and grid_export_w > self.red_limit_w
                    and discharge_w > self.red_limit_w
                    and pv_w > self.green_limit_w
                )
                if contradiction:
                    self._contradiction_started_at = self._contradiction_started_at or now
                    band = "red"
                    status = "delegated_bidirectional_contradiction"
                else:
                    self._contradiction_started_at = None
                    band = "green"
                    status = "delegated_balancing"

        elif regime == "standby" and charge_w is not None and discharge_w is not None:
            deviation_w = max(charge_w, discharge_w)
            if deviation_w < self.green_limit_w:
                band = "green"
                self._grey_started_at = None
                self._red_started_at = None
            elif deviation_w <= self.red_limit_w:
                band = "grey"
                self._red_started_at = None
                self._grey_started_at = self._grey_started_at or now
            else:
                band = "red"
                self._grey_started_at = None
                self._red_started_at = self._red_started_at or now
            status = f"standby_{band}"

        grey_elapsed = self._elapsed(self._grey_started_at, now)
        red_elapsed = self._elapsed(self._red_started_at, now)
        contradiction_elapsed = self._elapsed(self._contradiction_started_at, now)
        actionable = (
            grey_elapsed >= self.grey_timeout_s
            or red_elapsed >= self.red_timeout_s
            or contradiction_elapsed >= self.red_timeout_s
        )
        if actionable:
            recommendation = "replan_from_flow_validation"

        return {
            "flow_observer_status": status,
            "flow_observer_control_regime": regime,
            "flow_observer_responsibility": (
                "delegated" if regime and regime.startswith("delegated_") else "picot_setpoint"
            ) if regime else "unknown",
            "flow_observer_validation_band": band,
            "flow_observer_tracking_deviation_w": deviation_w,
            "flow_observer_raw_mismatch": contradiction or band in {"grey", "red"},
            "flow_observer_persistent_mismatch": actionable,
            "flow_observer_grey_elapsed_s": grey_elapsed,
            "flow_observer_grey_limit_s": self.grey_timeout_s,
            "flow_observer_red_elapsed_s": max(red_elapsed, contradiction_elapsed),
            "flow_observer_red_limit_s": self.red_timeout_s,
            "flow_observer_recommendation": recommendation,
            "flow_observer_grid_export_w": grid_export_w,
            "flow_observer_battery_discharge_w": discharge_w,
            "flow_observer_pv_power_w": pv_w,
            "flow_observer_control_change_allowed": False,
            "flow_observer_consecutive_samples": 0,
            "flow_observer_required_samples": 0,
        }
