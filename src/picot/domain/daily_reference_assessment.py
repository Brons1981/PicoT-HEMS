"""Observer-only assessment contracts for complete daily physical paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isclose

from picot.domain.daily_reference_simulation import PVScenario


@dataclass(frozen=True, slots=True)
class DailyReferencePathAssessment:
    """Physical outcome of one complete uncertainty trajectory, without ranking."""

    assessment_id: str
    trajectory_id: str
    snapshot_id: str
    scenario: PVScenario
    horizon_start: datetime
    horizon_end: datetime
    interval_count: int
    physically_complete: bool
    target_reached_during_horizon: bool
    target_reached_at: datetime | None
    target_held_at_horizon_end: bool
    reserve_respected: bool
    minimum_storage_energy_observed_wh: float
    storage_energy_at_horizon_end_wh: float
    household_demand_wh: float
    usable_pv_wh: float
    pv_to_storage_input_wh: float
    pv_to_grid_wh: float
    grid_to_household_wh: float
    storage_to_household_output_wh: float
    storage_charge_loss_wh: float
    storage_discharge_loss_wh: float
    minimum_confidence: float
    evidence_ids: tuple[str, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.assessment_id.strip() or not self.trajectory_id.strip():
            raise ValueError("Daily path assessment identity must be explicit.")
        if not self.snapshot_id.strip() or not self.method_version.strip():
            raise ValueError("Daily path assessment lineage must be explicit.")
        if self.horizon_end <= self.horizon_start or self.interval_count <= 0:
            raise ValueError("Daily path assessment horizon must be complete.")
        if not self.physically_complete:
            raise ValueError("Incomplete daily paths may not be assessed.")
        if self.target_reached_during_horizon != (self.target_reached_at is not None):
            raise ValueError("Daily target outcome and target time must agree.")
        if self.target_reached_at is not None and not (
            self.horizon_start <= self.target_reached_at <= self.horizon_end
        ):
            raise ValueError("Daily target time must remain within the horizon.")
        for value in (
            self.minimum_storage_energy_observed_wh,
            self.storage_energy_at_horizon_end_wh,
            self.household_demand_wh,
            self.usable_pv_wh,
            self.pv_to_storage_input_wh,
            self.pv_to_grid_wh,
            self.grid_to_household_wh,
            self.storage_to_household_output_wh,
            self.storage_charge_loss_wh,
            self.storage_discharge_loss_wh,
        ):
            if value < 0.0:
                raise ValueError("Daily path assessment energy must not be negative.")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("Daily path confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids or len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Daily path evidence must be explicit and unique.")


@dataclass(frozen=True, slots=True)
class DailyReferenceAssessmentSet:
    """Unranked assessments for all required PV uncertainty paths."""

    assessment_set_id: str
    simulation_id: str
    snapshot_id: str
    assessments: tuple[DailyReferencePathAssessment, ...]
    observer_only: bool
    selection_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.assessment_set_id.strip() or not self.simulation_id.strip():
            raise ValueError("Daily assessment set identity must be explicit.")
        if not self.snapshot_id.strip() or not self.method_version.strip():
            raise ValueError("Daily assessment set lineage must be explicit.")
        scenarios = tuple(item.scenario for item in self.assessments)
        if set(scenarios) != set(PVScenario) or len(scenarios) != len(PVScenario):
            raise ValueError("Daily assessment requires exactly lower, central and upper.")
        if any(item.snapshot_id != self.snapshot_id for item in self.assessments):
            raise ValueError("Daily assessments must share one snapshot.")
        if not self.observer_only or self.selection_permitted:
            raise ValueError("Daily assessment must remain observer-only and unranked.")


def energy_at_or_above(value: float, boundary: float) -> bool:
    """Compare physical energy using the simulator's numerical tolerance."""

    return value > boundary or isclose(value, boundary, rel_tol=1e-9, abs_tol=1e-6)
