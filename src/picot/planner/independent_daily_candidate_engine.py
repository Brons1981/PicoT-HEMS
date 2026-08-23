"""Form candidates exclusively from one canonical independent daily run."""

from __future__ import annotations

from picot.domain.daily_reference_candidate import (
    DailyReferenceCandidate,
    DailyReferenceCandidateFamily,
    DailyReferenceCandidateScenario,
    DailyReferenceCandidateSet,
    DailyReferencePortfolioCandidateSet,
)
from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.daily_reference_portfolio import (
    DailyReferencePortfolio,
    DailyReferenceStrategyResult,
)
from picot.domain.daily_reference_run import DailyReferenceRun
from picot.domain.daily_reference_simulation import PVScenario

METHOD_VERSION = "independent-daily-candidate-engine:v1"


class IndependentDailyCandidateEngine:
    """Create only candidates already proven by the canonical daily run."""

    def build(self, run: DailyReferenceRun) -> DailyReferenceCandidateSet:
        if not run.candidate_input_complete:
            raise ValueError("Reference Candidate Engine requires a complete daily run.")
        candidate = self._build_candidate(
            run=run,
            family=DailyReferenceCandidateFamily.NOM_FULL_HORIZON,
            intent_schedule_id="nom-full-horizon",
            intents_used=(DailyStorageIntent.NOM,),
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

    def build_portfolio(
        self,
        portfolio: DailyReferencePortfolio,
    ) -> DailyReferencePortfolioCandidateSet:
        candidates = tuple(
            self._build_strategy_candidate(item)
            for item in portfolio.strategy_results
        )
        return DailyReferencePortfolioCandidateSet(
            candidate_set_id=f"daily-portfolio-candidates:{portfolio.portfolio_id}",
            source_portfolio_id=portfolio.portfolio_id,
            snapshot_id=portfolio.snapshot_id,
            candidates=candidates,
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
        )

    def _build_strategy_candidate(
        self,
        strategy: DailyReferenceStrategyResult,
    ) -> DailyReferenceCandidate:
        intents_used = tuple(
            dict.fromkeys(item.intent for item in strategy.intent_schedule.intervals)
        )
        family_by_intent = {
            DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY: (
                DailyReferenceCandidateFamily.HOUSEHOLD_SUPPORT_ONLY
            ),
            DailyStorageIntent.NOM: DailyReferenceCandidateFamily.NOM,
            DailyStorageIntent.STANDBY: DailyReferenceCandidateFamily.STANDBY,
            DailyStorageIntent.GRID_REQUIREMENT: (
                DailyReferenceCandidateFamily.GRID_REQUIREMENT
            ),
            DailyStorageIntent.STORAGE_EXPORT: (
                DailyReferenceCandidateFamily.STORAGE_EXPORT
            ),
        }
        family = (
            family_by_intent[intents_used[0]]
            if len(intents_used) == 1
            else DailyReferenceCandidateFamily.MIXED_SCHEDULE
        )
        return self._build_candidate(
            run=strategy.run,
            family=family,
            intent_schedule_id=strategy.intent_schedule.schedule_id,
            intents_used=intents_used,
        )

    @staticmethod
    def _build_candidate(
        *,
        run: DailyReferenceRun,
        family: DailyReferenceCandidateFamily,
        intent_schedule_id: str,
        intents_used: tuple[DailyStorageIntent, ...],
    ) -> DailyReferenceCandidate:
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
            candidate_id=f"daily-candidate:{run.run_id}:{intent_schedule_id}",
            source_run_id=run.run_id,
            snapshot_id=run.snapshot_id,
            family=family,
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
            intent_schedule_id=intent_schedule_id,
            intents_used=intents_used,
        )
        return candidate
