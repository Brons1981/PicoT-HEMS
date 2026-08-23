"""Close the independent daily portfolio into one observer-only result."""

from __future__ import annotations

from picot.domain.daily_reference_observer_result import (
    DailyReferenceObserverResult,
)
from picot.domain.daily_reference_portfolio import DailyReferencePortfolio
from picot.planner.independent_daily_candidate_engine import (
    IndependentDailyCandidateEngine,
)
from picot.planner.independent_daily_evaluator import IndependentDailyEvaluator

METHOD_VERSION = "independent-daily-observer:v1"


class IndependentDailyObserver:
    """Run Candidate and Evaluation only on a proven independent portfolio."""

    def observe(
        self,
        portfolio: DailyReferencePortfolio,
    ) -> DailyReferenceObserverResult:
        candidate_set = IndependentDailyCandidateEngine().build_portfolio(portfolio)
        evaluation = IndependentDailyEvaluator().evaluate(candidate_set)
        return DailyReferenceObserverResult(
            result_id=f"daily-observer:{portfolio.portfolio_id}",
            snapshot_id=portfolio.snapshot_id,
            portfolio=portfolio,
            candidate_set=candidate_set,
            evaluation=evaluation,
            best_observation_ids=evaluation.best_candidate_ids,
            observer_only=True,
            selection_permitted=False,
            commitment_permitted=False,
            method_version=METHOD_VERSION,
        )
