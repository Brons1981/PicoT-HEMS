"""Deterministic Candidate Engine implementing ADR-024, ADR-030 and ADR-031."""

from __future__ import annotations

from math import floor

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
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import EnergyPath, PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.opportunity import (
    Opportunity,
    OpportunityKind,
    OpportunityMetricKind,
    OpportunitySet,
)
from picot.domain.planning_input_snapshot import PlanningInputSnapshot


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
                generated, rejected = self._build_pv_first_paths(
                    snapshot,
                    opportunity,
                    storage_capabilities,
                    capabilities.mapping_version,
                )
                paths.extend(generated)
                candidates.extend(self._candidate_for(path) for path in generated)
                exclusions.extend(rejected)
            elif opportunity.kind in {
                OpportunityKind.NEGATIVE_PRICE_WINDOW,
                OpportunityKind.LOWEST_PRICE_WINDOW,
            }:
                exclusions.append(
                    CandidateExclusion(
                        family=CandidateFamily.COST_FIRST,
                        kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                        reason=(
                            "Cost-first charging requires an accepted energy-target "
                            "or power-allocation contract."
                        ),
                        source_ids=(opportunity.opportunity_id,),
                    )
                )
            elif opportunity.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW:
                exclusions.append(
                    CandidateExclusion(
                        family=CandidateFamily.COST_FIRST,
                        kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                        reason=(
                            "High-value discharge requires projected SoC, reserve and "
                            "power-allocation support."
                        ),
                        source_ids=(opportunity.opportunity_id,),
                    )
                )

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

    def _build_pv_first_paths(
        self,
        snapshot: PlanningInputSnapshot,
        opportunity: Opportunity,
        capabilities: tuple[LogicalCapabilitySnapshot, ...],
        mapping_version: int,
    ) -> tuple[list[EnergyPath], list[CandidateExclusion]]:
        paths: list[EnergyPath] = []
        exclusions: list[CandidateExclusion] = []

        if not capabilities:
            exclusions.append(
                CandidateExclusion(
                    family=CandidateFamily.PV_FIRST,
                    kind=CandidateExclusionKind.UNSUPPORTED_CAPABILITY,
                    reason="No ENERGY_STORAGE capability is available.",
                    source_ids=(opportunity.opportunity_id,),
                )
            )
            return paths, exclusions

        surplus_power = self._metric_value(
            opportunity,
            OpportunityMetricKind.MINIMUM_EXPECTED_POWER_W,
        )
        if surplus_power is None:
            exclusions.append(
                CandidateExclusion(
                    family=CandidateFamily.PV_FIRST,
                    kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                    reason="PV-first charging requires explicit expected surplus power.",
                    source_ids=(opportunity.opportunity_id,),
                )
            )
            return paths, exclusions

        for capability in capabilities:
            reason = self._unsupported_pv_reason(capability)
            if reason is not None:
                exclusions.append(
                    CandidateExclusion(
                        family=CandidateFamily.PV_FIRST,
                        kind=CandidateExclusionKind.UNSUPPORTED_CAPABILITY,
                        reason=reason,
                        source_ids=(opportunity.opportunity_id, capability.capability_id),
                    )
                )
                continue

            requested_power = self._requested_power(surplus_power, capability)
            if requested_power is None:
                exclusions.append(
                    CandidateExclusion(
                        family=CandidateFamily.PV_FIRST,
                        kind=CandidateExclusionKind.HARD_BOUNDARY,
                        reason="Requested PV charge power violates capability limits.",
                        source_ids=(opportunity.opportunity_id, capability.capability_id),
                    )
                )
                continue

            path_id = (
                f"{snapshot.snapshot_id}:pv-first:{opportunity.opportunity_id}:"
                f"{capability.capability_id}"
            )
            segment = PathSegment(
                segment_id=f"{path_id}:segment:1",
                order=1,
                execution_scope_id=capability.execution_scope_id,
                starts_at=max(snapshot.captured_at, opportunity.starts_at),
                ends_at=min(snapshot.horizon_end, opportunity.ends_at),
                primitive=ExecutionPrimitive.CHARGE_AT_POWER,
                capability_id=capability.capability_id,
                purpose="Store expected PV surplus.",
                evidence_ids=(opportunity.opportunity_id,),
                requested_power_w=requested_power,
                charge_source_policy=ChargeSourcePolicy.PV_ONLY,
            )
            confidence = min(opportunity.confidence, capability.confidence)
            paths.append(
                EnergyPath(
                    path_id=path_id,
                    snapshot_id=snapshot.snapshot_id,
                    family=CandidateFamily.PV_FIRST,
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
                        "PV surplus remains available within recorded confidence.",
                    ),
                    confidence=confidence,
                )
            )

        return paths, exclusions

    @staticmethod
    def _unsupported_pv_reason(
        capability: LogicalCapabilitySnapshot,
    ) -> str | None:
        if capability.availability is not CapabilityAvailability.AVAILABLE:
            return "Storage capability is not available."
        if capability.health is not CapabilityHealth.HEALTHY:
            return "Storage capability is not healthy."
        if ExecutionPrimitive.CHARGE_AT_POWER not in capability.supported_primitives:
            return "Storage capability does not support CHARGE_AT_POWER."
        if EnergyFlowDirection.CHARGE not in capability.flow_directions:
            return "Storage capability does not support charge flow."
        if capability.maximum_power_w is None:
            return "Storage capability maximum power is unknown."
        return None

    @staticmethod
    def _requested_power(
        surplus_power: float,
        capability: LogicalCapabilitySnapshot,
    ) -> float | None:
        maximum = capability.maximum_power_w
        if maximum is None:
            return None
        requested = min(surplus_power, maximum)
        if capability.power_step_w is not None:
            requested = floor(requested / capability.power_step_w) * capability.power_step_w
        if requested <= 0:
            return None
        if capability.minimum_power_w is not None and requested < capability.minimum_power_w:
            return None
        return requested

    @staticmethod
    def _metric_value(
        opportunity: Opportunity,
        kind: OpportunityMetricKind,
    ) -> float | None:
        for metric in opportunity.metrics:
            if metric.kind is kind:
                return metric.value
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
