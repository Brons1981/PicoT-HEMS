from picot.v2.contracts import (
    GridRequirementAdmissionCondition,
    GridRequirementAdmissionSet,
    GridRequirementCandidateAdmission,
    ReferenceFinancialCandidateComparison,
    ReferenceFinancialComparisonSet,
)
from picot.v2.grid_requirement_observer_decision import (
    GridRequirementObserverDecisionProducer,
)


def _admission(candidate_id: str, *, admissible: bool) -> GridRequirementCandidateAdmission:
    blocker = None if admissible else "connection_limit_missing_or_exceeded"
    return GridRequirementCandidateAdmission(
        candidate_id=candidate_id,
        energy_path_id=f"path:{candidate_id}",
        storage_requirement_id="requirement:1",
        status="admissible" if admissible else "blocked",
        conditions=(
            GridRequirementAdmissionCondition(
                condition="connection_limit_respected",
                satisfied=admissible,
                evidence_ids=("grid-limit:1",) if admissible else (),
                blocker=blocker,
            ),
        ),
        blockers=() if admissible else (blocker,),
        observer_only=True,
        method_version="test:v1",
    )


def _finance(candidate_id: str, result: float) -> ReferenceFinancialCandidateComparison:
    return ReferenceFinancialCandidateComparison(
        candidate_id=candidate_id,
        energy_path_id=f"path:{candidate_id}",
        candidate_family="grid_requirement",
        settlement_id=f"settlement:{candidate_id}",
        net_financial_result_eur=result,
        difference_from_baseline_eur=result,
        relative_to_baseline="better" if result > 0.0 else "equal",
        confidence=1.0,
        evidence_ids=(f"settlement:{candidate_id}",),
    )


def test_equal_admissible_results_keep_no_hidden_preference() -> None:
    admission = GridRequirementAdmissionSet(
        candidate_set_id="candidate-set:1",
        status="ready",
        assessments=(_admission("grid:a", admissible=True), _admission("grid:b", admissible=True)),
        observer_only=True,
        influences_live_selection=False,
        method_version="test:v1",
    )
    financial = ReferenceFinancialComparisonSet(
        status="ready",
        candidate_set_id="candidate-set:1",
        baseline_candidate_id="baseline",
        comparisons=(
            ReferenceFinancialCandidateComparison(
                candidate_id="baseline",
                energy_path_id="path:baseline",
                candidate_family="reserve_first",
                settlement_id="settlement:baseline",
                net_financial_result_eur=0.0,
                difference_from_baseline_eur=0.0,
                relative_to_baseline="equal",
                confidence=1.0,
                evidence_ids=("settlement:baseline",),
            ),
            _finance("grid:a", 0.20),
            _finance("grid:b", 0.20),
        ),
        best_candidate_ids=("grid:a", "grid:b"),
        financially_preferred_candidate_id=None,
        direction="higher_is_better",
        unit="EUR",
        comparison_scope="financial_result_only",
        hard_constraints_assessed=False,
        observer_only=True,
        method_version="test:v1",
    )

    decision = GridRequirementObserverDecisionProducer().decide(
        admission=admission,
        financial=financial,
    )

    assert decision.status == "ready"
    assert decision.preferred_for_future_evaluation_candidate_id is None
    assert all(item.eligible_for_future_evaluation for item in decision.candidates)


def test_financially_attractive_but_blocked_candidate_stays_ineligible() -> None:
    admission = GridRequirementAdmissionSet(
        candidate_set_id="candidate-set:1",
        status="ready",
        assessments=(_admission("grid:a", admissible=False),),
        observer_only=True,
        influences_live_selection=False,
        method_version="test:v1",
    )
    financial = ReferenceFinancialComparisonSet(
        status="ready",
        candidate_set_id="candidate-set:1",
        baseline_candidate_id="baseline",
        comparisons=(
            ReferenceFinancialCandidateComparison(
                candidate_id="baseline",
                energy_path_id="path:baseline",
                candidate_family="reserve_first",
                settlement_id="settlement:baseline",
                net_financial_result_eur=0.0,
                difference_from_baseline_eur=0.0,
                relative_to_baseline="equal",
                confidence=1.0,
                evidence_ids=("settlement:baseline",),
            ),
            _finance("grid:a", 1.00),
        ),
        best_candidate_ids=("grid:a",),
        financially_preferred_candidate_id="grid:a",
        direction="higher_is_better",
        unit="EUR",
        comparison_scope="financial_result_only",
        hard_constraints_assessed=False,
        observer_only=True,
        method_version="test:v1",
    )

    decision = GridRequirementObserverDecisionProducer().decide(
        admission=admission,
        financial=financial,
    )

    assert decision.candidates[0].eligible_for_future_evaluation is False
    assert decision.preferred_for_future_evaluation_candidate_id is None
    assert decision.candidates[0].admission_blockers == (
        "connection_limit_missing_or_exceeded",
    )
