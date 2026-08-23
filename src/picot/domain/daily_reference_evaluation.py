"""Observer-only evaluation contracts for independent daily candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from picot.domain.daily_reference_candidate import DailyReferenceCandidateFamily


class DailyReferenceEvaluationDirection(StrEnum):
    """The only supported financial comparison direction."""

    HIGHER_IS_BETTER = "higher_is_better"


class DailyReferenceExclusionReason(StrEnum):
    """Explicit hard-gate failures that prevent financial comparison."""

    PHYSICAL_PATH_INCOMPLETE = "physical_path_incomplete"
    RESERVE_NOT_RESPECTED = "reserve_not_respected"
    TARGET_NOT_REACHED = "target_not_reached"
    GRID_NOT_REQUIRED_PV_RECOVERABLE = "grid_not_required_pv_recoverable"


@dataclass(frozen=True, slots=True)
class DailyReferenceEvaluationRecord:
    """One candidate's admissibility and observer-only financial outcome."""

    candidate_id: str
    family: DailyReferenceCandidateFamily
    intent_schedule_id: str
    admissible: bool
    exclusion_reasons: tuple[DailyReferenceExclusionReason, ...]
    worst_case_financial_result_eur: float
    minimum_confidence: float
    best_observation: bool

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.intent_schedule_id.strip():
            raise ValueError("Daily evaluation record identity must be explicit.")
        if self.admissible == bool(self.exclusion_reasons):
            raise ValueError("Daily evaluation admissibility must match its reasons.")
        if self.best_observation and not self.admissible:
            raise ValueError("An excluded candidate cannot be a best observation.")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("Daily evaluation confidence must be between 0.0 and 1.0.")


@dataclass(frozen=True, slots=True)
class DailyReferenceEvaluation:
    """Deterministic comparison that cannot select or commit a live plan."""

    evaluation_id: str
    source_candidate_set_id: str
    snapshot_id: str
    records: tuple[DailyReferenceEvaluationRecord, ...]
    best_candidate_ids: tuple[str, ...]
    objective: str
    direction: DailyReferenceEvaluationDirection
    observer_only: bool
    selection_permitted: bool
    commitment_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip() or not self.source_candidate_set_id.strip():
            raise ValueError("Daily evaluation identity must be explicit.")
        if not self.snapshot_id.strip() or not self.objective.strip():
            raise ValueError("Daily evaluation lineage and objective must be explicit.")
        if not self.method_version.strip() or not self.records:
            raise ValueError("Daily evaluation requires records and a method version.")
        record_ids = tuple(item.candidate_id for item in self.records)
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Daily evaluation candidates must be unique.")
        expected_best = tuple(
            item.candidate_id for item in self.records if item.best_observation
        )
        if self.best_candidate_ids != expected_best:
            raise ValueError("Daily evaluation best observations must reconcile.")
        if len(self.best_candidate_ids) != len(set(self.best_candidate_ids)):
            raise ValueError("Daily evaluation best observations must be unique.")
        if not self.observer_only or self.selection_permitted:
            raise ValueError(
                "Daily evaluation must remain observer-only and unselected."
            )
        if self.commitment_permitted:
            raise ValueError("Daily evaluation must not permit commitment.")
