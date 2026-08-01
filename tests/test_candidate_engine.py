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
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.candidate_engine import CandidateEngine

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _snapshot() -> PlanningInputSnapshot:
    forecast = ForecastSeries(
        forecast_id="pv-1",
        kind=ForecastKind.PV_POWER,
        source="test",
        created_at=BASE,
        expires_at=BASE + timedelta(hours=36),
        unit="W",
        points=(
            ForecastPoint(
                starts_at=BASE,
                ends_at=BASE + timedelta(hours=1),
                value=3000.0,
                confidence=0.9,
            ),
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
        forecasts=ForecastSet(series=(forecast,)),
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


def _capabilities(*, available: bool = True) -> CapabilitySnapshotSet:
    capability = LogicalCapabilitySnapshot(
        capability_id="battery-charge",
        execution_scope_id="battery-main",
        supported_primitives=(ExecutionPrimitive.CHARGE_AT_POWER,),
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
        minimum_power_w=100.0,
        maximum_power_w=1500.0,
    )
    return CapabilitySnapshotSet(
        snapshot_id="snapshot-1",
        mapping_version=3,
        captured_at=BASE,
        capabilities=(capability,),
    )


def test_candidate_engine_builds_baseline_and_pv_first_path() -> None:
    result = CandidateEngine().generate(_snapshot(), _opportunities(), _capabilities())

    assert len(result.candidates) == 2
    assert len(result.energy_paths) == 2
    pv_path = result.energy_paths[1]
    assert pv_path.segments[0].requested_power_w == 1500.0
    assert pv_path.opportunity_ids == ("pv-surplus-1",)


def test_candidate_engine_keeps_baseline_and_explains_unavailable_storage() -> None:
    result = CandidateEngine().generate(
        _snapshot(),
        _opportunities(),
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
