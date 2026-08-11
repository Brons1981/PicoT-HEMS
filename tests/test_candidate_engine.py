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
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries, ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import (
    EvidenceReference,
    Opportunity,
    OpportunityKind,
    OpportunityLifecycle,
    OpportunityMetric,
    OpportunityMetricKind,
    OpportunitySet,
)
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.domain.storage_planning import StoragePlanningState
from picot.planner.candidate_engine import CandidateEngine

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _snapshot(*, with_projection: bool = False) -> PlanningInputSnapshot:
    series: list[ForecastSeries] = [
        ForecastSeries(
            forecast_id="pv-1",
            kind=ForecastKind.PV_POWER,
            source="test",
            created_at=BASE,
            expires_at=BASE + timedelta(hours=36),
            unit="W",
            points=(
                ForecastPoint(
                    starts_at=BASE,
                    ends_at=BASE + timedelta(hours=3),
                    value=3000.0,
                    confidence=0.9,
                ),
            ),
        )
    ]
    storage_states = ()
    if with_projection:
        series.append(
            ForecastSeries(
                forecast_id="load-1",
                kind=ForecastKind.HOUSEHOLD_LOAD,
                source="test",
                created_at=BASE,
                expires_at=BASE + timedelta(hours=36),
                unit="W",
                points=(
                    ForecastPoint(
                        starts_at=BASE,
                        ends_at=BASE + timedelta(hours=3),
                        value=1000.0,
                        confidence=0.85,
                    ),
                ),
            )
        )
        storage_states = (
            StoragePlanningState(
                capability_id="battery-charge",
                current_soc=0.64,
                usable_capacity_wh=8000.0,
                measured_at=BASE,
                confidence=0.98,
                source_version="test-v1",
                charge_efficiency=1.0,
            ),
        )

    return PlanningInputSnapshot(
        snapshot_id="snapshot-1",
        captured_at=BASE,
        horizon_end=BASE + timedelta(hours=36),
        strategy=PlannerStrategy(
            strategy_version=2,
            source_profile_version=1,
            mapping_version="map-1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=tuple(series)),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=3,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("test",),
        storage_states=storage_states,
    )


def _pv_opportunities() -> OpportunitySet:
    opportunity = Opportunity(
        opportunity_id="pv-surplus-1",
        snapshot_id="snapshot-1",
        kind=OpportunityKind.PV_SURPLUS_WINDOW,
        starts_at=BASE + timedelta(hours=1),
        ends_at=BASE + timedelta(hours=2),
        confidence=0.88,
        lifecycle=OpportunityLifecycle.DETECTED,
        evidence=(EvidenceReference(source_id="pv-1", point_indexes=(0,)),),
        metrics=(
            OpportunityMetric(
                kind=OpportunityMetricKind.MINIMUM_EXPECTED_POWER_W,
                value=1800.0,
            ),
        ),
    )
    return OpportunitySet(snapshot_id="snapshot-1", opportunities=(opportunity,))


def _price_opportunities() -> OpportunitySet:
    opportunity = Opportunity(
        opportunity_id="cheap-1",
        snapshot_id="snapshot-1",
        kind=OpportunityKind.LOWEST_PRICE_WINDOW,
        starts_at=BASE + timedelta(hours=1),
        ends_at=BASE + timedelta(hours=2),
        confidence=0.99,
        lifecycle=OpportunityLifecycle.DETECTED,
        evidence=(EvidenceReference(source_id="price-1", point_indexes=(0,)),),
    )
    return OpportunitySet(snapshot_id="snapshot-1", opportunities=(opportunity,))


def _capabilities(*, available: bool = True) -> CapabilitySnapshotSet:
    capability = LogicalCapabilitySnapshot(
        capability_id="battery-charge",
        execution_scope_id="battery-main",
        supported_primitives=(ExecutionPrimitive.BALANCE_CHARGE_ONLY,),
        availability=(
            CapabilityAvailability.AVAILABLE
            if available
            else CapabilityAvailability.TEMPORARILY_UNAVAILABLE
        ),
        health=CapabilityHealth.HEALTHY,
        fresh_at=BASE,
        confidence=0.95,
        source_mapping_id="mapping-1",
        adapter_contract_version="1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
        maximum_power_w=2400.0,
        maximum_soc=0.95,
    )
    return CapabilitySnapshotSet(
        snapshot_id="snapshot-1",
        mapping_version=3,
        captured_at=BASE,
        capabilities=(capability,),
    )


def test_candidate_engine_builds_balance_pv_first_path_without_commanded_power() -> None:
    result = CandidateEngine().generate(_snapshot(), _pv_opportunities(), _capabilities())

    assert len(result.candidates) == 2
    pv_path = result.energy_paths[1]
    assert pv_path.segments[0].primitive is ExecutionPrimitive.BALANCE_CHARGE_ONLY
    assert pv_path.segments[0].requested_power_w is None
    assert pv_path.opportunity_ids == ("pv-surplus-1",)


def test_candidate_engine_builds_cost_first_balance_candidate_without_pv_projection() -> None:
    result = CandidateEngine().generate(_snapshot(), _price_opportunities(), _capabilities())

    assert len(result.candidates) == 2
    cost_path = result.energy_paths[1]
    assert cost_path.family.value == "cost_first"
    assert cost_path.segments[0].primitive is ExecutionPrimitive.BALANCE_CHARGE_ONLY
    assert cost_path.segments[0].requested_power_w is None
    assert cost_path.projected_states == ()
    assert "projection unavailable" in cost_path.assumptions[1].lower()


def test_candidate_engine_projects_nom_soc_from_pv_surplus() -> None:
    result = CandidateEngine().generate(
        _snapshot(with_projection=True),
        _price_opportunities(),
        _capabilities(),
    )

    cost_path = result.energy_paths[1]
    assert len(cost_path.projected_states) == 2
    assert cost_path.projected_states[0].battery_soc == pytest.approx(0.64)
    assert cost_path.projected_states[-1].battery_soc == pytest.approx(0.89)
    assert cost_path.segments[0].requested_power_w is None


def test_candidate_engine_keeps_baseline_and_explains_unavailable_storage() -> None:
    result = CandidateEngine().generate(
        _snapshot(),
        _pv_opportunities(),
        _capabilities(available=False),
    )

    assert len(result.candidates) == 1
    assert result.energy_paths[0].family.value == "reserve_first"
    assert result.exclusions[0].source_ids == (
        "pv-surplus-1",
        "battery-charge",
    )


def test_candidate_engine_rejects_atomic_snapshot_mismatch() -> None:
    mismatched = OpportunitySet(snapshot_id="other", opportunities=())

    with pytest.raises(ValueError, match="Opportunity Set must match"):
        CandidateEngine().generate(_snapshot(), mismatched, _capabilities())
