"""End-to-end orchestration of the deterministic ADR-037 planning slice.

This module owns sequencing only. Every calculation remains owned by its
existing domain component; no requirement, feasibility, Candidate or Evaluation
logic is duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.candidate import CandidateSet
from picot.domain.capability_snapshot import CapabilitySnapshotSet, LogicalCapabilitySnapshot
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.evaluation import CandidateOutcomeSet, EvaluationResult
from picot.domain.evidence_confidence_policy import EvidenceConfidenceAssessment
from picot.domain.opportunity import OpportunitySet
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.projected_household_energy_balance import ProjectedHouseholdEnergyBalance
from picot.domain.pv_only_storage_feasibility import (
    PVOnlyStorageEnergyFeasibility,
    PVOnlyStorageEnergyFeasibilityEvaluator,
)
from picot.domain.storage_energy_requirement import StorageEnergyRequirement
from picot.domain.storage_requirement_derivation import StorageRequirementDeriver
from picot.domain.storage_technical_recoverability import (
    StorageTechnicalRecoverability,
    StorageTechnicalRecoverabilityEvaluator,
)
from picot.planner.adr037_candidate_outcome_derivation import ADR037CandidateOutcomeDeriver
from picot.planner.candidate_energy_path_simulator import CandidateEnergyPathSimulator
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.flow_aware_candidate_engine import FlowAwareCandidateEngine


@dataclass(frozen=True, slots=True)
class ADR037PlanningResult:
    """Traceable outputs of one complete ADR-037 planner pass."""

    requirement: StorageEnergyRequirement
    pv_only_feasibility: PVOnlyStorageEnergyFeasibility
    technical_recoverability: StorageTechnicalRecoverability
    candidate_set: CandidateSet
    candidate_outcomes: CandidateOutcomeSet
    evaluation: EvaluationResult


@dataclass(frozen=True, slots=True)
class ADR037PlannerPipeline:
    """Sequence the already-owned ADR-037 calculations exactly once."""

    requirement_deriver: StorageRequirementDeriver = StorageRequirementDeriver()
    pv_feasibility_evaluator: PVOnlyStorageEnergyFeasibilityEvaluator = (
        PVOnlyStorageEnergyFeasibilityEvaluator()
    )
    recoverability_evaluator: StorageTechnicalRecoverabilityEvaluator = (
        StorageTechnicalRecoverabilityEvaluator()
    )
    candidate_engine: FlowAwareCandidateEngine = FlowAwareCandidateEngine()
    simulator: CandidateEnergyPathSimulator = CandidateEnergyPathSimulator()
    outcome_deriver: ADR037CandidateOutcomeDeriver = ADR037CandidateOutcomeDeriver()
    evaluation_engine: EvaluationEngine = EvaluationEngine()

    def run(
        self,
        *,
        requirement_id: str,
        evaluated_at: datetime,
        snapshot: PlanningInputSnapshot,
        balance: ProjectedHouseholdEnergyBalance,
        effective_limit: EffectiveStorageLimit,
        confidence_assessment: EvidenceConfidenceAssessment,
        storage_state: CurrentStorageState,
        storage_capability: LogicalCapabilitySnapshot,
        opportunities: OpportunitySet,
        capabilities: CapabilitySnapshotSet,
    ) -> ADR037PlanningResult:
        """Run requirement -> feasibility -> candidates -> simulation -> evaluation."""

        requirement = self.requirement_deriver.derive(
            requirement_id=requirement_id,
            balance=balance,
            effective_limit=effective_limit,
            confidence_assessment=confidence_assessment,
        )
        pv_only_feasibility = self.pv_feasibility_evaluator.evaluate(
            requirement=requirement,
            balance=balance,
            effective_limit=effective_limit,
        )
        technical_recoverability = self.recoverability_evaluator.evaluate(
            evaluated_at=evaluated_at,
            requirement=requirement,
            storage_state=storage_state,
            storage_limit=effective_limit,
            capability=storage_capability,
        )
        generated = self.candidate_engine.generate(
            snapshot,
            opportunities,
            capabilities,
            storage_requirement=requirement,
            pv_only_feasibility=pv_only_feasibility,
            storage_recoverability=technical_recoverability,
            projected_balance=balance,
            effective_storage_limit=effective_limit,
        )
        simulated_paths = tuple(
            self.simulator.simulate(
                path=path,
                snapshot=snapshot,
                storage_state=storage_state,
            )
            for path in generated.energy_paths
        )
        candidate_set = CandidateSet(
            snapshot_id=generated.snapshot_id,
            strategy_version=generated.strategy_version,
            candidates=generated.candidates,
            energy_paths=simulated_paths,
            exclusions=generated.exclusions,
        )
        candidate_outcomes = self.outcome_deriver.derive(
            candidate_set=candidate_set,
            forecasts=snapshot.forecasts,
            pv_only_feasibility=pv_only_feasibility,
            storage_recoverability=technical_recoverability,
        )
        evaluation = self.evaluation_engine.evaluate(
            candidate_set,
            snapshot.strategy,
            candidate_outcomes,
            created_at=evaluated_at,
        )
        return ADR037PlanningResult(
            requirement=requirement,
            pv_only_feasibility=pv_only_feasibility,
            technical_recoverability=technical_recoverability,
            candidate_set=candidate_set,
            candidate_outcomes=candidate_outcomes,
            evaluation=evaluation,
        )
