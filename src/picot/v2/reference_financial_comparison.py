"""Observer-only financial comparison over canonical V2ADR-054 settlements."""

from __future__ import annotations

from math import isfinite

from picot.v2.contracts import (
    Candidate,
    CandidateSet,
    ReferenceCandidateSimulation,
    ReferenceFinancialCandidateComparison,
    ReferenceFinancialComparisonSet,
)

METHOD_VERSION = "v2-reference-financial-comparison:v1"


class ReferenceFinancialComparator:
    """Compare settled Candidates without changing canonical Evaluation."""

    def compare(
        self,
        *,
        candidate_set: CandidateSet,
        observations: tuple[ReferenceCandidateSimulation, ...],
    ) -> ReferenceFinancialComparisonSet:
        candidate_ids = tuple(item.candidate_id for item in candidate_set.candidates)
        observation_ids = tuple(item.candidate_id for item in observations)
        if observation_ids != candidate_ids:
            return self._blocked(
                candidate_set.candidate_set_id,
                ("reference_candidate_lineage_incomplete",),
            )
        candidates = {item.candidate_id: item for item in candidate_set.candidates}
        paths = {item.path_id: item for item in candidate_set.energy_paths}
        baseline_ids = tuple(
            candidate.candidate_id
            for candidate in candidate_set.candidates
            if all(
                segment.charge_source_policy is None
                for segment in paths[candidate.energy_path_id].segments
            )
        )
        if len(baseline_ids) != 1:
            blocker = (
                "financial_baseline_missing"
                if not baseline_ids
                else "financial_baseline_ambiguous"
            )
            return self._blocked(
                candidate_set.candidate_set_id,
                (blocker,),
            )
        unavailable_ids = tuple(
            item.candidate_id
            for item in observations
            if item.status != "ready"
            or item.ledger is None
            or item.financial_settlement is None
            or item.ledger.candidate_id != item.candidate_id
            or item.ledger.energy_path_id != item.energy_path_id
            or item.financial_settlement.ledger_id != item.ledger.ledger_id
        )
        if unavailable_ids:
            return self._blocked(
                candidate_set.candidate_set_id,
                tuple(f"financial_settlement_unavailable:{item}" for item in unavailable_ids),
            )
        if any(
            not isfinite(item.financial_settlement.net_financial_result_eur)
            for item in observations
            if item.financial_settlement is not None
        ):
            return self._blocked(
                candidate_set.candidate_set_id,
                ("financial_result_not_finite",),
            )

        baseline_id = baseline_ids[0]
        baseline_observation = next(
            item for item in observations if item.candidate_id == baseline_id
        )
        assert baseline_observation.financial_settlement is not None
        baseline_result = baseline_observation.financial_settlement.net_financial_result_eur
        results = {
            item.candidate_id: item.financial_settlement.net_financial_result_eur
            for item in observations
            if item.financial_settlement is not None
        }
        best_result = max(results.values())
        best_candidate_ids = tuple(
            candidate_id
            for candidate_id in candidate_ids
            if results[candidate_id] == best_result
        )
        comparisons = tuple(
            self._candidate_comparison(
                candidate=candidates[item.candidate_id],
                observation=item,
                baseline_result=baseline_result,
            )
            for item in observations
        )
        return ReferenceFinancialComparisonSet(
            status="ready",
            candidate_set_id=candidate_set.candidate_set_id,
            baseline_candidate_id=baseline_id,
            comparisons=comparisons,
            best_candidate_ids=best_candidate_ids,
            financially_preferred_candidate_id=(
                best_candidate_ids[0] if len(best_candidate_ids) == 1 else None
            ),
            direction="higher_is_better",
            unit="EUR",
            comparison_scope="financial_result_only",
            hard_constraints_assessed=False,
            observer_only=True,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _candidate_comparison(
        *,
        candidate: Candidate,
        observation: ReferenceCandidateSimulation,
        baseline_result: float,
    ) -> ReferenceFinancialCandidateComparison:
        assert observation.financial_settlement is not None
        result = observation.financial_settlement.net_financial_result_eur
        difference = result - baseline_result
        relation = "better" if difference > 0.0 else "worse" if difference < 0.0 else "equal"
        return ReferenceFinancialCandidateComparison(
            candidate_id=candidate.candidate_id,
            energy_path_id=observation.energy_path_id,
            candidate_family=candidate.family,
            settlement_id=observation.financial_settlement.settlement_id,
            net_financial_result_eur=result,
            difference_from_baseline_eur=difference,
            relative_to_baseline=relation,
            confidence=observation.financial_settlement.confidence,
            evidence_ids=observation.financial_settlement.evidence_ids,
        )

    @staticmethod
    def _blocked(
        candidate_set_id: str,
        blockers: tuple[str, ...],
    ) -> ReferenceFinancialComparisonSet:
        return ReferenceFinancialComparisonSet(
            status="blocked",
            candidate_set_id=candidate_set_id,
            baseline_candidate_id=None,
            comparisons=(),
            best_candidate_ids=(),
            financially_preferred_candidate_id=None,
            direction="higher_is_better",
            unit="EUR",
            comparison_scope="financial_result_only",
            hard_constraints_assessed=False,
            observer_only=True,
            method_version=METHOD_VERSION,
            blockers=blockers,
        )
