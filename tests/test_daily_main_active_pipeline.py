"""Active pipeline selection and durable reuse, using bounded synthetic inputs."""

from dataclasses import replace
from zoneinfo import ZoneInfo

from test_daily_main_charge_selection import snapshot_for_main
from test_daily_main_charge_windows import inputs

from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def setup(tmp_path, monkeypatch):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    runtime = MarketDailyPlannerRuntime(inputs()["conversion_model"])

    def forbidden(*args, **kwargs):
        raise AssertionError("daily input must never invoke the legacy market generator")

    monkeypatch.setattr(runtime, "generate", forbidden)
    pipeline = CanonicalPipeline(market_daily_planner_runtime=runtime, commitment_store=store)
    source = snapshot_for_main()

    def recover(snapshot=source):
        return _restore_daily_charge_context(snapshot, store, local_timezone=ZoneInfo("UTC"))

    return store, pipeline, recover


def test_first_selection_activates_exact_plan_and_repeated_poll_does_not_reprice(
    tmp_path, monkeypatch
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    assert first.execution_plan_set.plans, first.evaluation.reason
    plan = first.execution_plan_set.plans[0]
    saved = store.load_active_daily_main_plan(plan.execution_scope_id)
    assert saved.plan_id == plan.plan_id
    assert first.evaluation.financial_equivalence_margin_eur == 0
    assert first.candidate_set.candidates[0].pv_forecast_basis == "mean-lower-central"
    assert first.primitive_boundary.pv_charge_progress is None
    before = (tmp_path / "plans.json").read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("a bound daily goal must not rediscover price windows")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", forbidden)
    second = pipeline.run(planning_input=recover())
    assert second.execution_plan_set.plans[0] == plan
    assert second.candidate_set.candidates == ()
    assert second.evaluation.status == "plan_retained"
    assert (tmp_path / "plans.json").read_bytes() == before
    assert all(a.completed_at is None for a in store.load_daily_assignments())


def test_missing_data_requests_guarded_nom_without_erasing_the_main_plan(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    plan = first.execution_plan_set.plans[0]
    before = (tmp_path / "plans.json").read_bytes()
    missing = replace(recover(), pv_energy_timeline=None)
    fallback = pipeline.run(planning_input=missing, control_change_allowed=True)
    assert fallback.execution_record.status == "live_fallback_ready"
    assert fallback.primitive_boundary.planned_primitive.value == "balance_bidirectional"
    assert "storage_mode_capability_evidence_unavailable" in fallback.primitive_boundary.blockers
    assert store.load_active_daily_main_plan(plan.execution_scope_id).plan_id == plan.plan_id
    assert (tmp_path / "plans.json").read_bytes() == before


def test_corrupt_active_pointer_is_blocked_without_guessing_a_plan(tmp_path, monkeypatch):
    import json

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    assert first.execution_plan_set.plans
    payload = json.loads((tmp_path / "plans.json").read_text())
    payload["active_daily_main_assignments"] = {"battery": "unknown"}
    (tmp_path / "plans.json").write_text(json.dumps(payload))
    source = recover()
    assert source.daily_charge_context.status == "blocked"
    run = pipeline.run(planning_input=source)
    assert run.execution_record.status == "observer_fallback_ready"
    assert run.execution_plan_set.plans == ()


def with_mode(snapshot, primitive, *, current_mode="Standby"):
    from picot.v2.storage_mode_provenance import (
        initial_storage_mode_provenance,
        record_planner_mode_application,
    )
    from picot.v2.zendure_mode_capabilities import (
        ZendureModeCapabilityEvidence,
        ZendureModeMapping,
    )

    provenance = initial_storage_mode_provenance(
        observed_vendor_mode=current_mode,
        observed_at=snapshot.captured_at,
    )
    provenance = record_planner_mode_application(
        provenance,
        vendor_mode=current_mode,
        applied_at=snapshot.captured_at,
        application_id="test-mode-observation",
    )
    return replace(
        snapshot,
        storage_mode_control_provenance=provenance,
        storage_mode_capability_evidence=ZendureModeCapabilityEvidence(
            captured_at=snapshot.captured_at,
            source_entity_id="input_select.test_mode",
            capability_id="battery-capability",
            execution_scope_id="battery",
            current_vendor_mode=current_mode,
            status="available",
            unavailable_reason=None,
            usable_vendor_modes=("Standby", "Test active"),
            excluded_dynamic_vendor_modes=(),
            mappings=(
                ZendureModeMapping(
                    "Test active",
                    (primitive,),
                    "integration_configured_maximum",
                ),
            ),
        ),
    )


def test_nom_fallback_uses_generic_dispatch_and_obeys_manual_block(tmp_path, monkeypatch):
    from picot.domain.execution_primitive import ExecutionPrimitive
    from picot.v2.canonical_execution_runtime import (
        CanonicalDispatchOutcome,
        CanonicalExecutionRuntime,
    )

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = with_mode(recover(), ExecutionPrimitive.BALANCE_BIDIRECTIONAL)
    source = replace(source, pv_energy_timeline=None)
    requests = []

    def dispatch(request, mapping):
        requests.append(request)
        return CanonicalDispatchOutcome("dispatched", "test-command")

    runtime = CanonicalExecutionRuntime(dispatch, commitment_store=store)
    run = runtime.apply(pipeline.run(planning_input=source, control_change_allowed=True))
    assert run.vendor_result.status == "dispatched"
    assert requests[0].primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    assert requests[0].plan_id == "guarded-nom:battery"
    assert store.load_active_daily_main_plan("battery") is None
    assert runtime.advance_committed_boundary(source, execution_enabled=True).status == "blocked"
    blocked = replace(
        source,
        storage_mode_control_provenance=replace(
            source.storage_mode_control_provenance,
            manual_override_active=True,
            status="manual_override",
        ),
    )
    runtime.apply(pipeline.run(planning_input=blocked, control_change_allowed=True))
    assert len(requests) == 1


def test_clock_confirmation_completes_only_fresh_owned_soc_and_survives_restart(
    tmp_path, monkeypatch
):
    from datetime import timedelta

    from picot.v2.canonical_execution_runtime import CanonicalExecutionRuntime

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover())
    saved = store.load_active_daily_main_plan("battery")
    main = next(s for s in saved.segments if s.main_assignment_id is not None)
    source = selected.planning_input
    at = main.starts_at + timedelta(seconds=1)
    source = replace(
        source,
        daily_charge_context=None,
        captured_at=at,
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
    )
    source = with_mode(source, main.primitive, current_mode="Test active")
    # The value predates the first mode confirmation and cannot prove execution.
    source = replace(
        source,
        current_storage_states=(
            replace(
                source.current_storage_states[0],
                current_soc=1.0,
                measured_at=at - timedelta(seconds=1),
            ),
        ),
    )
    runtime = CanonicalExecutionRuntime(
        lambda *args: (_ for _ in ()).throw(AssertionError("already active")),
        commitment_store=store,
    )
    outcome = runtime.advance_committed_boundary(recover(source), execution_enabled=True)
    assert outcome.status == "already_active"
    assert all(a.completed_at is None for a in store.load_daily_assignments())
    at += timedelta(seconds=1)
    source = replace(
        source,
        captured_at=at,
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
        storage_mode_capability_evidence=replace(
            source.storage_mode_capability_evidence, captured_at=at
        ),
        current_storage_states=(
            replace(
                source.current_storage_states[0],
                measured_at=at,
            ),
        ),
    )
    runtime.advance_committed_boundary(recover(source), execution_enabled=True)
    completed = next(
        a for a in store.load_daily_assignments() if a.assignment_id == main.main_assignment_id
    )
    assert completed.completed_at == at
    assert saved.plan_id in completed.completion_evidence_id
    assert main.segment_id in completed.completion_evidence_id
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    assert (
        next(
            a
            for a in restarted.load_daily_assignments()
            if a.assignment_id == completed.assignment_id
        )
        == completed
    )


def test_clock_dispatch_keeps_exact_segment_identity_and_power(tmp_path, monkeypatch):
    from picot.v2.canonical_execution_runtime import (
        CanonicalDispatchOutcome,
        CanonicalExecutionRuntime,
    )

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover())
    plan = store.load_active_daily_main_plan("battery")
    segment = next(s for s in plan.segments if s.main_assignment_id is not None)
    source = replace(
        selected.planning_input, daily_charge_context=None, captured_at=segment.starts_at
    )
    source = with_mode(source, segment.primitive)
    requests = []

    def dispatch(request, mapping):
        requests.append(request)
        return CanonicalDispatchOutcome("dispatched", "test-command")

    runtime = CanonicalExecutionRuntime(dispatch, commitment_store=store)
    outcome = runtime.advance_committed_boundary(recover(source), execution_enabled=True)
    assert outcome.status == "dispatched"
    assert requests[0].segment_id == segment.segment_id
    assert requests[0].plan_id == plan.plan_id
    assert requests[0].requested_power_w == segment.requested_power_w
    assert all(a.completed_at is None for a in store.load_daily_assignments())
