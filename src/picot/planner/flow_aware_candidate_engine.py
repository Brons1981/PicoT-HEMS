"""Flow-aware Candidate generation for closed-loop ADR-037 planning."""

from __future__ import annotations

from picot.domain.candidate import (
    Candidate,
    CandidateExclusion,
    CandidateExclusionKind,
    CandidateFamily,
    CandidateSet,
)
from picot.domain.capability_snapshot import CapabilityRole, CapabilitySnapshotSet
from picot.domain.energy_path import EnergyPath, PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.opportunity import OpportunitySet
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.pv_only_storage_feasibility import PVOnlyStorageEnergyFeasibility
from picot.domain.storage_energy_requirement import StorageEnergyRequirement
from picot.domain.storage_technical_recoverability import StorageTechnicalRecoverability
from picot.planner.candidate_engine import CandidateEngine


class FlowAwareCandidateEngine(CandidateEngine):
    """Replace the passive baseline when current flow evidence requires correction."""

    def generate(
        self,
        snapshot: PlanningInputSnapshot,
        opportunities: OpportunitySet,
        capabilities: CapabilitySnapshotSet,
        *,
        storage_requirement: StorageEnergyRequirement | None = None,
        pv_only_feasibility: PVOnlyStorageEnergyFeasibility | None = None,
        storage_recoverability: StorageTechnicalRecoverability | None = None,
    ) -> CandidateSet:
        base = super().generate(
            snapshot,
            opportunities,
            capabilities,
            storage_requirement=storage_requirement,
            pv_only_feasibility=pv_only_feasibility,
            storage_recoverability=storage_recoverability,
        )
        observation = snapshot.current_flow_observation
        if observation is None or not observation.persistent_mismatch:
            return base
        if not observation.discharge_while_exporting:
            return base

        storage_capability = next(
            (
                capability
                for capability in capabilities.capabilities
                if capability.role is CapabilityRole.ENERGY_STORAGE
                and ExecutionPrimitive.BALANCE_BIDIRECTIONAL
                in capability.supported_primitives
            ),
            None,
        )

        baseline_ids = {
            path.path_id
            for path in base.energy_paths
            if path.family is CandidateFamily.RESERVE_FIRST and not path.segments
        }
        kept_paths = tuple(path for path in base.energy_paths if path.path_id not in baseline_ids)
        kept_candidates = tuple(
            candidate
            for candidate in base.candidates
            if candidate.energy_path_id not in baseline_ids
        )

        if storage_capability is None:
            return CandidateSet(
                snapshot_id=base.snapshot_id,
                strategy_version=base.strategy_version,
                candidates=kept_candidates,
                energy_paths=kept_paths,
                exclusions=(
                    *base.exclusions,
                    CandidateExclusion(
                        family=CandidateFamily.RESERVE_FIRST,
                        kind=CandidateExclusionKind.UNSUPPORTED_CAPABILITY,
                        reason=(
                            "Persistent discharge-while-exporting requires a storage "
                            "BALANCE_BIDIRECTIONAL capability; passive baseline is not valid."
                        ),
                        source_ids=(observation.observation_id,),
                    ),
                ),
            )

        path_id = f"{snapshot.snapshot_id}:flow-correction:preserve-storage"
        evidence_ids = tuple(
            dict.fromkeys((observation.observation_id, *observation.evidence_ids))
        )
        path = EnergyPath(
            path_id=path_id,
            snapshot_id=snapshot.snapshot_id,
            family=CandidateFamily.RESERVE_FIRST,
            horizon_start=snapshot.captured_at,
            horizon_end=snapshot.horizon_end,
            segments=(
                PathSegment(
                    segment_id=f"{path_id}:segment:1",
                    order=1,
                    execution_scope_id=storage_capability.execution_scope_id,
                    starts_at=snapshot.captured_at,
                    ends_at=snapshot.horizon_end,
                    primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                    capability_id=storage_capability.capability_id,
                    purpose=(
                        "Stop contradictory battery discharge while the household is "
                        "exporting and return storage to delegated bidirectional balancing."
                    ),
                    evidence_ids=evidence_ids,
                ),
            ),
            projected_states=(),
            opportunity_ids=(),
            constraint_ids=(observation.observation_id,),
            capability_ids=(storage_capability.capability_id,),
            strategy_version=snapshot.strategy.strategy_version,
            mapping_version=capabilities.mapping_version,
            assumptions=(
                "Persistent current-flow evidence overrides the passive no-action baseline.",
                "Bidirectional balancing stops forced discharge and may absorb live surplus.",
            ),
            confidence=1.0,
        )
        candidate = Candidate(
            candidate_id=f"candidate:{path_id}",
            snapshot_id=snapshot.snapshot_id,
            family=path.family,
            energy_path_id=path.path_id,
            opportunity_ids=path.opportunity_ids,
            constraint_ids=path.constraint_ids,
            strategy_version=path.strategy_version,
            capability_ids=path.capability_ids,
            assumptions=path.assumptions,
            confidence=path.confidence,
        )
        return CandidateSet(
            snapshot_id=base.snapshot_id,
            strategy_version=base.strategy_version,
            candidates=(candidate, *kept_candidates),
            energy_paths=(path, *kept_paths),
            exclusions=base.exclusions,
        )
