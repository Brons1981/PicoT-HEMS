"""Join grid admission and finance without entering canonical Evaluation."""

from __future__ import annotations

from picot.v2.contracts import (
    GridRequirementAdmissionSet,
    GridRequirementObserverDecision,
    GridRequirementObserverDecisionCandidate,
    ReferenceFinancialComparisonSet,
)

METHOD_VERSION = "v2-grid-requirement-observer-decision:v1"


class GridRequirementObserverDecisionProducer:
    """Produce a passive future-Evaluation recommendation."""

    def decide(
        self,
        *,
        admission: GridRequirementAdmissionSet,
        financial: ReferenceFinancialComparisonSet,
    ) -> GridRequirementObserverDecision:
        if admission.status == "not_applicable":
            return self._empty(admission.candidate_set_id, "not_applicable", ())
        if financial.status != "ready":
            return self._empty(
                admission.candidate_set_id,
                "blocked",
                financial.blockers or ("financial_comparison_unavailable",),
            )
        finance = {
            item.candidate_id: item
            for item in financial.comparisons
            if item.candidate_family == "grid_requirement"
        }
        admission_ids = tuple(item.candidate_id for item in admission.assessments)
        if set(admission_ids) != set(finance):
            return self._empty(
                admission.candidate_set_id,
                "blocked",
                ("grid_admission_financial_lineage_mismatch",),
            )
        candidates = tuple(
            GridRequirementObserverDecisionCandidate(
                candidate_id=item.candidate_id,
                energy_path_id=item.energy_path_id,
                physically_admissible=item.status == "admissible",
                net_financial_result_eur=finance[item.candidate_id].net_financial_result_eur,
                difference_from_baseline_eur=(
                    finance[item.candidate_id].difference_from_baseline_eur
                ),
                relative_to_baseline=finance[item.candidate_id].relative_to_baseline,
                admission_blockers=item.blockers,
                eligible_for_future_evaluation=item.status == "admissible",
            )
            for item in admission.assessments
        )
        eligible = tuple(item for item in candidates if item.eligible_for_future_evaluation)
        preferred = None
        if eligible:
            best = max(item.net_financial_result_eur for item in eligible)
            best_ids = tuple(
                item.candidate_id
                for item in eligible
                if item.net_financial_result_eur == best
            )
            preferred = best_ids[0] if len(best_ids) == 1 else None
        return GridRequirementObserverDecision(
            candidate_set_id=admission.candidate_set_id,
            status="ready",
            candidates=candidates,
            preferred_for_future_evaluation_candidate_id=preferred,
            blockers=(),
            observer_only=True,
            influences_live_selection=False,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _empty(
        candidate_set_id: str,
        status: str,
        blockers: tuple[str, ...],
    ) -> GridRequirementObserverDecision:
        return GridRequirementObserverDecision(
            candidate_set_id=candidate_set_id,
            status=status,
            candidates=(),
            preferred_for_future_evaluation_candidate_id=None,
            blockers=blockers,
            observer_only=True,
            influences_live_selection=False,
            method_version=METHOD_VERSION,
        )
