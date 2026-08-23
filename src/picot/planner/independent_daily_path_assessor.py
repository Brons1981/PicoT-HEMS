"""Assess complete daily reference paths without selecting a winner."""

from __future__ import annotations

from picot.domain.daily_reference_assessment import (
    DailyReferenceAssessmentSet,
    DailyReferencePathAssessment,
    energy_at_or_above,
)
from picot.domain.daily_reference_simulation import (
    DailyReferenceSimulationSet,
    DailyReferenceTrajectory,
)

METHOD_VERSION = "independent-daily-path-assessor:v1"


class IndependentDailyPathAssessor:
    """Summarise only structurally complete observer-only trajectories."""

    def assess(
        self,
        simulation: DailyReferenceSimulationSet,
    ) -> DailyReferenceAssessmentSet:
        horizons = {
            (item.horizon_start, item.horizon_end) for item in simulation.trajectories
        }
        if len(horizons) != 1:
            raise ValueError("Daily paths must share one complete horizon.")
        assessments = tuple(self._assess_path(item) for item in simulation.trajectories)
        return DailyReferenceAssessmentSet(
            assessment_set_id=f"daily-assessment:{simulation.simulation_id}",
            simulation_id=simulation.simulation_id,
            snapshot_id=simulation.snapshot_id,
            assessments=assessments,
            observer_only=True,
            selection_permitted=False,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _assess_path(
        trajectory: DailyReferenceTrajectory,
    ) -> DailyReferencePathAssessment:
        intervals = trajectory.intervals
        minimum_observed_wh = min(
            min(item.storage_energy_at_start_wh, item.storage_energy_at_end_wh)
            for item in intervals
        )
        end_energy_wh = intervals[-1].storage_energy_at_end_wh
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for interval in intervals
                for evidence_id in interval.evidence_ids
            )
        )
        return DailyReferencePathAssessment(
            assessment_id=f"daily-path-assessment:{trajectory.trajectory_id}",
            trajectory_id=trajectory.trajectory_id,
            snapshot_id=trajectory.snapshot_id,
            scenario=trajectory.scenario,
            horizon_start=trajectory.horizon_start,
            horizon_end=trajectory.horizon_end,
            interval_count=len(intervals),
            physically_complete=True,
            target_reached_during_horizon=trajectory.target_reached_at is not None,
            target_reached_at=trajectory.target_reached_at,
            target_held_at_horizon_end=energy_at_or_above(
                end_energy_wh, trajectory.target_storage_energy_wh
            ),
            reserve_respected=energy_at_or_above(
                minimum_observed_wh, trajectory.minimum_storage_energy_wh
            ),
            minimum_storage_energy_observed_wh=minimum_observed_wh,
            storage_energy_at_horizon_end_wh=end_energy_wh,
            household_demand_wh=sum(item.household_demand_wh for item in intervals),
            usable_pv_wh=sum(item.usable_pv_wh for item in intervals),
            pv_to_storage_input_wh=sum(
                item.pv_to_storage_input_wh for item in intervals
            ),
            pv_to_grid_wh=sum(item.pv_to_grid_wh for item in intervals),
            grid_to_household_wh=sum(item.grid_to_household_wh for item in intervals),
            storage_to_household_output_wh=sum(
                item.storage_to_household_output_wh for item in intervals
            ),
            storage_charge_loss_wh=sum(
                item.storage_charge_loss_wh for item in intervals
            ),
            storage_discharge_loss_wh=sum(
                item.storage_discharge_loss_wh for item in intervals
            ),
            minimum_confidence=min(item.confidence for item in intervals),
            evidence_ids=evidence_ids,
            method_version=METHOD_VERSION,
        )
