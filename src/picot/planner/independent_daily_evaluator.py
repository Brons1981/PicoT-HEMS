"""Evaluate independent daily candidates without affecting the live planner."""

from __future__ import annotations

from picot.domain.daily_reference_candidate import (
    DailyReferenceCandidate,
    DailyReferencePortfolioCandidateSet,
)
from picot.domain.daily_reference_evaluation import (
    DailyReferenceEvaluation,
    DailyReferenceEvaluationDirection,
    DailyReferenceEvaluationRecord,
    DailyReferenceExclusionReason,
)

METHOD_VERSION = "independent-daily-evaluator:v1"
OBJECTIVE = "maximize_worst_case_net_financial_result_eur"


class IndependentDailyEvaluator:
    """Apply hard physical gates, then compare worst-case financial outcomes."""

    def evaluate(
        self,
        candidate_set: DailyReferencePortfolioCandidateSet,
    ) -> DailyReferenceEvaluation:
        reasons_by_candidate = {
            candidate.candidate_id: self._exclusion_reasons(candidate)
            for candidate in candidate_set.candidates
        }
        admitted = tuple(
            candidate
            for candidate in candidate_set.candidates
            if not reasons_by_candidate[candidate.candidate_id]
        )
        best_result = (
            max(item.worst_case_financial_result_eur for item in admitted)
            if admitted
            else None
        )
        records = tuple(
            DailyReferenceEvaluationRecord(
                candidate_id=candidate.candidate_id,
                family=candidate.family,
                intent_schedule_id=candidate.intent_schedule_id,
                admissible=not reasons_by_candidate[candidate.candidate_id],
                exclusion_reasons=reasons_by_candidate[candidate.candidate_id],
                worst_case_financial_result_eur=(
                    candidate.worst_case_financial_result_eur
                ),
                minimum_confidence=candidate.minimum_confidence,
                best_observation=(
                    best_result is not None
                    and not reasons_by_candidate[candidate.candidate_id]
                    and candidate.worst_case_financial_result_eur == best_result
                ),
            )
            for candidate in candidate_set.candidates
        )
        return DailyReferenceEvaluation(
            evaluation_id=f"daily-evaluation:{candidate_set.candidate_set_id}",
            source_candidate_set_id=candidate_set.candidate_set_id,
            snapshot_id=candidate_set.snapshot_id,
            records=records,
            best_candidate_ids=tuple(
                item.candidate_id for item in records if item.best_observation
            ),
            objective=OBJECTIVE,
            direction=DailyReferenceEvaluationDirection.HIGHER_IS_BETTER,
            observer_only=True,
            selection_permitted=False,
            commitment_permitted=False,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _exclusion_reasons(
        candidate: DailyReferenceCandidate,
    ) -> tuple[DailyReferenceExclusionReason, ...]:
        reasons: list[DailyReferenceExclusionReason] = []
        if not candidate.complete_across_scenarios:
            reasons.append(DailyReferenceExclusionReason.PHYSICAL_PATH_INCOMPLETE)
        if not candidate.reserve_respected_across_scenarios:
            reasons.append(DailyReferenceExclusionReason.RESERVE_NOT_RESPECTED)
        if not candidate.target_held_across_scenarios:
            reasons.append(DailyReferenceExclusionReason.TARGET_NOT_HELD)
        return tuple(reasons)
