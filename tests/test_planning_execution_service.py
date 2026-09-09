from dataclasses import replace

import pytest
from test_daily_main_active_pipeline import setup, with_mode
from test_market_execution_guard import history
from test_market_rule_selection import winter_source

from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.pipeline import PlanningInputSuperseded
from picot.v2.planning_execution_service import PlanningExecutionService
from picot.v2.zendure_mode_capabilities import ZendureModeMapping


@pytest.mark.parametrize("poll_interval", [60, 86400])
def test_cooperative_check_services_next_segment_and_aborts_changed_ownership(
    tmp_path, monkeypatch, poll_interval
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover(winter_source(recover()))
    pipeline.run(planning_input=source)
    observed = recover(source)
    now = [observed.captured_at]
    calls = []
    changed = [False]
    service = PlanningExecutionService(
        refresh=lambda: recover(
            replace(
                observed,
                captured_at=now[0],
                daily_charge_context=None,
                capability_snapshot_set=replace(
                    observed.capability_snapshot_set, captured_at=now[0]
                ),
            )
        ),
        advance=lambda current: calls.append(current.captured_at) or changed[0],
        now=lambda: now[0],
        poll_interval_seconds=poll_interval,
        next_check_at=now[0],
    )
    service.checkpoint()
    service.checkpoint()
    assert calls == [now[0]]
    if poll_interval == 86400:
        assert service.next_check_at == min(
            s.ends_at
            for p in observed.daily_charge_context.main_plans
            for s in p.segments
            if s.ends_at > now[0]
        )
    now[0] = service.next_check_at
    changed[0] = True
    with pytest.raises(PlanningInputSuperseded):
        service.checkpoint()
    assert calls[-1] == now[0]


def test_market_cannot_publish_after_execution_invalidates_planning_input(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover(winter_source(recover()))
    pipeline.run(planning_input=source)
    original = store.load_active_daily_main_plan("battery")
    goals = store.load_daily_assignments()
    calls = []

    def checkpoint():
        calls.append(True)
        if len(calls) == 3:
            raise PlanningInputSuperseded("observed stop")

    with pytest.raises(PlanningInputSuperseded):
        pipeline.run(planning_input=recover(source), planning_checkpoint=checkpoint)
    assert store.load_active_daily_main_plan("battery") == original
    assert store.load_daily_assignments() == goals
    assert store.load_market_plan_bindings() == ()


def test_fresh_execution_uses_low_soc_without_rewriting_planning_snapshot(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = with_mode(
        winter_source(recover()), Primitive.DISCHARGE_AT_POWER, current_mode="Export"
    )
    source = replace(
        source,
        storage_mode_capability_evidence=replace(
            source.storage_mode_capability_evidence,
            mappings=(
                ZendureModeMapping(
                    "Export", (Primitive.DISCHARGE_AT_POWER,), "integration_configured_maximum"
                ),
                ZendureModeMapping(
                    "NOM", (Primitive.BALANCE_BIDIRECTIONAL,), "integration_configured_maximum"
                ),
            ),
        ),
    )
    pipeline.run(planning_input=recover(source), control_change_allowed=True)
    old_input = recover(source)
    run = pipeline.run(planning_input=old_input, control_change_allowed=True)
    assert run.execution_record.status == "live_plan_ready", run.evaluation.reason
    binding = store.load_market_plan_bindings()[0]
    plan = store.load_market_bound_plan(binding.assignment_id)
    start = next(s.starts_at for s in plan.segments if s.segment_id in binding.segment_ids)
    fresh = recover(
        replace(
            source,
            captured_at=start,
            daily_charge_context=None,
            capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=start),
            current_storage_states=tuple(
                replace(s, current_soc=0.1, measured_at=start)
                for s in source.current_storage_states
            ),
            storage_mode_capability_evidence=replace(
                source.storage_mode_capability_evidence, captured_at=start, state_changed_at=start
            ),
            market_power_history=history(start, start),
        )
    )
    calls = []
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "stop")
        ),
        commitment_store=store,
    )
    result = runtime.apply_committed(run, fresh)
    assert result.vendor_result.status == "dispatched", result.vendor_result.failure_reason
    assert result.primitive_boundary.mapping_status == "validated"
    assert (
        result.primitive_boundary.source_entity_id
        == fresh.storage_mode_capability_evidence.source_entity_id
    )
    assert calls[0].primitive is Primitive.BALANCE_BIDIRECTIONAL
    assert calls[0].requested_at == fresh.captured_at
    assert result.planning_input == old_input
    assert result.primitive_boundary.planned_primitive is Primitive.BALANCE_BIDIRECTIONAL


def test_live_composition_retries_cancelled_calculation_without_dispatch(tmp_path, monkeypatch):
    from picot.v2.live_runtime import _execute_planning_bundle
    from picot.v2.opportunity_engine import PriceOpportunityConfig
    from picot.v2.planning_input import PlanningInputBundle
    from picot.v2.web_ui import WebViewStore

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover(winter_source(recover()))
    pipeline.run(planning_input=source)
    source = recover(source)
    bundle = PlanningInputBundle(
        snapshot=source,
        evidence=(),
        facts=(),
        assembly_started_at=source.captured_at,
        assembly_finished_at=source.captured_at,
    )

    def checkpoint():
        raise PlanningInputSuperseded("stop observed")

    calls = []
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda *args: calls.append(args), commitment_store=store
    )
    assert not _execute_planning_bundle(
        token="unused",
        canonical_pipeline=pipeline,
        price_config=PriceOpportunityConfig(0, 0, "test:v1"),
        bundle=bundle,
        web_view_store=WebViewStore(),
        canonical_execution_runtime=runtime,
        execution_enabled=True,
        planning_checkpoint=checkpoint,
    )
    assert not calls
    assert store.load_market_plan_bindings() == ()
