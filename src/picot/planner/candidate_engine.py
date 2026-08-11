"""Deterministic Candidate Engine implementing ADR-024, ADR-030, ADR-031 and ADR-037."""

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
from picot.domain.energy_path import EnergyPath, PathSegment, ProjectedEnergyState
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.domain.opportunity import Opportunity, OpportunityKind, OpportunitySet
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.storage_planning import EnergyRequirement, StoragePlanningState


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
                    purpose="Store available PV surplus under integration-managed balance control.",
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
                    purpose="Preserve cheap-price charging opportunity under integration-managed balance control.",
                )
            elif opportunity.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW:
                generated = []
                rejected = [
                    CandidateExclusion(
                        family=CandidateFamily.COST_FIRST,
                        kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                        reason=(
                            "High-value discharge remains excluded until a complete projected "
                            "SoC, reserve, recovery and economic-cycle path can be proven."
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

            primitives = tuple(
                primitive
                for primitive in CHARGE_BALANCE_PRIMITIVES
                if primitive in capability.supported_primitives
            )
            for primitive in primitives:
                projected_states, projection_assumptions, projection_error = self._project_nom_charge(
                    snapshot,
                    opportunity,
                    capability,
                    primitive,
                )
                if projection_error is not None:
                    exclusions.append(
                        CandidateExclusion(
                            family=family,
                            kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
                            reason=projection_error,
                            source_ids=(opportunity.opportunity_id, capability.capability_id),
                        )
                    )
                    continue

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
                confidence_inputs = [opportunity.confidence, capability.confidence]
                state = self._storage_state(snapshot, capability.capability_id)
                if state is not None:
                    confidence_inputs.append(state.confidence)
                confidence = min(confidence_inputs)
                paths.append(
                    EnergyPath(
                        path_id=path_id,
                        snapshot_id=snapshot.snapshot_id,
                        family=family,
                        horizon_start=snapshot.captured_at,
                        horizon_end=snapshot.horizon_end,
                        segments=(segment,),
                        projected_states=projected_states,
                        opportunity_ids=(opportunity.opportunity_id,),
                        constraint_ids=(),
                        capability_ids=(capability.capability_id,),
                        strategy_version=snapshot.strategy.strategy_version,
                        mapping_version=mapping_version,
                        assumptions=(
                            "Battery integration controls instantaneous NOM power; PicoT does not command watts.",
                            *projection_assumptions,
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

    def _project_nom_charge(
        self,
        snapshot: PlanningInputSnapshot,
        opportunity: Opportunity,
        capability: LogicalCapabilitySnapshot,
        primitive: ExecutionPrimitive,
    ) -> tuple[tuple[ProjectedEnergyState, ...], tuple[str, ...], str | None]:
        state = self._storage_state(snapshot, capability.capability_id)
        hard_requirements = self._hard_requirements(snapshot, capability.capability_id)
        pv_series = snapshot.forecasts.by_kind(ForecastKind.PV_POWER)
        load_series = snapshot.forecasts.by_kind(ForecastKind.HOUSEHOLD_LOAD)

        # Missing projection data does not invalidate a balance Candidate unless a
        # hard future storage state actually depends on that projection.
        if state is None or len(pv_series) != 1 or len(load_series) != 1:
            if hard_requirements:
                return (), (), (
                    "Hard storage requirement cannot be proven because NOM projection "
                    "requires one explicit storage state, one PV forecast and one load forecast."
                )
            return (), (
                "NOM SoC projection unavailable; no hard storage requirement depends on it.",
            ), None

        if state.charge_efficiency is None:
            if hard_requirements:
                return (), (), "Hard storage requirement cannot be proven without charge efficiency."
            return (), (
                "NOM SoC projection unavailable because charge efficiency is unknown.",
            ), None

        start = max(snapshot.captured_at, opportunity.starts_at)
        end = min(snapshot.horizon_end, opportunity.ends_at)
        points = self._paired_intervals(pv_series[0], load_series[0], start, end)
        soc = state.current_soc
        projected: list[ProjectedEnergyState] = [
            ProjectedEnergyState(at=start, confidence=state.confidence, battery_soc=soc)
        ]
        max_soc = capability.maximum_soc if capability.maximum_soc is not None else 1.0
        max_power = capability.maximum_power_w

        for interval_start, interval_end, pv, load, confidence in points:
            available_charge_w = max(0.0, pv - load)
            if max_power is not None:
                available_charge_w = min(available_charge_w, max_power)
            hours = (interval_end - interval_start).total_seconds() / 3600.0
            stored_wh = available_charge_w * hours * state.charge_efficiency
            soc = min(max_soc, soc + stored_wh / state.usable_capacity_wh)
            projected.append(
                ProjectedEnergyState(
                    at=interval_end,
                    confidence=min(state.confidence, confidence),
                    pv_production_w=max(0.0, pv),
                    household_demand_w=max(0.0, load),
                    controllable_load_w=available_charge_w,
                    battery_soc=soc,
                )
            )

        for requirement in hard_requirements:
            if requirement.deadline > end:
                return (), (), (
                    "Hard storage requirement extends beyond the supported NOM projection window."
                )
            requirement_soc = self._projected_soc_at(projected, requirement.deadline)
            if requirement_soc is None or requirement_soc < requirement.target_soc:
                return (), (), (
                    f"Hard storage requirement {requirement.requirement_id} is not projected "
                    "to reach its target SoC under NOM control."
                )

        assumptions = (
            "Expected NOM charge flow equals forecast PV surplus after household load, bounded by known capability limits.",
            f"Projection primitive: {primitive.value}; projected flow is evidence, not a setpoint.",
        )
        return tuple(projected), assumptions, None

    @staticmethod
    def _paired_intervals(
        pv_series: ForecastSeries,
        load_series: ForecastSeries,
        start,
        end,
    ) -> tuple[tuple[object, object, float, float, float], ...]:
        intervals: list[tuple[object, object, float, float, float]] = []
        for pv in pv_series.points:
            for load in load_series.points:
                interval_start = max(start, pv.starts_at, load.starts_at)
                interval_end = min(end, pv.ends_at, load.ends_at)
                if interval_end <= interval_start:
                    continue
                intervals.append(
                    (
                        interval_start,
                        interval_end,
                        pv.value,
                        load.value,
                        min(pv.confidence, load.confidence),
                    )
                )
        return tuple(sorted(intervals, key=lambda item: item[0]))

    @staticmethod
    def _storage_state(
        snapshot: PlanningInputSnapshot,
        capability_id: str,
    ) -> StoragePlanningState | None:
        return next(
            (item for item in snapshot.storage_states if item.capability_id == capability_id),
            None,
        )

    @staticmethod
    def _hard_requirements(
        snapshot: PlanningInputSnapshot,
        capability_id: str,
    ) -> tuple[EnergyRequirement, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in snapshot.energy_requirements
                    if item.capability_id == capability_id and item.hard
                ),
                key=lambda item: (item.deadline, item.requirement_id),
            )
        )

    @staticmethod
    def _projected_soc_at(
        projected: list[ProjectedEnergyState],
        moment,
    ) -> float | None:
        eligible = [state for state in projected if state.at <= moment and state.battery_soc is not None]
        if not eligible:
            return None
        return eligible[-1].battery_soc

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
