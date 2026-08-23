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
from picot.domain.daily_reference_intent import DailyStorageIntent

METHOD_VERSION = "independent-daily-evaluator:v3"
OBJECTIVE = "pv_preferred_then_minimize_average_charge_window_price_eur_per_kwh"


class IndependentDailyEvaluator:
    """Apply PV-first physical gates, then compare average window prices."""

    def evaluate(
        self,
        candidate_set: DailyReferencePortfolioCandidateSet,
    ) -> DailyReferenceEvaluation:
        physical_reasons_by_candidate = {
            candidate.candidate_id: self._exclusion_reasons(candidate)
            for candidate in candidate_set.candidates
        }
        pv_recoverable = any(
            DailyStorageIntent.GRID_REQUIREMENT not in candidate.intents_used
            and not physical_reasons_by_candidate[candidate.candidate_id]
            for candidate in candidate_set.candidates
        )
        reasons_by_candidate = {
            candidate.candidate_id: (
                *physical_reasons_by_candidate[candidate.candidate_id],
                *(
                    (
                        DailyReferenceExclusionReason.GRID_NOT_REQUIRED_PV_RECOVERABLE,
                    )
                    if pv_recoverable
                    and DailyStorageIntent.GRID_REQUIREMENT in candidate.intents_used
                    else ()
                ),
            )
            for candidate in candidate_set.candidates
        }
        admitted = tuple(
            candidate
            for candidate in candidate_set.candidates
            if not reasons_by_candidate[candidate.candidate_id]
        )
        priced = tuple(
            item
            for item in admitted
            if item.average_charge_window_price_eur_per_kwh is not None
        )
        best_price = (
            min(
                item.average_charge_window_price_eur_per_kwh
                for item in priced
                if item.average_charge_window_price_eur_per_kwh is not None
            )
            if priced
            else None
        )
        best_unpriced_ids = (
            {item.candidate_id for item in admitted} if admitted and not priced else set()
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
                average_charge_window_price_eur_per_kwh=(
                    candidate.average_charge_window_price_eur_per_kwh
                ),
                charge_window_confidence=candidate.charge_window_confidence,
                best_observation=(
                    not reasons_by_candidate[candidate.candidate_id]
                    and (
                        candidate.candidate_id in best_unpriced_ids
                        or (
                            best_price is not None
                            and candidate.average_charge_window_price_eur_per_kwh
                            == best_price
                        )
                    )
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
            direction=DailyReferenceEvaluationDirection.LOWER_IS_BETTER,
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
        if not candidate.target_reached_across_scenarios:
            reasons.append(DailyReferenceExclusionReason.TARGET_NOT_REACHED)
        return tuple(reasons)
