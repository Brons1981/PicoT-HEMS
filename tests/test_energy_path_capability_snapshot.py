from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.candidate import CandidateFamily
from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import (
    EnergyPath,
    PathSegment,
    PhaseProjection,
    ProjectedEnergyState,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.household_state import Phase

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _capability() -> LogicalCapabilitySnapshot:
    return LogicalCapabilitySnapshot(
        capability_id="battery-control",
        execution_scope_id="battery-main",
        supported_primitives=(
            ExecutionPrimitive.STANDBY,
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.DISCHARGE_AT_POWER,
        ),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=BASE,
        confidence=0.98,
        source_mapping_id="mapping-battery-1",
        adapter_contract_version="1.0",
        flow_directions=(
            EnergyFlowDirection.CHARGE,
            EnergyFlowDirection.DISCHARGE,
        ),
        minimum_power_w=100.0,
        maximum_power_w=2400.0,
        minimum_soc=0.10,
        maximum_soc=1.0,
        phases=(Phase.L1,),
    )


def test_capability_snapshot_preserves_logical_limits_and_mapping() -> None:
    capability = _capability()
    snapshot = CapabilitySnapshotSet(
        snapshot_id="snapshot-1",
        mapping_version=3,
        captured_at=BASE,
        capabilities=(capability,),
    )

    assert snapshot.mapping_version == 3
    assert snapshot.capabilities[0].maximum_power_w == 2400.0
    assert snapshot.capabilities[0].source_mapping_id == "mapping-battery-1"


def test_capability_snapshot_rejects_future_freshness() -> None:
    capability = _capability()

    with pytest.raises(ValueError, match="must not be in the future"):
        CapabilitySnapshotSet(
            snapshot_id="snapshot-1",
            mapping_version=1,
            captured_at=BASE - timedelta(seconds=1),
            capabilities=(capability,),
        )


def test_power_primitive_requires_requested_power() -> None:
    with pytest.raises(ValueError, match="require requested power"):
        PathSegment(
            segment_id="segment-1",
            order=1,
            execution_scope_id="battery-main",
            starts_at=BASE,
            ends_at=BASE + timedelta(hours=1),
            primitive=ExecutionPrimitive.CHARGE_AT_POWER,
            capability_id="battery-control",
            purpose="Use forecast PV surplus",
            evidence_ids=("opportunity-pv-1",),
            charge_source_policy=ChargeSourcePolicy.PV_ONLY,
        )


def test_energy_path_is_complete_traceable_and_immutable() -> None:
    segment = PathSegment(
        segment_id="segment-1",
        order=1,
        execution_scope_id="battery-main",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=1),
        primitive=ExecutionPrimitive.CHARGE_AT_POWER,
        capability_id="battery-control",
        purpose="Use forecast PV surplus",
        evidence_ids=("opportunity-pv-1",),
        requested_power_w=1200.0,
        charge_source_policy=ChargeSourcePolicy.PV_ONLY,
    )
    state = ProjectedEnergyState(
        at=BASE + timedelta(hours=1),
        confidence=0.90,
        household_import_w=0.0,
        pv_production_w=2800.0,
        household_demand_w=1200.0,
        battery_soc=0.62,
        phase_loads=(PhaseProjection(phase=Phase.L1, current_a=8.0),),
    )

    path = EnergyPath(
        path_id="path-pv-first-1",
        snapshot_id="snapshot-1",
        family=CandidateFamily.PV_FIRST,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
        segments=(segment,),
        projected_states=(state,),
        opportunity_ids=("opportunity-pv-1",),
        constraint_ids=(),
        capability_ids=("battery-control",),
        strategy_version=2,
        mapping_version=3,
        assumptions=("PV forecast remains within recorded confidence.",),
        confidence=0.90,
    )

    assert path.segments[0].primitive is ExecutionPrimitive.CHARGE_AT_POWER
    assert path.segments[0].charge_source_policy is ChargeSourcePolicy.PV_ONLY
    assert path.mapping_version == 3
    with pytest.raises(AttributeError):
        path.confidence = 0.5  # type: ignore[misc]


def test_energy_path_rejects_overlapping_segments_for_one_scope() -> None:
    first = PathSegment(
        segment_id="segment-1",
        order=1,
        execution_scope_id="battery-main",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=2),
        primitive=ExecutionPrimitive.STANDBY,
        capability_id="battery-control",
        purpose="Hold reserve",
        evidence_ids=("constraint-reserve-1",),
    )
    second = PathSegment(
        segment_id="segment-2",
        order=2,
        execution_scope_id="battery-main",
        starts_at=BASE + timedelta(hours=1),
        ends_at=BASE + timedelta(hours=3),
        primitive=ExecutionPrimitive.STANDBY,
        capability_id="battery-control",
        purpose="Hold reserve",
        evidence_ids=("constraint-reserve-1",),
    )

    with pytest.raises(ValueError, match="may not overlap"):
        EnergyPath(
            path_id="path-overlap",
            snapshot_id="snapshot-1",
            family=CandidateFamily.RESERVE_FIRST,
            horizon_start=BASE,
            horizon_end=BASE + timedelta(hours=4),
            segments=(first, second),
            projected_states=(),
            opportunity_ids=(),
            constraint_ids=("constraint-reserve-1",),
            capability_ids=("battery-control",),
            strategy_version=1,
            mapping_version=1,
            assumptions=(),
            confidence=0.8,
        )
