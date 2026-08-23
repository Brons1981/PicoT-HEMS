"""Form candidates exclusively from one canonical independent daily run."""

from __future__ import annotations

from picot.domain.daily_reference_candidate import (
    DailyReferenceCandidate,
    DailyReferenceCandidateFamily,
    DailyReferenceCandidateScenario,
    DailyReferenceCandidateSet,
)
from picot.domain.daily_reference_run import DailyReferenceRun
from picot.domain.daily_reference_simulation import PVScenario

METHOD_VERSION = "independent-daily-candidate-engine:v1"


class IndependentDailyCandidateEngine:
    """Create only candidates already proven by the canonical daily run."""

    def build(self, run: DailyReferenceRun) -> DailyReferenceCandidateSet:
        if not run.candidate_input_complete:
            raise ValueError("Reference Candidate Engine requires a complete daily run.")
        assessments = {item.scenario: item for item in run.assessment.assessments}
        financial = {item.scenario: item for item in run.financial.paths}
        outcomes = tuple(
            DailyReferenceCandidateScenario(
                scenario=scenario,
                trajectory_id=assessments[scenario].trajectory_id,
                physically_complete=assessments[scenario].physically_complete,
                target_reached_during_horizon=(
                    assessments[scenario].target_reached_during_horizon
                ),
                target_reached_at=assessments[scenario].target_reached_at,
                target_held_at_horizon_end=(
                    assessments[scenario].target_held_at_horizon_end
                ),
                reserve_respected=assessments[scenario].reserve_respected,
                storage_energy_at_horizon_end_wh=(
                    assessments[scenario].storage_energy_at_horizon_end_wh
                ),
                net_financial_result_eur=(
                    financial[scenario].net_financial_result_eur
                ),
                confidence=min(
                    assessments[scenario].minimum_confidence,
                    financial[scenario].confidence,
                ),
            )
            for scenario in PVScenario
        )
        candidate = DailyReferenceCandidate(
            candidate_id=f"daily-candidate:{run.run_id}:nom-full-horizon",
            source_run_id=run.run_id,
            snapshot_id=run.snapshot_id,
            family=DailyReferenceCandidateFamily.NOM_FULL_HORIZON,
            scenario_outcomes=outcomes,
            complete_across_scenarios=all(
                item.physically_complete for item in outcomes
            ),
            target_reached_across_scenarios=all(
                item.target_reached_during_horizon for item in outcomes
            ),
            target_held_across_scenarios=all(
                item.target_held_at_horizon_end for item in outcomes
            ),
            reserve_respected_across_scenarios=all(
                item.reserve_respected for item in outcomes
            ),
            worst_case_financial_result_eur=min(
                item.net_financial_result_eur for item in outcomes
            ),
            minimum_confidence=min(item.confidence for item in outcomes),
            observer_only=True,
            selection_eligible=False,
            method_version=METHOD_VERSION,
        )
        return DailyReferenceCandidateSet(
            candidate_set_id=f"daily-candidates:{run.run_id}",
            source_run_id=run.run_id,
            snapshot_id=run.snapshot_id,
            candidates=(candidate,),
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
        )
