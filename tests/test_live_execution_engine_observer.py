from __future__ import annotations

from datetime import UTC, datetime

from picot.addon.live_execution_engine_observer import observe_execution_engine
from picot.domain.capability_snapshot import CapabilitySnapshotSet
from picot.domain.execution_plan import ExecutionPlanSet

BASE = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)


def _empty_plan_set() -> ExecutionPlanSet:
    return ExecutionPlanSet(
        plan_set_id="plan-set-empty",
        schema_version=1,
        snapshot_id="snapshot-1",
        strategy_version=1,
        evaluation_id="evaluation-1",
        winning_candidate_id="candidate-1",
        winning_energy_path_id="path-1",
        created_at=BASE,
        plans=(),
        implementation_version="execution-plan-builder-v1",
    )


def _empty_capabilities() -> CapabilitySnapshotSet:
    return CapabilitySnapshotSet(
        snapshot_id="snapshot-1",
        mapping_version=1,
        captured_at=BASE,
        capabilities=(),
    )


def test_empty_baseline_plan_set_is_evaluated_without_requests_or_records() -> None:
    fields = observe_execution_engine(
        _empty_plan_set(),
        _empty_capabilities(),
        now=BASE,
    )

    assert fields["execution_engine_observed"] is True
    assert fields["execution_engine_status"] == "evaluated"
    assert fields["execution_fallback_policy_resolved"] is True
    assert fields["execution_request_count"] == 0
    assert fields["execution_record_count"] == 0


def test_missing_plan_set_is_not_executed() -> None:
    fields = observe_execution_engine(None, _empty_capabilities(), now=BASE)

    assert fields["execution_engine_observed"] is False
    assert fields["execution_engine_status"] == "plan_set_unavailable"
