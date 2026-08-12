from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import (
    EvidenceReference,
    Opportunity,
    OpportunityKind,
    OpportunityLifecycle,
    OpportunitySet,
)
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalancePoint,
)
from picot.domain.pv_only_storage_feasibility import (
    PVOnlyEnergyFeasibilityOutcome,
    PVOnlyStorageEnergyFeasibility,
)
from picot.domain.storage_energy_requirement import StorageEnergyRequirement, StorageRequirementReason
from picot.domain.storage_technical_recoverability import StorageTechnicalRecoverability
from picot.planner.candidate_engine import CandidateEngine

BASE = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
PROTECTION_START = BASE + timedelta(hours=6)
PROTECTED_THROUGH = BASE + timedelta(hours=10)


def _snapshot() -> PlanningInputSnapshot:
    return PlanningInputSnapshot(
        snapshot_id="snapshot-grid",
        captured_at=BASE,
        horizon_end=BASE + timedelta(hours=24),
        strategy=PlannerStrategy(
            strategy_version=2,
            source_profile_version=1,
            mapping_version="map-1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=()),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=3,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("test",),
    )


def _opportunities() -> OpportunitySet:
    opportunity = Opportunity(
        opportunity_id="lowest-price-1",
        snapshot_id="snapshot-grid",
        kind=OpportunityKind.LOWEST_PRICE_WINDOW,
        starts_at=BASE + timedelta(hours=1),
        ends_at=BASE + timedelta(hours=2),
        confidence=0.9,
        lifecycle=OpportunityLifecycle.DETECTED,
        evidence=(EvidenceReference(source_id="price-forecast-1", point_indexes=(0,)),),
    )
    return OpportunitySet(snapshot_id="snapshot-grid", opportunities=(opportunity,))


def _capabilities(*, maximum_power_w: float = 1500.0) -> CapabilitySnapshotSet:
    capability = LogicalCapabilitySnapshot(
        capability_id="battery-charge",
        execution_scope_id="battery-main",
        supported_primitives=(ExecutionPrimitive.CHARGE_AT_POWER,),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=BASE,
        confidence=0.95,
        source_mapping_id="mapping-1",
        adapter_contract_version="1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
        minimum_power_w=100.0,
        maximum_power_w=maximum_power_w,
        power_step_w=100.0,
    )
    return CapabilitySnapshotSet(
        snapshot_id="snapshot-grid",
        mapping_version=3,
        captured_at=BASE,
        capabilities=(capability,),
    )


def _balance() -> ProjectedHouseholdEnergyBalance:
    return ProjectedHouseholdEnergyBalance(
        balance_id="balance-1",
        created_at=BASE,
        horizon_end=BASE + timedelta(hours=24),
        execution_scope_id="battery-main",
        starting_storage_energy_wh=6000.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=BASE + timedelta(hours=24),
                projected_storage_energy_wh=5000.0,
                cumulative_pv_energy_wh=1000.0,
                cumulative_household_load_wh=2000.0,
            ),
        ),
        confidence=0.8,
        evidence_ids=("balance-source",),
    )


def _limit() -> EffectiveStorageLimit:
    return EffectiveStorageLimit(
        limit_id="limit-1",
        execution_scope_id="battery-main",
        max_soc=0.95,
        usable_capacity_wh=8000.0,
        confidence=1.0,
        evidence_ids=("config:max-soc",),
        method_version="effective-storage-limit-v1",
    )


def _requirement() -> StorageEnergyRequirement:
    return StorageEnergyRequirement(
        requirement_id="storage:req:evening",
        protection_starts_at=PROTECTION_START,
        protected_through=PROTECTED_THROUGH,
        required_energy_wh=7000.0,
        required_soc_percent=None,
        reason=StorageRequirementReason.HOUSEHOLD_DEMAND,
        confidence=0.85,
        evidence_ids=("balance-1", "limit-1"),
    )


