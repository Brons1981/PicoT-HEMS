"""Fail-closed adapter from existing v2 Candidates to V2ADR-054 simulation."""

from __future__ import annotations

from datetime import datetime

from picot.domain.candidate import CandidateFamily
from picot.domain.current_storage_state import CurrentStorageState as DomainStorageState
from picot.domain.energy_contract import EnergyTariffInterval
from picot.domain.energy_path import EnergyPath as DomainEnergyPath
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastSet
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast as DomainLoadForecast,
)
from picot.domain.household_load_forecast import (
    HouseholdLoadForecastInterval as DomainLoadInterval,
)
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot as DomainPlanningInputSnapshot,
)
from picot.domain.planning_input_snapshot import (
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyTimeline as DomainPVTimeline,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyTimelineInterval as DomainPVInterval,
)
from picot.planner.canonical_household_energy_simulator import (
    CanonicalHouseholdEnergySimulator,
)
from picot.v2.contracts import (
    Candidate,
    CandidateOutcomeSet,
    CandidateSet,
    DelegatedStorageCandidateOutcome,
    EnergyPath,
    PlanningInputSnapshot,
    ReferenceCandidateSimulation,
    ReferenceSimulationSet,
)

METHOD_VERSION = "v2-canonical-reference-observer:v2"
ADAPTER_METHOD_VERSION = "v2-to-domain-reference-adapter:v2"


