"""Deterministic Candidate Engine implementing ADR-024, ADR-030, ADR-031 and ADR-037."""

from __future__ import annotations

from math import ceil, floor

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
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.energy_path import EnergyPath, PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.opportunity import (
    Opportunity,
    OpportunityKind,
    OpportunityMetricKind,
    OpportunitySet,
)
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.projected_household_energy_balance import ProjectedHouseholdEnergyBalance
from picot.domain.pv_only_storage_feasibility import PVOnlyStorageEnergyFeasibility
from picot.domain.storage_energy_requirement import StorageEnergyRequirement
from picot.domain.storage_technical_recoverability import StorageTechnicalRecoverability


class CandidateEngine:
    """Build a small deterministic Candidate Set from atomic planner inputs."""

    def generate(
        self,
        snapshot: PlanningInputSnapshot,
        opportunities: OpportunitySet,
        capabilities: CapabilitySnapshotSet,
        *,
        storage_requirement: StorageEnergyRequirement | None = None,
        pv_only_feasibility: PVOnlyStorageEnergyFeasibility | None = None,
        storage_recoverability: StorageTechnicalRecoverability | None = None,
        projected_balance: ProjectedHouseholdEnergyBalance | None = None,
        effective_storage_limit: EffectiveStorageLimit | None = None,
    ) -> CandidateSet:
        self._validate_inputs(snapshot, opportunities, capabilities)
        self._validate_storage_evidence(
            storage_requirement,
            pv_only_feasibility,
            storage_recoverability,
            projected_balance,
            effective_storage_limit,
        )

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
            elif opportunity.kind in {
                OpportunityKind.NEGATIVE_PRICE_WINDOW,
                OpportunityKind.LOWEST_PRICE_WINDOW,
            }:
                if (
                    storage_requirement is None
                    or pv_only_feasibility is None
                    or storage_recoverability is None
                    or projected_balance is None
                    or effective_storage_limit is None
                ):
                    exclusions.append(
                        CandidateExclusion(
                            family=CandidateFamily.COST_FIRST,
                            kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                            reason=(
                                "Timed cost-first charging requires storage requirement, "
                                "PV-only feasibility, technical recoverability, projected "
                                "household balance and effective storage limit evidence."
                            ),
                            source_ids=(opportunity.opportunity_id,),
                        )
                    )
                    continue
                generated, rejected = self._build_grid_supported_storage_path(
                    snapshot=snapshot,
                    opportunity=opportunity,
                    capabilities=storage_capabilities,
                    mapping_version=capabilities.mapping_version,
                    requirement=storage_requirement,
                    pv_only_feasibility=pv_only_feasibility,
                    recoverability=storage_recoverability,
                    projected_balance=projected_balance,
                    effective_storage_limit=effective_storage_limit,
                )
            elif opportunity.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW:
                generated = []
                rejected = [
                    CandidateExclusion(
                        family=CandidateFamily.COST_FIRST,
                        kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                        reason=(
                            "High-value discharge requires projected SoC, reserve and "
                            "power-allocation support."
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
            raise ValueError(
                "Capability Snapshot Set must match the Planning Input Snapshot."
            )
        if capabilities.mapping_version != snapshot.versions.capability_mapping:
            raise ValueError("Capability mapping versions must match.")
        if capabilities.captured_at > snapshot.captured_at:
            raise ValueError(
                "Capability Snapshot Set cannot be captured after planning input."
            )

    @staticmethod
    def _validate_storage_evidence(
        requirement: StorageEnergyRequirement | None,
        pv_only_feasibility: PVOnlyStorageEnergyFeasibility | None,
        recoverability: StorageTechnicalRecoverability | None,
        projected_balance: ProjectedHouseholdEnergyBalance | None,
        effective_storage_limit: EffectiveStorageLimit | None,
    ) -> None:
        core_supplied = (
            requirement is not None,
            pv_only_feasibility is not None,
            recoverability is not None,
        )
        if any(core_supplied) and not all(core_supplied):
            raise ValueError(
                "Storage Candidate generation requires requirement, PV-only feasibility "
                "and technical recoverability together."
            )
        if requirement is None or pv_only_feasibility is None or recoverability is None:
            if projected_balance is not None or effective_storage_limit is not None:
                raise ValueError(
                    "Projected balance and effective storage limit require the complete "
                    "storage evidence set."
                )
            return
        if (projected_balance is None) != (effective_storage_limit is None):
            raise ValueError(
                "Projected balance and effective storage limit must be supplied together."
            )
        if pv_only_feasibility.requirement_id != requirement.requirement_id:
            raise ValueError("PV-only feasibility must match the storage requirement.")
        if recoverability.requirement_id != requirement.requirement_id:
            raise ValueError(
                "Technical recoverability must match the storage requirement."
            )
        if recoverability.protection_starts_at != requirement.protection_starts_at:
            raise ValueError(
                "Technical recoverability protection start must match the requirement."
            )
        if recoverability.protected_through != requirement.protected_through:
            raise ValueError(
                "Technical recoverability protected interval must match the requirement."
            )
        if projected_balance is not None:
            if projected_balance.execution_scope_id != requirement.execution_scope_id:
                raise ValueError(
                    "Projected balance execution scope must match the storage requirement."
                )
            if projected_balance.created_at != requirement.derived_at:
                raise ValueError(
                    "Projected balance and storage requirement must belong to the same run."
                )
        if effective_storage_limit is not None:
            if effective_storage_limit.execution_scope_id != requirement.execution_scope_id:
                raise ValueError(
                    "Effective storage limit execution scope must match the requirement."
                )

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
            return paths, [
                CandidateExclusion(
                    family=CandidateFamily.PV_FIRST,
                    kind=CandidateExclusionKind.UNSUPPORTED_CAPABILITY,
                    reason="No ENERGY_STORAGE capability is available.",
                    source_ids=(opportunity.opportunity_id,),
                )
            ]
        surplus_power = self._metric_value(
            opportunity,
            OpportunityMetricKind.MINIMUM_EXPECTED_POWER_W,
        )
        if surplus_power is None:
            return paths, [
                CandidateExclusion(
                    family=CandidateFamily.PV_FIRST,
                    kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                    reason="PV-first charging requires explicit expected surplus power.",
                    source_ids=(opportunity.opportunity_id,),
                )
            ]

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

    def _build_grid_supported_storage_path(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        opportunity: Opportunity,
        capabilities: tuple[LogicalCapabilitySnapshot, ...],
        mapping_version: int,
        requirement: StorageEnergyRequirement,
        pv_only_feasibility: PVOnlyStorageEnergyFeasibility,
        recoverability: StorageTechnicalRecoverability,
        projected_balance: ProjectedHouseholdEnergyBalance,
        effective_storage_limit: EffectiveStorageLimit,
    ) -> tuple[list[EnergyPath], list[CandidateExclusion]]:
        if pv_only_feasibility.energy_sufficient:
            return [], [
                CandidateExclusion(
                    family=CandidateFamily.COST_FIRST,
                    kind=CandidateExclusionKind.DOMINATED,
                    reason=(
                        "PV-only energy is sufficient for the storage requirement; "
                        "grid supplementation is unnecessary."
                    ),
                    source_ids=(opportunity.opportunity_id, requirement.requirement_id),
                )
            ]
        if not recoverability.additional_acquisition_required:
            return [], [
                CandidateExclusion(
                    family=CandidateFamily.COST_FIRST,
                    kind=CandidateExclusionKind.DOMINATED,
                    reason="No additional stored energy is required.",
                    source_ids=(opportunity.opportunity_id, requirement.requirement_id),
                )
            ]
        if not recoverability.technically_recoverable:
            return [], [
                CandidateExclusion(
                    family=CandidateFamily.COST_FIRST,
                    kind=CandidateExclusionKind.HARD_BOUNDARY,
                    reason=(
                        "Storage requirement is not technically recoverable before "
                        "the protected interval starts."
                    ),
                    source_ids=(opportunity.opportunity_id, requirement.requirement_id),
                )
            ]

        capability = next(
            (
                item
                for item in capabilities
                if item.capability_id == recoverability.capability_id
            ),
            None,
        )
        if capability is None:
            return [], [
                CandidateExclusion(
                    family=CandidateFamily.COST_FIRST,
                    kind=CandidateExclusionKind.UNSUPPORTED_CAPABILITY,
                    reason=(
                        "Technical recoverability references no current storage "
                        "capability."
                    ),
                    source_ids=(opportunity.opportunity_id, recoverability.capability_id),
                )
            ]
        reason = self._unsupported_pv_reason(capability)
        if reason is not None:
            return [], [
                CandidateExclusion(
                    family=CandidateFamily.COST_FIRST,
                    kind=CandidateExclusionKind.UNSUPPORTED_CAPABILITY,
                    reason=reason,
                    source_ids=(opportunity.opportunity_id, capability.capability_id),
                )
            ]

        starts_at = max(snapshot.captured_at, opportunity.starts_at)
        ends_at = min(
            snapshot.horizon_end,
            opportunity.ends_at,
            requirement.protection_starts_at,
        )
        if ends_at <= starts_at:
            return [], [
                CandidateExclusion(
                    family=CandidateFamily.COST_FIRST,
                    kind=CandidateExclusionKind.HARD_BOUNDARY,
                    reason=(
                        "Price Opportunity does not provide charge time before "
                        "the protected interval starts."
                    ),
                    source_ids=(opportunity.opportunity_id, requirement.requirement_id),
                )
            ]

        requested_power = self._grid_requested_power(
            required_energy_wh=recoverability.extra_energy_required_wh,
            starts_at=starts_at,
            ends_at=ends_at,
            capability=capability,
        )
        if requested_power is None:
            return [], [
                CandidateExclusion(
                    family=CandidateFamily.COST_FIRST,
                    kind=CandidateExclusionKind.HARD_BOUNDARY,
                    reason=(
                        "Price Opportunity cannot deliver the required storage energy "
                        "within capability power limits before protection starts."
                    ),
                    source_ids=(
                        opportunity.opportunity_id,
                        requirement.requirement_id,
                        capability.capability_id,
                    ),
                )
            ]

        path_id = (
            f"{snapshot.snapshot_id}:cost-first:{opportunity.opportunity_id}:"
            f"{capability.capability_id}:{requirement.requirement_id}"
        )
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    opportunity.opportunity_id,
                    requirement.requirement_id,
                    projected_balance.balance_id,
                    effective_storage_limit.limit_id,
                    *requirement.evidence_ids,
                    *pv_only_feasibility.evidence_ids,
                    *recoverability.evidence_ids,
                    *projected_balance.evidence_ids,
                    *effective_storage_limit.evidence_ids,
                )
            )
        )
        segment = PathSegment(
            segment_id=f"{path_id}:segment:1",
            order=1,
            execution_scope_id=capability.execution_scope_id,
            starts_at=starts_at,
            ends_at=ends_at,
            primitive=ExecutionPrimitive.CHARGE_AT_POWER,
            capability_id=capability.capability_id,
            purpose=(
                "Reach future storage requirement with PV preferred and grid support "
                "allowed."
            ),
            evidence_ids=evidence_ids,
            requested_power_w=requested_power,
            charge_source_policy=ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED,
        )
        confidence = min(
            opportunity.confidence,
            capability.confidence,
            requirement.confidence,
            pv_only_feasibility.confidence,
            recoverability.confidence,
            projected_balance.confidence,
        )
        path = EnergyPath(
            path_id=path_id,
            snapshot_id=snapshot.snapshot_id,
            family=CandidateFamily.COST_FIRST,
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
                "PV remains the preferred charging source.",
                "Grid supplementation is permitted only by this Energy Path.",
                "The storage-energy target must be available when protection starts.",
                f"Canonical projected balance: {projected_balance.balance_id}.",
                f"Effective storage ceiling: {effective_storage_limit.limit_id}.",
            ),
            confidence=confidence,
        )
        return [path], []

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
        if (
            capability.minimum_power_w is not None
            and requested < capability.minimum_power_w
        ):
            return None
        return requested

    @staticmethod
    def _grid_requested_power(
        *,
        required_energy_wh: float,
        starts_at: object,
        ends_at: object,
        capability: LogicalCapabilitySnapshot,
    ) -> float | None:
        duration_seconds = (ends_at - starts_at).total_seconds()  # type: ignore[operator]
        duration_hours = duration_seconds / 3600.0
        if duration_hours <= 0.0:
            return None
        maximum = capability.maximum_power_w
        if maximum is None:
            return None
        requested = required_energy_wh / duration_hours
        if capability.power_step_w is not None:
            requested = ceil(requested / capability.power_step_w) * capability.power_step_w
        if capability.minimum_power_w is not None:
            requested = max(requested, capability.minimum_power_w)
        if requested <= 0.0 or requested > maximum:
            return None
        return float(requested)

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