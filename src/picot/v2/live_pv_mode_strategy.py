"""Deterministic mode strategy for the first controlled live PV canary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

NOM_VENDOR_MODE = "Nul op de meter"
SMART_DISCHARGE_VENDOR_MODE = "Alleen slim ontladen"


@dataclass(frozen=True, slots=True)
class LivePVModeInput:
    """Fresh runtime evidence used by the narrow live mode strategy."""

    now: datetime
    current_vendor_mode: str
    charge_window_active: bool
    battery_power_w: float
    evidence_age_seconds: float
    manual_override_active: bool
    live_enabled: bool

    def __post_init__(self) -> None:
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if not self.current_vendor_mode.strip():
            raise ValueError("current_vendor_mode must be explicit")
        if not isfinite(self.battery_power_w):
            raise ValueError("battery_power_w must be finite")
        if (
            not isfinite(self.evidence_age_seconds)
            or self.evidence_age_seconds < 0.0
        ):
            raise ValueError(
                "evidence_age_seconds must be finite and non-negative"
            )


@dataclass(frozen=True, slots=True)
class LivePVModeDecision:
    """Explainable desired mode and whether external dispatch is allowed."""

    requested_vendor_mode: str | None
    reason: str
    dispatch_allowed: bool


@dataclass(slots=True)
class LivePVModeStrategy:
    """Apply NOM charging, turning-point hysteresis, and a discharge hold."""

    turning_point_duration: timedelta = timedelta(minutes=5)
    smart_discharge_minimum_hold: timedelta = timedelta(minutes=15)
    maximum_evidence_age_seconds: float = 60.0
    discharge_threshold_w: float = 50.0
    _discharge_started_at: datetime | None = None
    _smart_discharge_applied_at: datetime | None = None

    def record_applied_mode(
        self,
        vendor_mode: str,
        *,
        applied_at: datetime,
    ) -> None:
        """Record confirmed planner dispatch for hysteresis across polls."""
        if applied_at.tzinfo is None or applied_at.utcoffset() is None:
            raise ValueError("applied_at must be timezone-aware")
        if vendor_mode == SMART_DISCHARGE_VENDOR_MODE:
            self._smart_discharge_applied_at = applied_at
        elif vendor_mode == NOM_VENDOR_MODE:
            self._smart_discharge_applied_at = None
        self._discharge_started_at = None

    def evaluate(self, value: LivePVModeInput) -> LivePVModeDecision:
        """Return one fail-closed, idempotent mode decision."""
        if value.manual_override_active:
            self._discharge_started_at = None
            return LivePVModeDecision(
                None,
                "manual_override_active",
                False,
            )
        if value.evidence_age_seconds > self.maximum_evidence_age_seconds:
            self._discharge_started_at = None
            return LivePVModeDecision(None, "evidence_stale", False)

        dispatch_allowed = value.live_enabled
        if value.current_vendor_mode == NOM_VENDOR_MODE:
            return self._evaluate_nom(value, dispatch_allowed)

        self._discharge_started_at = None
        if not value.charge_window_active:
            return LivePVModeDecision(
                None,
                "smart_discharge_held_until_new_charge_window",
                dispatch_allowed,
            )
        if (
            self._smart_discharge_applied_at is not None
            and value.now - self._smart_discharge_applied_at
            < self.smart_discharge_minimum_hold
        ):
            return LivePVModeDecision(
                None,
                "smart_discharge_minimum_hold_active",
                dispatch_allowed,
            )
        return LivePVModeDecision(
            NOM_VENDOR_MODE,
            "favourable_pv_charge_window_started",
            dispatch_allowed,
        )

    def _evaluate_nom(
        self,
        value: LivePVModeInput,
        dispatch_allowed: bool,
    ) -> LivePVModeDecision:
        if value.battery_power_w > -self.discharge_threshold_w:
            self._discharge_started_at = None
            return LivePVModeDecision(
                None,
                "nom_charge_or_neutral_active",
                dispatch_allowed,
            )
        if self._discharge_started_at is None:
            self._discharge_started_at = value.now
        if value.now - self._discharge_started_at < self.turning_point_duration:
            return LivePVModeDecision(
                None,
                "discharge_turning_point_pending",
                dispatch_allowed,
            )
        return LivePVModeDecision(
            SMART_DISCHARGE_VENDOR_MODE,
            "battery_discharge_turning_point_sustained",
            dispatch_allowed,
        )
