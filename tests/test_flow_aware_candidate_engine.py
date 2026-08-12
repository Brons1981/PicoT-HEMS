from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.current_flow_observation import CurrentFlowObservation
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import OpportunitySet
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.planner.flow_aware_candidate_engine import FlowAwareCandidateEngine


NOW = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)


def _snapshot(*, persistent: bool) -> PlanningInputSnapshot:
    observation = CurrentFlowObservation(
        observation_id="flow-1",
        observed_at=NOW,
        grid_export_w=3200.0,
        battery_discharge_w=2400.0,
        pv_power_w=1050.0,
        discharge_while_exporting=True,
        persistent_mismatch=persistent,
        consecutive_samples=3 if persistent else 1,
        required_samples=3,
        evidence_ids=("flow-evidence-1",),
    )
    return PlanningInputSnapshot(
        snapshot_id="snapshot-1",
        captured_at=NOW,
        horizon_end=NOW + timedelta(hours=24),
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="test-v1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=NOW, phases=()),
        forecasts=ForecastSet(series=()),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("test",),
        current_flow_observation=observation,
    )


def _capabilities(*, balance_supported: bool = True) -> CapabilitySnapshotSet:
    primitives = (ExecutionPrimitive.CHARGE_AT_POWER,)
    directions = (EnergyFlowDirection.CHARGE,)
    if balance_supported:
        primitives = (*primitives, ExecutionPrimitive.BALANCE_BIDIRECTIONAL)
        directions = (*directions, EnergyFlowDirection.BIDIRECTIONAL)
    capability = LogicalCapabilitySnapshot(
        capability_id="storage-primary-energy",
        execution_scope_id="storage-primary",
        supported_primitives=primitives,
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=NOW,
        confidence=1.0,
        source_mapping_id="mapping-1",
        adapter_contract_version="v1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=directions,
        maximum_power_w=2400.0,
    )
    return CapabilitySnapshotSet(
        snapshot_id="snapshot-1",
        mapping_version=1,
        captured_at=NOW,
        capabilities=(capability,),
    )


def test_persistent_discharge_while_exporting_replaces_passive_baseline() -> None:
    result = FlowAwareCandidateEngine().generate(
        _snapshot(persistent=True),
        OpportunitySet(snapshot_id="snapshot-1", opportunities=()),
        _capabilities(),
    )

    assert len(result.candidates) == 1
    path = result.energy_paths[0]
    assert "flow-correction:preserve-storage" in path.path_id
    assert len(path.segments) == 1
    assert path.segments[0].primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    assert path.constraint_ids == ("flow-1",)
    assert all("baseline:reserve-first" not in item.path_id for item in result.energy_paths)


def test_non_persistent_mismatch_keeps_passive_baseline() -> None:
    result = FlowAwareCandidateEngine().generate(
        _snapshot(persistent=False),
        OpportunitySet(snapshot_id="snapshot-1", opportunities=()),
        _capabilities(),
    )

    assert len(result.candidates) == 1
    assert result.energy_paths[0].segments == ()
    assert "baseline:reserve-first" in result.energy_paths[0].path_id


def test_persistent_mismatch_fails_closed_without_balance_capability() -> None:
    result = FlowAwareCandidateEngine().generate(
        _snapshot(persistent=True),
        OpportunitySet(snapshot_id="snapshot-1", opportunities=()),
        _capabilities(balance_supported=False),
    )

    assert result.candidates == ()
    assert result.energy_paths == ()
    assert any("BALANCE_BIDIRECTIONAL" in item.reason for item in result.exclusions)
