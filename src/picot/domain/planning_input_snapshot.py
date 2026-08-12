"""Immutable input envelope for one deterministic Planner Run.

The snapshot contains only PicoT domain data. It never contains Home Assistant
entity IDs, vendor objects or live integration handles. See ADR-017 and ADR-028.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.forecast import ForecastSet
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import PlannerStrategy


class RuntimePressureState(StrEnum):
    """Runtime resource state captured for a Planner Run."""

    NORMAL = "normal"
    TRANSIENT_PRESSURE = "transient_pressure"
    SUSTAINED_PRESSURE = "sustained_pressure"


@dataclass(frozen=True, slots=True)
class PlanningInputVersions:
    """Versions of mutable input groups captured in one atomic snapshot."""

    capability_mapping: int
    user_rules: int
    commitments: int
    household_state: int
    forecasts: int

    def __post_init__(self) -> None:
        for name, value in (
            ("capability_mapping", self.capability_mapping),
            ("user_rules", self.user_rules),
            ("commitments", self.commitments),
            ("household_state", self.household_state),
            ("forecasts", self.forecasts),
        ):
            if value < 1:
                raise ValueError(f"{name} version must be at least 1.")


@dataclass(frozen=True, slots=True)
class PlanningInputSnapshot:
    """Atomic and immutable temporal input envelope for one Planner Run."""

    snapshot_id: str
    captured_at: datetime
    horizon_end: datetime
    strategy: PlannerStrategy
    household_state: HouseholdState
    forecasts: ForecastSet
    runtime_state: RuntimePressureState
    versions: PlanningInputVersions
    replan_reasons: tuple[str, ...]
    household_load_forecast: HouseholdLoadForecast | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("Snapshot ID must not be empty.")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("Snapshot capture time must be timezone-aware.")
        if self.horizon_end.tzinfo is None or self.horizon_end.utcoffset() is None:
            raise ValueError("Planning horizon end must be timezone-aware.")
        if self.horizon_end <= self.captured_at:
            raise ValueError("Planning horizon must end after snapshot capture time.")
        if self.household_state.measured_at > self.captured_at:
            raise ValueError("Household state cannot be measured after snapshot capture time.")
        if any(series.created_at > self.captured_at for series in self.forecasts.series):
            raise ValueError("Forecasts cannot be created after snapshot capture time.")
        if any(series.is_expired_at(self.captured_at) for series in self.forecasts.series):
            raise ValueError("Expired forecasts cannot enter a Planning Input Snapshot.")
        if not self.replan_reasons:
            raise ValueError("A Planning Input Snapshot requires a replan reason.")
        if any(not reason.strip() for reason in self.replan_reasons):
            raise ValueError("Replan reasons must not be empty.")

        load_forecast = self.household_load_forecast
        if load_forecast is not None:
            if load_forecast.created_at > self.captured_at:
                raise ValueError("Household load forecast cannot be created after snapshot capture time.")
            if load_forecast.horizon_start != self.captured_at:
                raise ValueError("Household load forecast must start at snapshot capture time.")
            if load_forecast.horizon_end != self.horizon_end:
                raise ValueError("Household load forecast must cover the complete planning horizon.")
