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
from picot.domain.execution import CommandValidationOutcome
from picot.domain.execution_plan import (
    ExecutionPlan,
    ExecutionPlanLifecycle,
    ExecutionPlanSegment,
    ExecutionPlanSet,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.execution.execution_engine import ExecutionEngine

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _plan_set(*, starts_at: datetime | None = None) -> ExecutionPlanSet:
    segment_start = starts_at or BASE
    segment = ExecutionPlanSegment(
        segment_id="execution-segment-1",
        source_path_segment_id="path-segment-1",
        order=1,
        starts_at=segment_start,
        ends_at=segment_start + timedelta(hours=1),
        primitive=ExecutionPrimitive.CHARGE_AT_POWER,
        capability_id="battery-charge",
        purpose="Use PV surplus",
        evidence_ids=("opportunity-pv-1",),
        requested_power_w=1200.0,
    )
    plan = ExecutionPlan(
        plan_id="plan-battery-main",
        schema_version=1,
        revision=1,
        created_at=BASE,
        valid_from=BASE,
        valid_until=BASE + timedelta(hours=24),
        snapshot_id="snapshot-1",
        strategy_version=2,
        evaluation_id="evaluation-1",
        winning_candidate_id="candidate-1",
        winning_energy_path_id="path-1",
        execution_scope_id="battery-main",
        mapping_version=3,
        lifecycle=ExecutionPlanLifecycle.PROPOSED,
        fallback_policy_id="fallback-safe-v1",
        segments=(segment,),
    )
    return ExecutionPlanSet(
        plan_set_id="plan-set-1",
        schema_version=1,
        snapshot_id="snapshot-1",
        strategy_version=2,
        evaluation_id="evaluation-1",
        winning_candidate_id="candidate-1",
        winning_energy_path_id="path-1",
        created_at=BASE,
        plans=(plan,),
        implementation_version="execution-plan-builder-v1",
    )


def _capabilities(
    *,
    availability: CapabilityAvailability = CapabilityAvailability.AVAILABLE,
) -> CapabilitySnapshotSet:
    capability = LogicalCapabilitySnapshot(
        capability_id="battery-charge",
        execution_scope_id="battery-main",
        supported_primitives=(ExecutionPrimitive.CHARGE_AT_POWER,),
        availability=availability,
        health=CapabilityHealth.HEALTHY,
        fresh_at=BASE,
        confidence=0.98,
        source_mapping_id="mapping-battery-1",
        adapter_contract_version="1.0",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
        minimum_power_w=100.0,
        maximum_power_w=2400.0,
    )
    return CapabilitySnapshotSet(
        snapshot_id="snapshot-1",
        mapping_version=3,
        captured_at=BASE,
        capabilities=(capability,),
    )


def test_execution_engine_emits_request_for_due_supported_segment() -> None:
    result = ExecutionEngine().execute_due(
        _plan_set(),
        _capabilities(),
        now=BASE + timedelta(minutes=30),
    )

    assert len(result.requests) == 1
    assert len(result.records) == 1
    assert result.requests[0].primitive is ExecutionPrimitive.CHARGE_AT_POWER
    assert result.requests[0].requested_power_w == 1200.0
    assert result.records[0].outcome is CommandValidationOutcome.APPROVED
    assert result.records[0].request_id == result.requests[0].request_id


def test_execution_engine_returns_replan_when_capability_is_unavailable() -> None:
    result = ExecutionEngine().execute_due(
        _plan_set(),
        _capabilities(
            availability=CapabilityAvailability.TEMPORARILY_UNAVAILABLE,
        ),
        now=BASE + timedelta(minutes=30),
    )

    assert result.requests == ()
    assert result.records[0].outcome is CommandValidationOutcome.REPLAN_REQUIRED


def test_execution_engine_ignores_segments_that_are_not_due() -> None:
    result = ExecutionEngine().execute_due(
        _plan_set(starts_at=BASE + timedelta(hours=2)),
        _capabilities(),
        now=BASE + timedelta(minutes=30),
    )

    assert result.requests == ()
    assert result.records == ()


def test_execution_engine_is_deterministic_for_identical_inputs() -> None:
    now = BASE + timedelta(minutes=30)
    first = ExecutionEngine().execute_due(_plan_set(), _capabilities(), now=now)
    second = ExecutionEngine().execute_due(_plan_set(), _capabilities(), now=now)

    assert first == second
