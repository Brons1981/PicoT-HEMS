"""Derive deterministic ADR-037 Candidate Outcomes without hidden objective scores."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import EnergyPath
from picot.domain.evaluation import CandidateOutcome, CandidateOutcomeSet, CandidateValidity
from picot.domain.storage_technical_recoverability import StorageTechnicalRecoverability
from picot.planner.evaluation_engine import EvaluationEngine


@dataclass(frozen=True, slots=True)
class ADR037CandidateOutcomeDeriver:
    """Produce Evaluation inputs from facts already present in ADR-037 paths.

    This producer deliberately does not invent financial, self-consumption,
    net-balance or grid-import values. Those objective outcomes require a
    projected Energy Path with comparable physical quantities for every
    Candidate. Until that projection exists, Evaluation records those objectives
    as unavailable according to ADR-032.
    """

    complexity_version: str = "path-complexity-v1"

    def derive(
        self,
        *,
        candidate_set: CandidateSet,
        storage_recoverability: StorageTechnicalRecoverability | None = None,
    ) -> CandidateOutcomeSet:
        paths_by_id = {path.path_id: path for path in candidate_set.energy_paths}
        outcomes = tuple(
            self._outcome_for(
                candidate=candidate,
                path=paths_by_id[candidate.energy_path_id],
                storage_recoverability=storage_recoverability,
            )
            for candidate in candidate_set.candidates
        )
        return CandidateOutcomeSet(
            snapshot_id=candidate_set.snapshot_id,
            strategy_version=candidate_set.strategy_version,
            candidate_set_reference=EvaluationEngine.candidate_set_reference(candidate_set),
            outcomes=outcomes,
        )

    def _outcome_for(
        self,
        *,
        candidate: Candidate,
        path: EnergyPath,
        storage_recoverability: StorageTechnicalRecoverability | None,
    ) -> CandidateOutcome:
        recoverability = self._recoverability_for(
            candidate=candidate,
            path=path,
            storage_recoverability=storage_recoverability,
        )
        recoverability_evidence_ids: tuple[str, ...] = ()
        if recoverability is not None:
            if storage_recoverability is None:
                raise ValueError(
                    "Recoverability outcome requires technical recoverability evidence."
                )
            recoverability_evidence_ids = storage_recoverability.evidence_ids
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    candidate.candidate_id,
                    path.path_id,
                    *recoverability_evidence_ids,
                )
            )
        )
        return CandidateOutcome(
            candidate_id=candidate.candidate_id,
            objective_outcomes=(),
            confidence=candidate.confidence,
            recoverability=recoverability,
            execution_complexity=self._execution_complexity(path),
            expected_switching_count=None,
            complexity_version=self.complexity_version,
            validity=CandidateValidity.VALID,
            invalidity_reasons=(),
            evidence_ids=evidence_ids,
        )

    @staticmethod
    def _recoverability_for(
        *,
        candidate: Candidate,
        path: EnergyPath,
        storage_recoverability: StorageTechnicalRecoverability | None,
    ) -> float | None:
        grid_supported = any(
            segment.charge_source_policy
            is ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED
            for segment in path.segments
        )
        if not grid_supported:
            return None
        if candidate.family is not CandidateFamily.COST_FIRST:
            raise ValueError("Grid-supported ADR-037 paths must use COST_FIRST family.")
        if storage_recoverability is None:
            raise ValueError(
                "Grid-supported Candidate Outcomes require technical recoverability evidence."
            )
        if not storage_recoverability.technically_recoverable:
            raise ValueError(
                "Grid-supported Candidate cannot carry non-recoverable technical evidence."
            )
        if storage_recoverability.capability_id not in candidate.capability_ids:
            raise ValueError(
                "Technical recoverability capability must match the grid-supported Candidate."
            )
        return storage_recoverability.confidence

    @staticmethod
    def _execution_complexity(path: EnergyPath) -> int:
        """ADR-032 v1 complexity: segments + scopes + primitive transitions."""

        if not path.segments:
            return 0
        scopes = {segment.execution_scope_id for segment in path.segments}
        ordered = sorted(path.segments, key=lambda segment: (segment.order, segment.segment_id))
        transitions = sum(
            left.primitive is not right.primitive
            for left, right in zip(ordered, ordered[1:], strict=False)
        )
        return len(path.segments) + len(scopes) + transitions
