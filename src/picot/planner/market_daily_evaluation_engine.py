"""Evaluation-owned MEP candidate selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
from picot.planner.market_daily_planner import (
    METHOD_VERSION,
    MarketDailyCandidatePortfolio,
    MarketDailyPlan,
    MarketRouteAssessment,
)
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.plan_commitment_store import ActivePlanCommitment


@dataclass(frozen=True, slots=True)
class MarketDailyCommitmentDecision:
    """Evaluation-owned incumbent/challenger decision evidence."""

    incumbent_retained: bool
    decisive_step: str | None
    objective_difference_eur: float | None
    switching_margin_eur: float


class MarketDailyEvaluationEngine:
    """Select one MEP winner without generating or executing candidates."""

    @staticmethod
    def _market_charge_starts_at(
        assessment: MarketRouteAssessment,
    ) -> datetime:
        return next(
            (
                interval.starts_at
                for interval in assessment.intent_schedule.intervals
                if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
            ),
            assessment.intent_schedule.horizon_start,
        )

    @classmethod
    def _market_assessment_key(
        cls,
        assessment: MarketRouteAssessment,
    ) -> tuple[float, float, float, datetime, str]:
        """Apply the explicit financial, PV-first and timing comparison order."""

        maximum_grid_input_wh = max(
            item.grid_to_storage_input_wh for item in assessment.scenario_evidence
        )
        return (
            assessment.worst_case_incremental_result_eur,
            assessment.minimum_incremental_result_eur_per_exported_kwh,
            -maximum_grid_input_wh,
            cls._market_charge_starts_at(assessment),
            assessment.market_schedule_id,
        )

    @classmethod
    def select_market_assessment(
        cls,
        assessments: tuple[MarketRouteAssessment, ...],
    ) -> MarketRouteAssessment | None:
        """Select one admitted market Candidate through the Evaluation boundary."""

        admitted = tuple(item for item in assessments if item.admitted)
        return max(admitted, key=cls._market_assessment_key) if admitted else None

    def evaluate(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        portfolio: MarketDailyCandidatePortfolio,
        dispatch_authority: bool = False,
    ) -> MarketDailyPlan:
        market_wins = any(item.admitted for item in portfolio.route_assessments)
        current_intent, current_interval_ends_at = self.current_decision(
            snapshot=snapshot,
            native_observation=portfolio.native_observation,
            assessments=portfolio.route_assessments,
        )
        return MarketDailyPlan(
            planner_id="mep",
            planner_name="Markt Etmaal Planner",
            snapshot_id=snapshot.snapshot_id,
            native_observation=portfolio.native_observation,
            market_routes=portfolio.market_routes,
            route_assessments=portfolio.route_assessments,
            winning_source=("market_route" if market_wins else "mep_native_plan"),
            reason=(
                "profitable_complete_market_route"
                if market_wins
                else (
                    "market_recovery_outside_available_horizon"
                    if not portfolio.market_routes
                    and portfolio.recovery_outside_horizon
                    else "no_admitted_market_route"
                )
            ),
            dispatch_authority=dispatch_authority,
            current_intent=current_intent,
            current_interval_ends_at=current_interval_ends_at,
            method_version=METHOD_VERSION,
            round_trip_efficiency=portfolio.round_trip_efficiency,
            trading_margin_fraction=portfolio.trading_margin_fraction,
            wear_eur_per_export_kwh=portfolio.wear_eur_per_export_kwh,
            minimum_total_route_profit_eur=(
                portfolio.minimum_total_route_profit_eur
            ),
        )

    @staticmethod
    def select_native_candidate_id(
        native_observation: DailyReferenceStrategyObservation,
    ) -> str:
        candidates = native_observation.observer_result.candidate_set.candidates
        physically_admissible = tuple(
            item
            for item in candidates
            if item.complete_across_scenarios
            and item.reserve_respected_across_scenarios
            and item.target_reached_across_scenarios
        )
        pv_recoverable = any(
            DailyStorageIntent.GRID_REQUIREMENT not in item.intents_used
            for item in physically_admissible
        )
        admitted = tuple(
            item
            for item in physically_admissible
            if not (
                pv_recoverable
                and DailyStorageIntent.GRID_REQUIREMENT in item.intents_used
            )
        )
        if not admitted:
            baseline_schedule_id = (
                native_observation.strategy_space.schedules[0].schedule_id
            )
            return next(
                item.candidate_id
                for item in candidates
                if item.intent_schedule_id == baseline_schedule_id
            )
        priced = tuple(
            item
            for item in admitted
            if item.average_charge_window_price_eur_per_kwh is not None
        )
        return min(
            priced or admitted,
            key=lambda item: (
                item.average_charge_window_price_eur_per_kwh
                if item.average_charge_window_price_eur_per_kwh is not None
                else 0.0,
                item.candidate_id,
            ),
        ).candidate_id

    @staticmethod
    def evaluate_commitment(
        *,
        snapshot: PlanningInputSnapshot,
        incumbent: ActivePlanCommitment | None,
        challenger_financial_result_eur: float | None,
        required_by: datetime | None,
        switching_margin_eur: float,
    ) -> MarketDailyCommitmentDecision:
        if switching_margin_eur < 0.0:
            raise ValueError("plan switching margin must be non-negative")
        if incumbent is None:
            return MarketDailyCommitmentDecision(
                incumbent_retained=False,
                decisive_step=None,
                objective_difference_eur=None,
                switching_margin_eur=switching_margin_eur,
            )
        active_phase = incumbent.starts_at <= snapshot.captured_at
        objective_difference = (
            challenger_financial_result_eur
            - incumbent.worst_case_financial_result_eur
            if challenger_financial_result_eur is not None
            and incumbent.worst_case_financial_result_eur is not None
            else None
        )
        if (
            not active_phase
            and required_by is not None
            and incumbent.ends_at > required_by
        ):
            return MarketDailyCommitmentDecision(
                incumbent_retained=False,
                decisive_step="necessity:incumbent_misses_required_by",
                objective_difference_eur=objective_difference,
                switching_margin_eur=switching_margin_eur,
            )
        if (
            not active_phase
            and objective_difference is not None
            and objective_difference > switching_margin_eur
        ):
            return MarketDailyCommitmentDecision(
                incumbent_retained=False,
                decisive_step=(
                    "material_change:challenger_improves_total_objective"
                ),
                objective_difference_eur=objective_difference,
                switching_margin_eur=switching_margin_eur,
            )
        return MarketDailyCommitmentDecision(
            incumbent_retained=True,
            decisive_step="stability:canonical_plan_commitment_retained",
            objective_difference_eur=objective_difference,
            switching_margin_eur=switching_margin_eur,
        )
    @staticmethod
    def current_decision(
        *,
        snapshot: PlanningInputSnapshot,
        native_observation: DailyReferenceStrategyObservation,
        assessments: tuple[MarketRouteAssessment, ...],
    ) -> tuple[DailyStorageIntent | None, datetime | None]:
        schedules: tuple[DailyReferenceIntentSchedule, ...]
        winner = MarketDailyEvaluationEngine.select_market_assessment(assessments)
        if winner is not None:
            schedules = (winner.intent_schedule,)
        else:
            candidates = {
                item.candidate_id: item
                for item in native_observation.observer_result.candidate_set.candidates
            }
            results = {
                item.intent_schedule.schedule_id: item.intent_schedule
                for item in native_observation.observer_result.portfolio.strategy_results
            }
            native_winner_id = MarketDailyEvaluationEngine.select_native_candidate_id(
                native_observation
            )
            schedules = (
                (results[candidates[native_winner_id].intent_schedule_id],)
            )
        due = tuple(
            next(
                (
                    interval
                    for interval in schedule.intervals
                    if interval.starts_at
                    <= snapshot.captured_at
                    < interval.ends_at
                ),
                None,
            )
            for schedule in schedules
        )
        if not due or any(item is None for item in due):
            return None, None
        decisions = {(item.intent, item.ends_at) for item in due if item is not None}
        if len(decisions) != 1:
            return None, None
        return next(iter(decisions))
