"""Independent observer-only full-horizon physical simulation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isclose
ENERGY_TOLERANCE_WH = 1e-6


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")


class PVScenario(StrEnum):
    """PV uncertainty trajectories required by the daily reference simulation."""

    LOWER = "lower"
    CENTRAL = "central"
    UPPER = "upper"


@dataclass(frozen=True, slots=True)
class DailyReferenceInterval:
    """One conserved physical interval, independent from planner Candidates."""

    starts_at: datetime
    ends_at: datetime
    household_demand_wh: float
    usable_pv_wh: float
    pv_to_household_wh: float
    pv_to_storage_input_wh: float
    pv_to_grid_wh: float
    grid_to_household_wh: float
    grid_to_storage_input_wh: float
    storage_to_household_output_wh: float
    storage_charge_loss_wh: float
    storage_discharge_loss_wh: float
    storage_energy_at_start_wh: float
    storage_energy_at_end_wh: float
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.starts_at, "Daily interval start")
        _aware(self.ends_at, "Daily interval end")
        if self.ends_at <= self.starts_at:
            raise ValueError("Daily interval must end after it starts.")
        for value, label in (
            (self.household_demand_wh, "Household demand"),
            (self.usable_pv_wh, "Usable PV"),
            (self.pv_to_household_wh, "PV to household"),
            (self.pv_to_storage_input_wh, "PV to storage"),
            (self.pv_to_grid_wh, "PV to grid"),
            (self.grid_to_household_wh, "Grid to household"),
            (self.grid_to_storage_input_wh, "Grid to storage"),
            (self.storage_to_household_output_wh, "Storage to household"),
            (self.storage_charge_loss_wh, "Storage charge loss"),
            (self.storage_discharge_loss_wh, "Storage discharge loss"),
            (self.storage_energy_at_start_wh, "Storage energy at start"),
            (self.storage_energy_at_end_wh, "Storage energy at end"),
        ):
            if value < 0.0:
                raise ValueError(f"{label} must not be negative.")
        if self.grid_to_storage_input_wh > ENERGY_TOLERANCE_WH:
            raise ValueError("The NOM baseline may not charge storage from grid.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Daily interval confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("Daily interval evidence must be explicit.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Daily interval evidence IDs must be unique.")
        self._require_close(
            self.usable_pv_wh,
            self.pv_to_household_wh + self.pv_to_storage_input_wh + self.pv_to_grid_wh,
            "PV conservation",
        )
        self._require_close(
            self.household_demand_wh,
            self.pv_to_household_wh
            + self.storage_to_household_output_wh
            + self.grid_to_household_wh,
            "household conservation",
        )
        storage_energy_added_wh = (
            self.pv_to_storage_input_wh
            + self.grid_to_storage_input_wh
            - self.storage_charge_loss_wh
        )
        storage_energy_removed_wh = (
            self.storage_to_household_output_wh + self.storage_discharge_loss_wh
        )
        self._require_close(
            self.storage_energy_at_end_wh,
            self.storage_energy_at_start_wh
            + storage_energy_added_wh
            - storage_energy_removed_wh,
            "storage conservation",
        )

    @staticmethod
    def _require_close(expected: float, actual: float, label: str) -> None:
        if not isclose(expected, actual, rel_tol=1e-9, abs_tol=ENERGY_TOLERANCE_WH):
            raise ValueError(
                f"Daily reference {label} failed: expected {expected}, calculated {actual}."
            )


@dataclass(frozen=True, slots=True)
class DailyReferenceTrajectory:
    """Complete NOM trajectory for one PV scenario."""

    trajectory_id: str
    snapshot_id: str
    scenario: PVScenario
    horizon_start: datetime
    horizon_end: datetime
    target_storage_energy_wh: float
    minimum_storage_energy_wh: float
    target_reached_at: datetime | None
    intervals: tuple[DailyReferenceInterval, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.trajectory_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily trajectory identity must be explicit.")
        _aware(self.horizon_start, "Daily trajectory horizon start")
        _aware(self.horizon_end, "Daily trajectory horizon end")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("Daily trajectory horizon must end after it starts.")
        if not 0.0 <= self.minimum_storage_energy_wh <= self.target_storage_energy_wh:
            raise ValueError("Daily storage limits must be ordered and non-negative.")
        if not self.intervals:
            raise ValueError("Daily trajectory requires intervals.")
        if self.intervals[0].starts_at != self.horizon_start:
            raise ValueError("Daily trajectory must start at its declared horizon.")
        if self.intervals[-1].ends_at != self.horizon_end:
            raise ValueError("Daily trajectory must end at its declared horizon.")
        for left, right in zip(self.intervals, self.intervals[1:], strict=False):
            if left.ends_at != right.starts_at:
                raise ValueError("Daily trajectory intervals must be contiguous.")
            if not isclose(
                left.storage_energy_at_end_wh,
                right.storage_energy_at_start_wh,
                rel_tol=1e-9,
                abs_tol=ENERGY_TOLERANCE_WH,
            ):
                raise ValueError("Daily storage energy must remain continuous.")
        if self.target_reached_at is not None:
            _aware(self.target_reached_at, "Daily target time")
            if not self.horizon_start <= self.target_reached_at <= self.horizon_end:
                raise ValueError("Daily target time must remain within the horizon.")
        if not self.method_version.strip():
            raise ValueError("Daily trajectory method version must be explicit.")


@dataclass(frozen=True, slots=True)
class DailyReferenceSimulationSet:
    """Three independent physical trajectories that cannot affect live planning."""

    simulation_id: str
    snapshot_id: str
    trajectories: tuple[DailyReferenceTrajectory, ...]
    observer_only: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.simulation_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily simulation identity must be explicit.")
        scenarios = tuple(item.scenario for item in self.trajectories)
        if set(scenarios) != set(PVScenario) or len(scenarios) != len(PVScenario):
            raise ValueError("Daily simulation requires exactly lower, central and upper.")
        if any(item.snapshot_id != self.snapshot_id for item in self.trajectories):
            raise ValueError("Daily trajectories must share the simulation snapshot.")
        if not self.observer_only:
            raise ValueError("Daily reference simulation must remain observer-only.")
        if not self.method_version.strip():
            raise ValueError("Daily simulation method version must be explicit.")
