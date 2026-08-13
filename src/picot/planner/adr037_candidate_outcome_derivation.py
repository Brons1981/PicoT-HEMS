"""Derive deterministic ADR-037 Candidate Outcomes without hidden scoring."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import EnergyPath
from picot.domain.evaluation import (
    CandidateOutcome,
    CandidateOutcomeSet,
    CandidateValidity,
    ComparisonDirection,
    ObjectiveOutcome,
)
from picot.domain.objectives import ObjectiveKind
from picot.domain.pv_only_storage_feasibility import PVOnlyStorageEnergyFeasibility
from picot.domain.storage_technical_recoverability import StorageTechnicalRecoverability
from picot.planner.evaluation_engine import EvaluationEngine


@dataclass(frozen=True, slots=True)
class ADR037CandidateOutcomeDeriver:
    """Produce Evaluation inputs only from comparable simulated path facts.

    Physical self-consumption and net-balance outcomes are derived when every
    projected interval supplies the required dimensions. Financial result stays
    unavailable until canonical import/export settlement evidence is present;
    this producer never assumes that one price series applies symmetrically.
    """

    complexity_version: str = "path-complexity-v1"

    def derive(
        self,
        *,
        candidate_set: CandidateSet,
        pv_only_feasibility: PVOnlyStorageEnergyFeasibility | None = None,
        storage_recoverability: StorageTechnicalRecoverability | None = None,
    ) -> CandidateOutcomeSet:
        paths_by_id = {path.path_id: path for path in candidate_set.energy_paths}
        outcomes = tuple(
            self._outcome_for(
                candidate=candidate,
                path=paths_by_id[candidate.energy_path_id],
                pv_only_feasibility=pv_only_feasibility,
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
        pv_only_feasibility: PVOnlyStorageEnergyFeasibility | None,
        storage_recoverability: StorageTechnicalRecoverability | None,
    ) -> CandidateOutcome:
        grid_supported = self._is_grid_supported(path)
        recoverability = self._recoverability_for(
            candidate=candidate,
            path=path,
            storage_recoverability=storage_recoverability,
        )
        validity = CandidateValidity.VALID
        invalidity_reasons: tuple[str, ...] = ()
        if (
            pv_only_feasibility is not None
            and not pv_only_feasibility.energy_sufficient
            and not grid_supported
        ):
            validity = CandidateValidity.INVALID
            invalidity_reasons = (
                "PV-only path cannot meet the StorageEnergyRequirement before its deadline.",
            )

        recoverability_evidence_ids: tuple[str, ...] = ()
        if recoverability is not None:
            if storage_recoverability is None:
                raise ValueError(
                    "Recoverability outcome requires technical recoverability evidence."
                )
            recoverability_evidence_ids = storage_recoverability.evidence_ids
        feasibility_evidence_ids = (
            pv_only_feasibility.evidence_ids if pv_only_feasibility is not None else ()
        )
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    candidate.candidate_id,
                    path.path_id,
                    *feasibility_evidence_ids,
                    *recoverability_evidence_ids,
                )
            )
        )
        return CandidateOutcome(
            candidate_id=candidate.candidate_id,
            objective_outcomes=self._physical_objectives(path),
            confidence=candidate.confidence,
            recoverability=recoverability,
            execution_complexity=self._execution_complexity(path),
            expected_switching_count=None,
            complexity_version=self.complexity_version,
            validity=validity,
            invalidity_reasons=invalidity_reasons,
            evidence_ids=evidence_ids,
        )

    @staticmethod
    def _physical_objectives(path: EnergyPath) -> tuple[ObjectiveOutcome, ...]:
        if not path.projected_states:
            return ()
        previous = path.horizon_start
        self_consumed_wh = 0.0
        net_exchange_wh = 0.0
        confidences: list[float] = []
        for state in path.projected_states:
            if (
                state.pv_production_w is None
                or state.household_import_w is None
                or state.household_export_w is None
            ):
                return ()
            duration_h = (state.at - previous).total_seconds() / 3600.0
            if duration_h <= 0.0:
                return ()
            self_consumed_wh += max(
                0.0,
                state.pv_production_w - state.household_export_w,
            ) * duration_h
            net_exchange_wh += (
                state.household_import_w + state.household_export_w
            ) * duration_h
            confidences.append(state.confidence)
            previous = state.at
        confidence = min(confidences)
        evidence_ids = (path.path_id,)
        return (
            ObjectiveOutcome(
                objective=ObjectiveKind.SELF_CONSUMPTION,
                value=self_consumed_wh,
                direction=ComparisonDirection.HIGHER_IS_BETTER,
                unit="Wh",
                confidence=confidence,
                evidence_ids=evidence_ids,
            ),
            ObjectiveOutcome(
                objective=ObjectiveKind.NET_BALANCE,
                value=net_exchange_wh,
                direction=ComparisonDirection.LOWER_IS_BETTER,
                unit="Wh",
                confidence=confidence,
                evidence_ids=evidence_ids,
            ),
        )

    @staticmethod
    def _is_grid_supported(path: EnergyPath) -> bool:
        return any(
            segment.charge_source_policy
            is ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED
            for segment in path.segments
        )

    @classmethod
    def _recoverability_for(
        cls,
        *,
        candidate: Candidate,
        path: EnergyPath,
        storage_recoverability: StorageTechnicalRecoverability | None,
    ) -> float | None:
        if not cls._is_grid_supported(path):
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
