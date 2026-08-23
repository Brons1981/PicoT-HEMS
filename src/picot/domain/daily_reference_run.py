"""Canonical observer-only result of one independent daily reference run."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.daily_reference_assessment import DailyReferenceAssessmentSet
from picot.domain.daily_reference_financial import DailyReferenceFinancialSet
from picot.domain.daily_reference_simulation import DailyReferenceSimulationSet, PVScenario


@dataclass(frozen=True, slots=True)
class DailyReferenceRun:
    """One lineage-closed physical, assessed and financially valued daily run."""

    run_id: str
    snapshot_id: str
    simulation: DailyReferenceSimulationSet
    assessment: DailyReferenceAssessmentSet
    financial: DailyReferenceFinancialSet
    candidate_input_complete: bool
    observer_only: bool
    selection_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily reference run identity must be explicit.")
        if not self.method_version.strip():
            raise ValueError("Daily reference run method version must be explicit.")
        if {
            self.simulation.snapshot_id,
            self.assessment.snapshot_id,
            self.financial.snapshot_id,
        } != {self.snapshot_id}:
            raise ValueError("Daily reference run components must share one snapshot.")
        if self.assessment.simulation_id != self.simulation.simulation_id:
            raise ValueError("Daily assessment must originate from the run simulation.")
        if self.financial.simulation_id != self.simulation.simulation_id:
            raise ValueError("Daily financial paths must originate from the run simulation.")
        if not self.candidate_input_complete:
            raise ValueError("Incomplete daily reference results may not feed candidates.")
        if not self.observer_only or self.selection_permitted:
            raise ValueError("Daily reference run must remain observer-only and unselected.")
        if not (
            self.simulation.observer_only
            and self.assessment.observer_only
            and self.financial.observer_only
        ):
            raise ValueError("Every daily reference component must remain observer-only.")
        self._validate_scenario_lineage()

    def _validate_scenario_lineage(self) -> None:
        trajectories = {item.scenario: item for item in self.simulation.trajectories}
        assessments = {item.scenario: item for item in self.assessment.assessments}
        financial_paths = {item.scenario: item for item in self.financial.paths}
        if not (
            set(trajectories)
            == set(assessments)
            == set(financial_paths)
            == set(PVScenario)
        ):
            raise ValueError("Daily reference run requires identical scenario coverage.")
        for scenario in PVScenario:
            trajectory = trajectories[scenario]
            assessment = assessments[scenario]
            financial = financial_paths[scenario]
            if assessment.trajectory_id != trajectory.trajectory_id:
                raise ValueError("Daily assessment trajectory lineage does not match.")
            if financial.trajectory_id != trajectory.trajectory_id:
                raise ValueError("Daily financial trajectory lineage does not match.")
            if assessment.interval_count != len(trajectory.intervals):
                raise ValueError("Daily assessment interval count does not match.")
            if (
                financial.intervals[0].starts_at != trajectory.horizon_start
                or financial.intervals[-1].ends_at != trajectory.horizon_end
            ):
                raise ValueError("Daily financial horizon does not match.")
