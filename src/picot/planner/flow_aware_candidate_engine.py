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
from picot.domain.opportunity import OpportunityKind, OpportunitySet
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.pv_only_storage_feasibility import PVOnlyStorageEnergyFeasibility
from picot.domain.storage_energy_requirement import StorageEnergyRequirement
from picot.domain.storage_technical_recoverability import StorageTechnicalRecoverability
from picot.planner.candidate_engine import CandidateEngine


class FlowAwareCandidateEngine(CandidateEngine):
    """Turn live flow and planning evidence into explicit delegated storage paths."""

    grid_deadband_w: float = 50.0

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
        if (
            observation is not None
            and observation.persistent_mismatch
            and observation.discharge_while_exporting
        ):
            return self._replace_baseline(
                base,
                snapshot=snapshot,
                capabilities=capabilities,
                primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                path_suffix="flow-correction:preserve-storage",
                purpose=(
                    "Stop contradictory battery discharge while exporting and return "
                    "storage to delegated bidirectional balancing."
                ),
                evidence_ids=(observation.observation_id, *observation.evidence_ids),
                constraint_ids=(observation.observation_id,),
                unsupported_reason=(
                    "Persistent discharge-while-exporting requires a storage "
                    "BALANCE_BIDIRECTIONAL capability; passive baseline is not valid."
                ),
            )

        primitive, reason = self._normal_control_primitive(
            snapshot,
            opportunities=opportunities,
            storage_recoverability=storage_recoverability,
        )
        if primitive is None:
            return base
        return self._replace_baseline(
            base,
            snapshot=snapshot,
            capabilities=capabilities,
            primitive=primitive,
            path_suffix=(
                "delegated-control:nom"
                if primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
                else "delegated-control:slim-discharge"
            ),
            purpose=reason,
            evidence_ids=(snapshot.snapshot_id,),
            constraint_ids=(),
            unsupported_reason=(
                f"Live delegated control requires {primitive.value} capability; "
                "passive baseline is retained fail-closed."
            ),
            keep_baseline_when_unsupported=True,
        )

    def _normal_control_primitive(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        opportunities: OpportunitySet,
        storage_recoverability: StorageTechnicalRecoverability | None,
    ) -> tuple[ExecutionPrimitive | None, str]:
        grid_power_w = snapshot.household_state.grid_power_w
        if grid_power_w is None:
            return None, "Grid flow is unavailable; keep the current delegated mode."

        if grid_power_w <= -self.grid_deadband_w:
            return (
                ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                "Grid export is present; allow bidirectional balancing so live surplus can charge storage.",
            )

        active_low_price = any(
            item.kind is OpportunityKind.LOWEST_PRICE_WINDOW
            and item.starts_at <= snapshot.captured_at < item.ends_at
            for item in opportunities.opportunities
        )
        if active_low_price:
            return (
                ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                "A canonical low-price opportunity is active; keep charging permission available.",
            )

        if (
            storage_recoverability is not None
            and storage_recoverability.extra_energy_required_wh > 0.0
        ):
            return (
                ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                "Storage still has a future energy shortfall; keep delegated charging permission available.",
            )

        if grid_power_w >= self.grid_deadband_w:
            return (
                ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
                "The household is importing and no current charge permission is required; use delegated discharge-only balancing.",
            )

        return None, "Grid flow is inside the deadband; keep the current delegated mode."

    def _replace_baseline(
        self,
        base: CandidateSet,
        *,
        snapshot: PlanningInputSnapshot,
        capabilities: CapabilitySnapshotSet,
        primitive: ExecutionPrimitive,
        path_suffix: str,
        purpose: str,
        evidence_ids: tuple[str, ...],
        constraint_ids: tuple[str, ...],
        unsupported_reason: str,
        keep_baseline_when_unsupported: bool = False,
    ) -> CandidateSet:
        storage_capability = next(
            (
                capability
                for capability in capabilities.capabilities
                if capability.role is CapabilityRole.ENERGY_STORAGE
                and primitive in capability.supported_primitives
            ),
            None,
        )
        baseline_ids = {
            path.path_id
            for path in base.energy_paths
            if path.family is CandidateFamily.RESERVE_FIRST and not path.segments
        }
        if not baseline_ids:
            return base
        if storage_capability is None and keep_baseline_when_unsupported:
            return base

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
                        reason=unsupported_reason,
                        source_ids=evidence_ids,
                    ),
                ),
            )

        path_id = f"{snapshot.snapshot_id}:{path_suffix}"
        unique_evidence_ids = tuple(dict.fromkeys(evidence_ids))
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
                    primitive=primitive,
                    capability_id=storage_capability.capability_id,
                    purpose=purpose,
                    evidence_ids=unique_evidence_ids,
                ),
            ),
            projected_states=(),
            opportunity_ids=(),
            constraint_ids=constraint_ids,
            capability_ids=(storage_capability.capability_id,),
            strategy_version=snapshot.strategy.strategy_version,
            mapping_version=capabilities.mapping_version,
            assumptions=(purpose,),
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