class CanonicalReferenceObserver:
    """Simulate exact supported Candidates without influencing their selection."""

    def __init__(self) -> None:
        self._simulator = CanonicalHouseholdEnergySimulator()

    def observe(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        candidate_set: CandidateSet,
        outcomes: CandidateOutcomeSet,
    ) -> ReferenceSimulationSet:
        observations = tuple(
            self._observe_candidate(
                snapshot=snapshot,
                candidate=candidate,
                path=next(
                    path
                    for path in candidate_set.energy_paths
                    if path.path_id == candidate.energy_path_id
                ),
                legacy_outcome=next(
                    (
                        outcome
                        for outcome in outcomes.outcomes
                        if outcome.candidate_id == candidate.candidate_id
                    ),
                    None,
                ),
            )
            for candidate in candidate_set.candidates
        )
        return ReferenceSimulationSet(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            candidate_set_id=candidate_set.candidate_set_id,
            observations=observations,
            method_version=METHOD_VERSION,
        )

    def _observe_candidate(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        candidate: Candidate,
        path: EnergyPath,
        legacy_outcome: DelegatedStorageCandidateOutcome | None,
    ) -> ReferenceCandidateSimulation:
        missing = []
        if snapshot.energy_contract_snapshot is None:
            missing.append("energy_contract_snapshot_missing")
        if snapshot.storage_conversion_model is None:
            missing.append("storage_conversion_model_missing")
        if missing:
            return self._blocked(candidate.candidate_id, path.path_id, tuple(missing))
        unsupported = tuple(
            dict.fromkeys(
                f"unsupported_primitive:{segment.primitive.value}"
                for segment in path.segments
                if segment.primitive is not ExecutionPrimitive.CHARGE_AT_POWER
            )
        )
        if unsupported:
            return self._blocked(candidate.candidate_id, path.path_id, unsupported)
        if snapshot.horizon_end is None:
            return self._blocked(
                candidate.candidate_id,
                path.path_id,
                ("planning_horizon_missing",),
            )
        if not snapshot.current_storage_states:
            return self._blocked(
                candidate.candidate_id,
                path.path_id,
                ("current_storage_state_missing",),
            )
        if snapshot.pv_energy_timeline is None or snapshot.household_load_forecast is None:
            return self._blocked(
                candidate.candidate_id,
                path.path_id,
                ("canonical_pv_or_load_input_missing",),
            )
        try:
            assert snapshot.energy_contract_snapshot is not None
            assert snapshot.storage_conversion_model is not None
            domain_snapshot, domain_path, domain_storage = self._adapt(
                snapshot=snapshot,
                candidate_family=candidate.family,
                path=path,
            )
            requirement_target = (
                legacy_outcome.required_energy_wh
                if legacy_outcome is not None
                and any(
                    segment.charge_source_policy is not None
                    and segment.charge_source_policy.value
                    == "grid_allowed_for_requirement"
                    for segment in path.segments
                )
                else None
            )
            ledger = self._simulator.simulate(
                run_id=snapshot.run_id,
                candidate_id=candidate.candidate_id,
                path=domain_path,
                snapshot=domain_snapshot,
                storage_state=domain_storage,
                conversion_model=snapshot.storage_conversion_model,
                energy_contract=snapshot.energy_contract_snapshot,
                requirement_target_energy_wh=requirement_target,
            )
        except ValueError as exc:
            return self._blocked(
                candidate.candidate_id,
                path.path_id,
                (f"simulation_blocked:{exc}",),
            )
        reference_pv = sum(item.pv_to_storage_input_wh for item in ledger.intervals)
        reference_grid = sum(item.grid_to_storage_input_wh for item in ledger.intervals)
        reference_losses = sum(
            item.storage_charge_loss_wh + item.storage_discharge_loss_wh
            for item in ledger.intervals
        )
        legacy_pv = legacy_outcome.pv_storage_contribution_wh if legacy_outcome else None
        legacy_grid = legacy_outcome.grid_storage_contribution_wh if legacy_outcome else None
        legacy_losses = legacy_outcome.conversion_losses_wh if legacy_outcome else None
        return ReferenceCandidateSimulation(
            candidate_id=candidate.candidate_id,
            energy_path_id=path.path_id,
            status="ready",
            blockers=(),
            ledger=ledger,
            reference_pv_storage_wh=reference_pv,
            reference_grid_storage_wh=reference_grid,
            reference_grid_import_wh=sum(item.grid_import_wh for item in ledger.intervals),
            reference_grid_export_wh=sum(item.grid_export_wh for item in ledger.intervals),
            reference_conversion_losses_wh=reference_losses,
            legacy_pv_storage_wh=legacy_pv,
            legacy_grid_storage_wh=legacy_grid,
            legacy_conversion_losses_wh=legacy_losses,
            pv_storage_delta_wh=(reference_pv - legacy_pv if legacy_pv is not None else None),
            grid_storage_delta_wh=(
                reference_grid - legacy_grid if legacy_grid is not None else None
            ),
            conversion_losses_delta_wh=(
                reference_losses - legacy_losses if legacy_losses is not None else None
            ),
        )

    @staticmethod
    def _blocked(
        candidate_id: str,
        energy_path_id: str,
        blockers: tuple[str, ...],
    ) -> ReferenceCandidateSimulation:
        return ReferenceCandidateSimulation(
            candidate_id=candidate_id,
            energy_path_id=energy_path_id,
            status="blocked",
            blockers=blockers,
        )

    @staticmethod
    def _adapt(
        *,
        snapshot: PlanningInputSnapshot,
        candidate_family: str,
        path: EnergyPath,
    ) -> tuple[DomainPlanningInputSnapshot, DomainEnergyPath, DomainStorageState]:
        assert snapshot.horizon_end is not None
        assert snapshot.pv_energy_timeline is not None
        assert snapshot.household_load_forecast is not None
        assert snapshot.energy_contract_snapshot is not None
        target_intervals = snapshot.energy_contract_snapshot.intervals
        if (
            target_intervals[0].starts_at != snapshot.captured_at
            or target_intervals[-1].ends_at != snapshot.horizon_end
            or any(
                left.ends_at != right.starts_at
                for left, right in zip(
                    target_intervals,
                    target_intervals[1:],
                    strict=False,
                )
            )
        ):
            raise ValueError(
                "Reference tariffs must be contiguous across the planning horizon."
            )
        storage = snapshot.current_storage_states[0]
        domain_storage = DomainStorageState(
            storage_state_id=storage.storage_state_id,
            execution_scope_id=storage.execution_scope_id,
            capability_id=storage.capability_id,
            current_soc=storage.current_soc,
            usable_capacity_wh=storage.usable_capacity_wh,
            measured_at=storage.measured_at,
            confidence=storage.confidence,
            evidence_ids=storage.evidence_ids,
        )
        domain_pv = DomainPVTimeline(
            timeline_id=snapshot.pv_energy_timeline.timeline_id,
            created_at=snapshot.captured_at,
            horizon_start=snapshot.captured_at,
            horizon_end=snapshot.horizon_end,
            intervals=CanonicalReferenceObserver._normalise_pv_intervals(
                snapshot,
                target_intervals,
            ),
        )
        domain_load = DomainLoadForecast(
            forecast_id=snapshot.household_load_forecast.forecast_id,
            created_at=snapshot.captured_at,
            horizon_start=snapshot.captured_at,
            horizon_end=snapshot.horizon_end,
            intervals=CanonicalReferenceObserver._normalise_load_intervals(
                snapshot,
                target_intervals,
            ),
            historical_source_reference=snapshot.household_load_forecast.forecast_id,
            method_version=ADAPTER_METHOD_VERSION,
        )
        domain_snapshot = DomainPlanningInputSnapshot(
            snapshot_id=snapshot.snapshot_id,
            captured_at=snapshot.captured_at,
            horizon_end=snapshot.horizon_end,
            strategy=PlannerStrategy(
                strategy_version=1,
                source_profile_version=1,
                mapping_version=f"observer:{snapshot.strategy_id}",
                optimisation_profile=OptimisationProfile.BALANCED,
                objectives=(),
            ),
            household_state=HouseholdState(measured_at=snapshot.captured_at, phases=()),
            forecasts=ForecastSet(series=()),
            runtime_state=RuntimePressureState.NORMAL,
            versions=PlanningInputVersions(
                capability_mapping=(
                    snapshot.capability_snapshot_set.mapping_version
                    if snapshot.capability_snapshot_set is not None
                    else 1
                ),
                user_rules=1,
                commitments=1,
                household_state=1,
                forecasts=1,
            ),
            replan_reasons=("v2-reference-observer",),
            current_storage_states=(domain_storage,),
            pv_energy_timeline=domain_pv,
            household_load_forecast=domain_load,
        )
        family = {
            "reserve_first": CandidateFamily.RESERVE_FIRST,
            "pv_charge_only": CandidateFamily.PV_FIRST,
            "cost_first": CandidateFamily.COST_FIRST,
        }.get(candidate_family)
        if family is None:
            raise ValueError(f"unsupported Candidate family {candidate_family}")
        domain_path = DomainEnergyPath(
            path_id=path.path_id,
            snapshot_id=snapshot.snapshot_id,
            family=family,
            horizon_start=snapshot.captured_at,
            horizon_end=snapshot.horizon_end,
            segments=path.segments,
            projected_states=(),
            opportunity_ids=(),
            constraint_ids=(),
            capability_ids=tuple(
                dict.fromkeys(segment.capability_id for segment in path.segments)
            ),
            strategy_version=1,
            mapping_version=(
                snapshot.capability_snapshot_set.mapping_version
                if snapshot.capability_snapshot_set is not None
                else 1
            ),
            assumptions=(ADAPTER_METHOD_VERSION,),
            confidence=(
                path.capability_confidence
                if path.capability_confidence is not None
                else 1.0
            ),
        )
        return domain_snapshot, domain_path, domain_storage

    @staticmethod
    def _normalise_pv_intervals(
        snapshot: PlanningInputSnapshot,
        target_intervals: tuple[EnergyTariffInterval, ...],
    ) -> tuple[DomainPVInterval, ...]:
        assert snapshot.pv_energy_timeline is not None
        result: list[DomainPVInterval] = []
        for target in target_intervals:
            starts_at = target.starts_at
            ends_at = target.ends_at
            sources = tuple(
                item
                for item in snapshot.pv_energy_timeline.intervals
                if item.starts_at < ends_at and item.ends_at > starts_at
            )
            energy_wh, confidence = CanonicalReferenceObserver._allocate_energy(
                starts_at=starts_at,
                ends_at=ends_at,
                sources=tuple(
                    (
                        item.starts_at,
                        item.ends_at,
                        item.pv_energy_wh,
                        item.confidence,
                    )
                    for item in sources
                ),
            )
            evidence_types = {
                PVEnergyEvidenceType(item.evidence_type.lower()) for item in sources
            }
            evidence_type = (
                next(iter(evidence_types))
                if len(evidence_types) == 1
                else PVEnergyEvidenceType.MIXED
            )
            result.append(
                DomainPVInterval(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    energy_wh=energy_wh,
                    evidence_type=evidence_type,
                    confidence=confidence,
                    evidence_ids=tuple(
                        dict.fromkeys(
                            evidence_id
                            for item in sources
                            for evidence_id in (
                                *item.actual_evidence_ids,
                                *item.forecast_evidence_ids,
                            )
                        )
                    ),
                    method_version=ADAPTER_METHOD_VERSION,
                )
            )
        return tuple(result)

    @staticmethod
    def _normalise_load_intervals(
        snapshot: PlanningInputSnapshot,
        target_intervals: tuple[EnergyTariffInterval, ...],
    ) -> tuple[DomainLoadInterval, ...]:
        assert snapshot.household_load_forecast is not None
        result: list[DomainLoadInterval] = []
        for target in target_intervals:
            starts_at = target.starts_at
            ends_at = target.ends_at
            sources = tuple(
                item
                for item in snapshot.household_load_forecast.intervals
                if item.starts_at < ends_at and item.ends_at > starts_at
            )
            energy_wh, confidence = CanonicalReferenceObserver._allocate_energy(
                starts_at=starts_at,
                ends_at=ends_at,
                sources=tuple(
                    (
                        item.starts_at,
                        item.ends_at,
                        item.expected_energy_wh,
                        item.confidence,
                    )
                    for item in sources
                ),
            )
            result.append(
                DomainLoadInterval(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    expected_energy_wh=energy_wh,
                    confidence=confidence,
                )
            )
        return tuple(result)

    @staticmethod
    def _allocate_energy(
        *,
        starts_at: datetime,
        ends_at: datetime,
        sources: tuple[tuple[datetime, datetime, float, float], ...],
    ) -> tuple[float, float]:
        target_seconds = (ends_at - starts_at).total_seconds()
        allocations: list[tuple[tuple[datetime, datetime, float, float], float]] = []
        for source in sources:
            source_start, source_end, _, _ = source
            overlap_seconds = (
                min(source_end, ends_at)
                - max(source_start, starts_at)
            ).total_seconds()
            allocations.append((source, overlap_seconds))
        if (
            not allocations
            or abs(sum(seconds for _, seconds in allocations) - target_seconds) > 1e-6
        ):
            raise ValueError(
                "Reference PV and load evidence must fully cover every tariff interval."
            )
        energy_wh = sum(
            source[2]
            * seconds
            / (source[1] - source[0]).total_seconds()
            for source, seconds in allocations
        )
        confidence = min(source[3] for source, _ in allocations)
        return energy_wh, confidence
