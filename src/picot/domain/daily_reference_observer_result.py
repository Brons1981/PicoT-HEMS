"""Closed observer-only result for the independent daily planning chain."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.daily_reference_candidate import (
    DailyReferencePortfolioCandidateSet,
)
from picot.domain.daily_reference_evaluation import DailyReferenceEvaluation
from picot.domain.daily_reference_portfolio import DailyReferencePortfolio


@dataclass(frozen=True, slots=True)
class DailyReferenceObserverResult:
    """Portfolio, candidates and evaluation tied to one immutable snapshot."""

    result_id: str
    snapshot_id: str
    portfolio: DailyReferencePortfolio
    candidate_set: DailyReferencePortfolioCandidateSet
    evaluation: DailyReferenceEvaluation
    best_observation_ids: tuple[str, ...]
    observer_only: bool
    selection_permitted: bool
    commitment_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.result_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily observer result identity must be explicit.")
        if not self.method_version.strip():
            raise ValueError("Daily observer result method version must be explicit.")
        if self.portfolio.snapshot_id != self.snapshot_id:
            raise ValueError("Daily observer portfolio snapshot must match.")
        if self.candidate_set.snapshot_id != self.snapshot_id:
            raise ValueError("Daily observer candidate snapshot must match.")
        if self.evaluation.snapshot_id != self.snapshot_id:
            raise ValueError("Daily observer evaluation snapshot must match.")
        if self.candidate_set.source_portfolio_id != self.portfolio.portfolio_id:
            raise ValueError("Daily observer candidate lineage must match portfolio.")
        if (
            self.evaluation.source_candidate_set_id
            != self.candidate_set.candidate_set_id
        ):
            raise ValueError("Daily observer evaluation lineage must match candidates.")
        candidate_ids = tuple(
            item.candidate_id for item in self.candidate_set.candidates
        )
        record_ids = tuple(item.candidate_id for item in self.evaluation.records)
        if candidate_ids != record_ids:
            raise ValueError(
                "Daily observer candidate and evaluation records must match."
            )
        if self.best_observation_ids != self.evaluation.best_candidate_ids:
            raise ValueError("Daily observer best observations must reconcile.")
        if not self.observer_only or self.selection_permitted:
            raise ValueError("Daily observer result must remain observer-only.")
        if self.commitment_permitted:
            raise ValueError("Daily observer result must not permit commitment.")
