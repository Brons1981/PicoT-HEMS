"""Form candidates exclusively from one canonical independent daily run."""

from __future__ import annotations

from picot.domain.daily_reference_candidate import (
    DailyReferenceCandidate,
    DailyReferenceCandidateFamily,
    DailyReferenceCandidateScenario,
    DailyReferenceCandidateSet,
    DailyReferencePortfolioCandidateSet,
)
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyStorageIntent,
)
from picot.domain.daily_reference_portfolio import (
    DailyReferencePortfolio,
    DailyReferenceStrategyResult,
)
from picot.domain.daily_reference_run import DailyReferenceRun
from picot.domain.daily_reference_simulation import PVScenario

METHOD_VERSION = "independent-daily-candidate-engine:v2"


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
            average_charge_window_price_eur_per_kwh=(
                self._average_charge_window_price(strategy)
            ),
            charge_window_confidence=self._charge_window_confidence(strategy),
        )

    @staticmethod
    def _build_candidate(
        *,
        run: DailyReferenceRun,
        family: DailyReferenceCandidateFamily,
        intent_schedule_id: str,
        intents_used: tuple[DailyStorageIntent, ...],
        average_charge_window_price_eur_per_kwh: float | None = None,
        charge_window_confidence: float | None = None,
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
            average_charge_window_price_eur_per_kwh=(
                average_charge_window_price_eur_per_kwh
            ),
            charge_window_confidence=charge_window_confidence,
        )
        return candidate

    @staticmethod
    def _charge_intervals(
        strategy: DailyReferenceStrategyResult,
    ) -> tuple[DailyReferenceIntentInterval, ...]:
        charge_intents = {DailyStorageIntent.NOM, DailyStorageIntent.GRID_REQUIREMENT}
        return tuple(
            item
            for item in strategy.intent_schedule.intervals
            if item.intent in charge_intents
        )

    @classmethod
    def _average_charge_window_price(
        cls,
        strategy: DailyReferenceStrategyResult,
    ) -> float | None:
        charge_intervals = cls._charge_intervals(strategy)
        if not charge_intervals:
            return None
        financial = strategy.run.financial.paths[0].intervals
        weighted: list[tuple[float, float]] = []
        for tariff in financial:
            for charge in charge_intervals:
                if (
                    tariff.starts_at >= charge.ends_at
                    or tariff.ends_at <= charge.starts_at
                ):
                    continue
                seconds = (
                    min(tariff.ends_at, charge.ends_at)
                    - max(tariff.starts_at, charge.starts_at)
                ).total_seconds()
                price = (
                    tariff.export_eur_per_kwh
                    if charge.intent is DailyStorageIntent.NOM
                    else tariff.import_eur_per_kwh
                )
                weighted.append((price, seconds))
        total_seconds = sum(seconds for _, seconds in weighted)
        return (
            sum(price * seconds for price, seconds in weighted) / total_seconds
            if total_seconds > 0.0
            else None
        )

    @classmethod
    def _charge_window_confidence(
        cls,
        strategy: DailyReferenceStrategyResult,
    ) -> float | None:
        charge_intervals = cls._charge_intervals(strategy)
        if not charge_intervals:
            return None
        confidences = tuple(
            interval.confidence
            for trajectory in strategy.run.simulation.trajectories
            for interval in trajectory.intervals
            if any(
                interval.starts_at < charge.ends_at
                and interval.ends_at > charge.starts_at
                for charge in charge_intervals
            )
        )
        return min(confidences) if confidences else None
