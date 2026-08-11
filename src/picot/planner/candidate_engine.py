"""Deterministic Candidate Engine implementing ADR-024, ADR-030, ADR-031 and ADR-037.

Candidate Generation constructs supported scenario paths. It does not perform
price detection, storage simulation or execution. See ADR-017.
"""

from __future__ import annotations

from picot.domain.candidate import (
    Candidate,
    CandidateExclusion,
    CandidateExclusionKind,
    CandidateFamily,
    CandidateSet,
)
from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.energy_path import EnergyPath, PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.opportunity import Opportunity, OpportunityKind, OpportunitySet
from picot.domain.planning_input_snapshot import PlanningInputSnapshot


CHARGE_BALANCE_PRIMITIVES = (
    ExecutionPrimitive.BALANCE_CHARGE_ONLY,
    ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
)


class CandidateEngine:
    """Build a small deterministic Candidate Set from atomic planner inputs."""

    def generate(
        self,
        snapshot: PlanningInputSnapshot,
        opportunities: OpportunitySet,
        capabilities: CapabilitySnapshotSet,
    ) -> CandidateSet:
        self._validate_inputs(snapshot, opportunities, capabilities)

        paths: list[EnergyPath] = [self._baseline_path(snapshot, capabilities)]
        candidates: list[Candidate] = [self._candidate_for(paths[0])]
        exclusions: list[CandidateExclusion] = []

        storage_capabilities = tuple(
            sorted(
                (
                    capability
                    for capability in capabilities.capabilities
                    if capability.role is CapabilityRole.ENERGY_STORAGE
                ),
                key=lambda capability: capability.capability_id,
            )
        )

        for opportunity in sorted(
            opportunities.opportunities,
            key=lambda item: (item.starts_at, item.opportunity_id),
        ):
            if opportunity.kind is OpportunityKind.PV_SURPLUS_WINDOW:
                generated, rejected = self._build_balance_charge_paths(
                    snapshot,
                    opportunity,
                    storage_capabilities,
                    capabilities.mapping_version,
                    family=CandidateFamily.PV_FIRST,
                    purpose="Use a PV-surplus opportunity with integration-managed charging.",
                )
            elif opportunity.kind in {
                OpportunityKind.NEGATIVE_PRICE_WINDOW,
                OpportunityKind.LOWEST_PRICE_WINDOW,
            }:
                generated, rejected = self._build_balance_charge_paths(
                    snapshot,
                    opportunity,
                    storage_capabilities,
                    capabilities.mapping_version,
                    family=CandidateFamily.COST_FIRST,
                    purpose="Use a low-price opportunity with integration-managed charging.",
                )
            elif opportunity.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW:
                generated = []
                rejected = [
                    CandidateExclusion(
                        family=CandidateFamily.COST_FIRST,
                        kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                        reason=(
                            "High-value discharge remains excluded until Simulation can prove "
                            "SoC, reserve, recovery and economic-cycle feasibility."
                        ),
                        source_ids=(opportunity.opportunity_id,),
                    )
                ]
            else:
                continue

            paths.extend(generated)
            candidates.extend(self._candidate_for(path) for path in generated)
            exclusions.extend(rejected)

        return CandidateSet(
            snapshot_id=snapshot.snapshot_id,
            strategy_version=snapshot.strategy.strategy_version,
            candidates=tuple(candidates),
            energy_paths=tuple(paths),
            exclusions=tuple(exclusions),
        )

    @staticmethod
    def _validate_inputs(
        snapshot: PlanningInputSnapshot,
        opportunities: OpportunitySet,
        capabilities: CapabilitySnapshotSet,
    ) -> None:
        if opportunities.snapshot_id != snapshot.snapshot_id:
            raise ValueError("Opportunity Set must match the Planning Input Snapshot.")
        if capabilities.snapshot_id != snapshot.snapshot_id:
            raise ValueError("Capability Snapshot Set must match the Planning Input Snapshot.")
        if capabilities.mapping_version != snapshot.versions.capability_mapping:
            raise ValueError("Capability mapping versions must match.")
        if capabilities.captured_at > snapshot.captured_at:
            raise ValueError("Capability Snapshot Set cannot be captured after planning input.")

    @staticmethod
    def _baseline_path(
        snapshot: PlanningInputSnapshot,
        capabilities: CapabilitySnapshotSet,
    ) -> EnergyPath:
        return EnergyPath(
            path_id=f"{snapshot.snapshot_id}:baseline:reserve-first",
            snapshot_id=snapshot.snapshot_id,
            family=CandidateFamily.RESERVE_FIRST,
            horizon_start=snapshot.captured_at,
            horizon_end=snapshot.horizon_end,
            segments=(),
            projected_states=(),
            opportunity_ids=(),
            constraint_ids=(),
            capability_ids=(),
            strategy_version=snapshot.strategy.strategy_version,
            mapping_version=capabilities.mapping_version,
            assumptions=("No speculative controllable action is scheduled.",),
            confidence=1.0,
        )

    def _build_balance_charge_paths(
        self,
        snapshot: PlanningInputSnapshot,
        opportunity: Opportunity,
        capabilities: tuple[LogicalCapabilitySnapshot, ...],
        mapping_version: int,
        *,
        family: CandidateFamily,
        purpose: str,
    ) -> tuple[list[EnergyPath], list[CandidateExclusion]]:
        paths: list[EnergyPath] = []
        exclusions: list[CandidateExclusion] = []

        if not capabilities:
            return paths, [
                CandidateExclusion(
                    family=family,
                    kind=CandidateExclusionKind.UNSUPPORTED_CAPABILITY,
                    reason="No ENERGY_STORAGE capability is available.",
                    source_ids=(opportunity.opportunity_id,),
                )
            ]

        for capability in capabilities:
            reason = self._unsupported_balance_charge_reason(capability)
            if reason is not None:
                exclusions.append(
                    CandidateExclusion(
                        family=family,
                        kind=CandidateExclusionKind.UNSUPPORTED_CAPABILITY,
                        reason=reason,
                        source_ids=(opportunity.opportunity_id, capability.capability_id),
                    )
                )
                continue

            primitive = next(
                primitive
                for primitive in CHARGE_BALANCE_PRIMITIVES
                if primitive in capability.supported_primitives
            )
            path_id = (
                f"{snapshot.snapshot_id}:{family.value}:{opportunity.opportunity_id}:"
                f"{capability.capability_id}:{primitive.value}"
            )
            segment = PathSegment(
                segment_id=f"{path_id}:segment:1",
                order=1,
                execution_scope_id=capability.execution_scope_id,
                starts_at=max(snapshot.captured_at, opportunity.starts_at),
                ends_at=min(snapshot.horizon_end, opportunity.ends_at),
                primitive=primitive,
                capability_id=capability.capability_id,
                purpose=purpose,
                evidence_ids=(opportunity.opportunity_id,),
            )
            confidence = min(opportunity.confidence, capability.confidence)
            paths.append(
                EnergyPath(
                    path_id=path_id,
                    snapshot_id=snapshot.snapshot_id,
                    family=family,
                    horizon_start=snapshot.captured_at,
                    horizon_end=snapshot.horizon_end,
                    segments=(segment,),
                    projected_states=(),
                    opportunity_ids=(opportunity.opportunity_id,),
                    constraint_ids=(),
                    capability_ids=(capability.capability_id,),
                    strategy_version=snapshot.strategy.strategy_version,
                    mapping_version=mapping_version,
                    assumptions=(
                        "Battery integration owns instantaneous NOM power; no requested_power_w is attached.",
                        "Candidate Generation does not calculate SoC, charge duration or expected NOM power; Simulation owns projection.",
                    ),
                    confidence=confidence,
                )
            )

        return paths, exclusions

    @staticmethod
    def _unsupported_balance_charge_reason(
        capability: LogicalCapabilitySnapshot,
    ) -> str | None:
        if capability.availability is not CapabilityAvailability.AVAILABLE:
            return "Storage capability is not available."
        if capability.health is not CapabilityHealth.HEALTHY:
            return "Storage capability is not healthy."
        if EnergyFlowDirection.CHARGE not in capability.flow_directions and (
            EnergyFlowDirection.BIDIRECTIONAL not in capability.flow_directions
        ):
            return "Storage capability does not support charge flow."
        if not any(
            primitive in capability.supported_primitives
            for primitive in CHARGE_BALANCE_PRIMITIVES
        ):
            return "Storage capability does not support a charge-capable BALANCE primitive."
        return None

    @staticmethod
    def _candidate_for(path: EnergyPath) -> Candidate:
        return Candidate(
            candidate_id=f"candidate:{path.path_id}",
            snapshot_id=path.snapshot_id,
            family=path.family,
            energy_path_id=path.path_id,
            opportunity_ids=path.opportunity_ids,
            constraint_ids=path.constraint_ids,
            strategy_version=path.strategy_version,
            capability_ids=path.capability_ids,
            assumptions=path.assumptions,
            confidence=path.confidence,
        )
