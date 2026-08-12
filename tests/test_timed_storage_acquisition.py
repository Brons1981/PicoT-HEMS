from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries, ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import (
    EvidenceReference,
    Opportunity,
    OpportunityKind,
    OpportunityLifecycle,
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
from picot.domain.storage_energy_requirement import (
    StorageEnergyRequirement,
    StorageRequirementReason,
)
from picot.planner.timed_storage_acquisition import TimedStorageAcquisitionAllocator

BASE = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
PROTECTION = BASE + timedelta(hours=4)
PRICES = (
    0.20,
    0.19,
    0.18,
    0.17,
    0.16,
    0.15,
    0.14,
    0.13,
    0.12,
    0.11,
    0.10,
    0.09,
    0.08,
    0.07,
    0.06,
    0.05,
)


def _series() -> ForecastSeries:
    points = tuple(
        ForecastPoint(
            starts_at=BASE + timedelta(minutes=15 * index),
            ends_at=BASE + timedelta(minutes=15 * (index + 1)),
            value=price,
            confidence=1.0,
        )
        for index, price in enumerate(PRICES)
    )
    return ForecastSeries(
        forecast_id="price-1",
        kind=ForecastKind.ENERGY_PRICE,
        source="test-price",
        created_at=BASE,
        expires_at=PROTECTION,
        unit="EUR/kWh",
        points=points,
    )


def _snapshot() -> PlanningInputSnapshot:
    return PlanningInputSnapshot(
        snapshot_id="snapshot-timed",
        captured_at=BASE,
        horizon_end=PROTECTION,
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="map-v1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=(_series(),)),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("test",),
    )


def _opportunity(*, source_id: str = "price-1") -> Opportunity:
    return Opportunity(
        opportunity_id="opp-low",
        snapshot_id="snapshot-timed",
        kind=OpportunityKind.LOWEST_PRICE_WINDOW,
        starts_at=BASE,
        ends_at=PROTECTION,
        confidence=1.0,
        lifecycle=OpportunityLifecycle.DETECTED,
        evidence=(
            EvidenceReference(source_id=source_id, point_indexes=tuple(range(16))),
        ),
    )


def _balance(*, protection_energy_wh: float = 1000.0) -> ProjectedHouseholdEnergyBalance:
    points = []
    for index in range(16):
        at = BASE + timedelta(minutes=15 * (index + 1))
        fraction = (index + 1) / 16.0
        energy = 2000.0 + (protection_energy_wh - 2000.0) * fraction
        points.append(
            ProjectedHouseholdEnergyBalancePoint(
                at=at,
                projected_storage_energy_wh=energy,
                cumulative_pv_energy_wh=0.0,
                cumulative_household_load_wh=2000.0 - energy,
            )
        )
    return ProjectedHouseholdEnergyBalance(
        balance_id="balance-1",
        created_at=BASE,
        horizon_end=PROTECTION,
        execution_scope_id="battery-main",
        starting_storage_energy_wh=2000.0,
        points=tuple(points),
        confidence=1.0,
        evidence_ids=("balance-source",),
    )


def _requirement(*, required_energy_wh: float = 2000.0) -> StorageEnergyRequirement:
    return StorageEnergyRequirement(
        requirement_id="req-1",
        protection_starts_at=PROTECTION,
        protected_through=PROTECTION,
        required_energy_wh=required_energy_wh,
        required_soc_percent=None,
        reason=StorageRequirementReason.HOUSEHOLD_DEMAND,
        confidence=1.0,
        evidence_ids=("balance-1", "limit-1"),
    )


def _limit() -> EffectiveStorageLimit:
    return EffectiveStorageLimit(
        limit_id="limit-1",
        execution_scope_id="battery-main",
        max_soc=1.0,
        usable_capacity_wh=8000.0,
        confidence=1.0,
        evidence_ids=("limit-source",),
        method_version="limit-v1",
    )


def _capability() -> LogicalCapabilitySnapshot:
    return LogicalCapabilitySnapshot(
        capability_id="battery-charge",
        execution_scope_id="battery-main",
        supported_primitives=(ExecutionPrimitive.CHARGE_AT_POWER,),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=BASE,
        confidence=1.0,
        source_mapping_id="mapping-1",
        adapter_contract_version="1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
        minimum_power_w=100.0,
        maximum_power_w=1000.0,
        power_step_w=100.0,
    )


def test_four_hour_opportunity_selects_only_needed_cheapest_hour() -> None:
    allocation = TimedStorageAcquisitionAllocator().allocate(
        snapshot=_snapshot(),
        opportunity=_opportunity(),
        balance=_balance(protection_energy_wh=1000.0),
        requirement=_requirement(required_energy_wh=2000.0),
        storage_limit=_limit(),
        capability=_capability(),
    )

    assert allocation is not None
    assert allocation.scheduled_grid_energy_wh == pytest.approx(1000.0)
    assert [item.point_index for item in allocation.intervals] == [12, 13, 14, 15]
    assert allocation.projected_energy_at_protection_start_wh == pytest.approx(2000.0)


def test_more_baseline_energy_reduces_scheduled_grid_energy() -> None:
    allocation = TimedStorageAcquisitionAllocator().allocate(
        snapshot=_snapshot(),
        opportunity=_opportunity(),
        balance=_balance(protection_energy_wh=1500.0),
        requirement=_requirement(required_energy_wh=2000.0),
        storage_limit=_limit(),
        capability=_capability(),
    )

    assert allocation is not None
    assert allocation.scheduled_grid_energy_wh == pytest.approx(500.0)
    assert [item.point_index for item in allocation.intervals] == [14, 15]


def test_equal_price_tie_prefers_latest_feasible_interval() -> None:
    series = _series()
    equal_points = tuple(
        ForecastPoint(
            starts_at=point.starts_at,
            ends_at=point.ends_at,
            value=0.10,
            confidence=1.0,
        )
        for point in series.points
    )
    equal_series = ForecastSeries(
        forecast_id=series.forecast_id,
        kind=series.kind,
        source=series.source,
        created_at=series.created_at,
        expires_at=series.expires_at,
        unit=series.unit,
        points=equal_points,
    )
    snapshot = _snapshot()
    snapshot = PlanningInputSnapshot(
        snapshot_id=snapshot.snapshot_id,
        captured_at=snapshot.captured_at,
        horizon_end=snapshot.horizon_end,
        strategy=snapshot.strategy,
        household_state=snapshot.household_state,
        forecasts=ForecastSet(series=(equal_series,)),
        runtime_state=snapshot.runtime_state,
        versions=snapshot.versions,
        replan_reasons=snapshot.replan_reasons,
    )

    allocation = TimedStorageAcquisitionAllocator().allocate(
        snapshot=snapshot,
        opportunity=_opportunity(),
        balance=_balance(protection_energy_wh=1750.0),
        requirement=_requirement(required_energy_wh=2000.0),
        storage_limit=_limit(),
        capability=_capability(),
    )

    assert allocation is not None
    assert [item.point_index for item in allocation.intervals] == [15]


def test_unresolved_opportunity_price_evidence_fails_closed() -> None:
    with pytest.raises(ValueError, match="exactly one ENERGY_PRICE"):
        TimedStorageAcquisitionAllocator().allocate(
            snapshot=_snapshot(),
            opportunity=_opportunity(source_id="other-price"),
            balance=_balance(),
            requirement=_requirement(),
            storage_limit=_limit(),
            capability=_capability(),
        )
