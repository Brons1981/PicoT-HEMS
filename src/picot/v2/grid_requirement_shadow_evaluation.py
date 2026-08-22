"""Observer-only shadow Evaluation for admitted grid-requirement Candidates."""

from __future__ import annotations

from picot.v2.contracts import (
    CandidateOutcomeSet,
    CandidateSet,
    EvaluationRecord,
    GridRequirementObserverDecision,
    GridRequirementShadowCandidateEvaluation,
    GridRequirementShadowEvaluation,
    ReferenceFinancialComparisonSet,
)

METHOD_VERSION = "v2-grid-requirement-shadow-evaluation:v1"
OBJECTIVE_ORDER = (
    "hard_constraint:storage_requirement_satisfied",
    "objective:financial_result:higher_is_better",
)


class GridRequirementShadowEvaluationProducer:
    """Project a winner without entering canonical Evaluation."""

    def evaluate(
        self,
        *,
        candidate_set: CandidateSet,
        outcomes: CandidateOutcomeSet,
        financial: ReferenceFinancialComparisonSet,
        decision: GridRequirementObserverDecision,
        actual_evaluation: EvaluationRecord,
    ) -> GridRequirementShadowEvaluation:
        if decision.status == "not_applicable":
            return self._empty(candidate_set.candidate_set_id, "not_applicable", actual_evaluation)
        if decision.status != "ready" or financial.status != "ready":
            return self._empty(
                candidate_set.candidate_set_id,
                "blocked",
                actual_evaluation,
                decision.blockers or financial.blockers or ("shadow_inputs_unavailable",),
            )
        actual_id = actual_evaluation.winning_candidate_id
        candidate_by_id = {item.candidate_id: item for item in candidate_set.candidates}
        finance_by_id = {item.candidate_id: item for item in financial.comparisons}
        outcome_by_id = {item.candidate_id: item for item in outcomes.outcomes}
        if actual_id is None or actual_id not in candidate_by_id or actual_id not in finance_by_id:
            return self._empty(
                candidate_set.candidate_set_id,
                "blocked",
                actual_evaluation,
                ("actual_winner_financial_lineage_missing",),
            )

        actual_candidate = candidate_by_id[actual_id]
        actual_finance = finance_by_id[actual_id]
        actual_outcome = outcome_by_id.get(actual_id)
        evaluated = [
            GridRequirementShadowCandidateEvaluation(
                candidate_id=actual_id,
                energy_path_id=actual_candidate.energy_path_id,
                candidate_family=actual_candidate.family,
                validity="valid",
                requirement_satisfied=(
                    actual_outcome.requirement_satisfied if actual_outcome is not None else False
                ),
                net_financial_result_eur=actual_finance.net_financial_result_eur,
                relative_to_baseline=actual_finance.relative_to_baseline,
                physical_admission="current_winner",
            )
        ]
        for item in decision.candidates:
            candidate = candidate_by_id.get(item.candidate_id)
            comparison = finance_by_id.get(item.candidate_id)
            outcome = outcome_by_id.get(item.candidate_id)
            exclusions: list[str] = []
            if candidate is None or comparison is None or outcome is None:
                exclusions.append("shadow_candidate_lineage_incomplete")
            elif (
                candidate.energy_path_id != item.energy_path_id
                or comparison.energy_path_id != item.energy_path_id
                or outcome.energy_path_id != item.energy_path_id
            ):
                exclusions.append("shadow_candidate_lineage_mismatch")
            if not item.eligible_for_future_evaluation:
                exclusions.extend(item.admission_blockers or ("grid_candidate_not_admitted",))
            evaluated.append(
                GridRequirementShadowCandidateEvaluation(
                    candidate_id=item.candidate_id,
                    energy_path_id=item.energy_path_id,
                    candidate_family="grid_requirement",
                    validity="excluded" if exclusions else "valid",
                    requirement_satisfied=(outcome.requirement_satisfied if outcome else False),
                    net_financial_result_eur=(
                        comparison.net_financial_result_eur
                        if comparison
                        else item.net_financial_result_eur
                    ),
                    relative_to_baseline=(
                        comparison.relative_to_baseline if comparison else item.relative_to_baseline
                    ),
                    physical_admission=("admissible" if item.physically_admissible else "blocked"),
                    exclusion_reasons=tuple(dict.fromkeys(exclusions)),
                )
            )

        valid = tuple(item for item in evaluated if item.validity == "valid")
        if not valid:
            return self._result(
                "blocked",
                actual_evaluation,
                tuple(evaluated),
                blockers=("no_valid_shadow_candidates",),
            )
        best_requirement = max(item.requirement_satisfied for item in valid)
        requirement_best = tuple(
            item for item in valid if item.requirement_satisfied == best_requirement
        )
        best_finance = max(item.net_financial_result_eur for item in requirement_best)
        best = tuple(
            item
            for item in requirement_best
            if item.net_financial_result_eur == best_finance
        )
        if len(best) != 1:
            return self._result("tie", actual_evaluation, tuple(evaluated), decisive_step=None)
        winner = best[0]
        decisive_step = (
            OBJECTIVE_ORDER[0]
            if any(item.requirement_satisfied != winner.requirement_satisfied for item in valid)
            else OBJECTIVE_ORDER[1]
        )
        return self._result(
            "winner_projected",
            actual_evaluation,
            tuple(evaluated),
            projected_winner=winner.candidate_id,
            decisive_step=decisive_step,
        )

    @staticmethod
    def _empty(
        candidate_set_id: str,
        status: str,
        actual: EvaluationRecord,
        blockers: tuple[str, ...] = (),
    ) -> GridRequirementShadowEvaluation:
        return GridRequirementShadowEvaluation(
            status=status,
            candidate_set_id=candidate_set_id,
            actual_winning_candidate_id=actual.winning_candidate_id,
            projected_winning_candidate_id=None,
            candidates=(),
            objective_order=OBJECTIVE_ORDER,
            decisive_step=None,
            differs_from_actual_winner=False,
            blockers=blockers,
            observer_only=True,
            influences_live_selection=False,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _result(
        status: str,
        actual: EvaluationRecord,
        candidates: tuple[GridRequirementShadowCandidateEvaluation, ...],
        *,
        projected_winner: str | None = None,
        decisive_step: str | None = None,
        blockers: tuple[str, ...] = (),
    ) -> GridRequirementShadowEvaluation:
        return GridRequirementShadowEvaluation(
            status=status,
            candidate_set_id=actual.candidate_set_id,
            actual_winning_candidate_id=actual.winning_candidate_id,
            projected_winning_candidate_id=projected_winner,
            candidates=candidates,
            objective_order=OBJECTIVE_ORDER,
            decisive_step=decisive_step,
            differs_from_actual_winner=(
                projected_winner is not None and projected_winner != actual.winning_candidate_id
            ),
            blockers=blockers,
            observer_only=True,
            influences_live_selection=False,
            method_version=METHOD_VERSION,
        )