def _feasibility(*, sufficient: bool = False) -> PVOnlyStorageEnergyFeasibility:
    return PVOnlyStorageEnergyFeasibility(
        requirement_id="storage:req:evening",
        outcome=(
            PVOnlyEnergyFeasibilityOutcome.ENERGY_SUFFICIENT
            if sufficient
            else PVOnlyEnergyFeasibilityOutcome.ENERGY_SHORTFALL
        ),
        projected_energy_at_protection_start_wh=6000.0,
        protection_start_shortfall_wh=0.0 if sufficient else 1000.0,
        household_path_shortfall_wh=0.0,
        confidence=0.8,
        evidence_ids=("storage:req:evening", "balance-1", "pv-feasibility-v2"),
    )


def _recoverability(*, extra_energy_wh: float = 1000.0, recoverable: bool = True) -> StorageTechnicalRecoverability:
    return StorageTechnicalRecoverability(
        evaluated_at=BASE,
        requirement_id="storage:req:evening",
        capability_id="battery-charge",
        protection_starts_at=PROTECTION_START,
        protected_through=PROTECTED_THROUGH,
        extra_energy_required_wh=extra_energy_wh,
        additional_acquisition_required=extra_energy_wh > 0.0,
        maximum_charge_energy_before_protection_wh=6000.0,
        latest_full_power_charge_start=(
            BASE + timedelta(hours=5) if extra_energy_wh > 0.0 else None
        ),
        technically_recoverable=recoverable,
        confidence=0.82,
        evidence_ids=("storage:req:evening", "battery-charge", "recoverability-v3"),
    )


def _generate(
    *,
    sufficient: bool = False,
    extra_energy_wh: float = 1000.0,
    maximum_power_w: float = 1500.0,
) -> object:
    return CandidateEngine().generate(
        _snapshot(),
        _opportunities(),
        _capabilities(maximum_power_w=maximum_power_w),
        storage_requirement=_requirement(),
        pv_only_feasibility=_feasibility(sufficient=sufficient),
        storage_recoverability=_recoverability(extra_energy_wh=extra_energy_wh),
        projected_balance=_balance(),
        effective_storage_limit=_limit(),
    )


def test_grid_supported_candidate_uses_explicit_source_policy() -> None:
    result = _generate()

    cost_paths = [path for path in result.energy_paths if path.family.value == "cost_first"]
    assert len(cost_paths) == 1
    segment = cost_paths[0].segments[0]
    assert segment.requested_power_w == pytest.approx(1000.0)
    assert segment.charge_source_policy is ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED
    assert "storage:req:evening" in segment.evidence_ids
    assert "balance-1" in segment.evidence_ids
    assert "limit-1" in segment.evidence_ids


def test_grid_candidate_is_not_generated_when_pv_only_is_sufficient() -> None:
    result = _generate(sufficient=True)

    assert all(path.family.value != "cost_first" for path in result.energy_paths)
    assert any("grid supplementation is unnecessary" in item.reason for item in result.exclusions)


def test_grid_candidate_is_rejected_when_price_window_cannot_deliver_target() -> None:
    result = _generate(extra_energy_wh=2000.0, maximum_power_w=1500.0)

    assert all(path.family.value != "cost_first" for path in result.energy_paths)
    assert any("cannot deliver" in item.reason for item in result.exclusions)


def test_storage_candidate_evidence_must_be_supplied_atomically() -> None:
    with pytest.raises(ValueError, match="requires requirement"):
        CandidateEngine().generate(
            _snapshot(),
            _opportunities(),
            _capabilities(),
            storage_requirement=_requirement(),
        )


def test_price_candidate_fails_closed_without_balance_and_limit() -> None:
    result = CandidateEngine().generate(
        _snapshot(),
        _opportunities(),
        _capabilities(),
        storage_requirement=_requirement(),
        pv_only_feasibility=_feasibility(),
        storage_recoverability=_recoverability(),
    )

    assert all(path.family.value != "cost_first" for path in result.energy_paths)
    assert any("projected household balance" in item.reason for item in result.exclusions)