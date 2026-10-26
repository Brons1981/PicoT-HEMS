"""Reset recovery must preserve a validated historical NOM window."""

import json
from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest
from test_completed_route_recovery import completed_case

from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def cloudy(snapshot):
    return replace(
        snapshot,
        pv_energy_timeline=replace(
            snapshot.pv_energy_timeline,
            intervals=tuple(
                replace(
                    i,
                    pv_energy_wh=0,
                    forecast_lower_energy_wh=0,
                    forecast_central_energy_wh=0,
                    forecast_upper_energy_wh=0,
                )
                for i in snapshot.pv_energy_timeline.intervals
            ),
        ),
    )


def historical_nom_case(tmp_path, monkeypatch):
    # A valid persisted daily route with an independently chosen afternoon NOM block.
    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    payload = json.loads(store._path.read_text())
    owner = store.load_daily_assignments()[0]
    plan = payload["execution_plans"][owner.route_plan_id]
    free = next(s for s in plan["segments"] if s["main_assignment_id"] is None)
    free["primitive"] = "balance_bidirectional"
    free["charge_source_policy"] = "pv_only"
    free["purpose"] = "historical-afternoon-pv"
    payload["daily_execution_plans"][owner.assignment_id] = plan
    store._path.write_text(json.dumps(payload))
    return store, pipeline, recover, source


def test_reset_preserves_nom_despite_quarter_hour_forecast_deficits(tmp_path, monkeypatch):
    store, pipeline, recover, source = historical_nom_case(tmp_path, monkeypatch)
    original = store.load_active_daily_main_plan("battery")
    owner = store.load_daily_assignments()[0]
    nom = [
        s
        for s in original.segments
        if s.primitive is Primitive.BALANCE_BIDIRECTIONAL
        and s.main_assignment_id is None
        and s.ends_at > source.captured_at
    ]
    assert nom, "fixture must include a previously chosen free NOM window"
    store.request_planning_recovery(request_id="continuity", requested_at=source.captured_at)
    result = pipeline.run(planning_input=recover(cloudy(source)))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    plan = store.load_active_daily_main_plan("battery")
    for old in nom:
        parts = [s for s in plan.segments if old.starts_at <= s.starts_at < old.ends_at]
        assert parts and all(s.primitive is Primitive.BALANCE_BIDIRECTIONAL for s in parts)
    assert store.load_daily_assignments()[0] == owner
    restarted = ActivePlanCommitmentStore(store._path)
    restored = _restore_daily_charge_context(source, restarted, local_timezone=ZoneInfo("UTC"))
    assert restored.daily_charge_context.status == "ready"
    again = pipeline.run(planning_input=recover(cloudy(source)))
    assert again.evaluation.status == "plan_retained"
    assert store.load_active_daily_main_plan("battery") == plan


def test_existing_dev320_route_is_corrected_once_and_survives_restart(tmp_path, monkeypatch):
    import picot.v2.completed_route_recovery as recovery

    store, pipeline, recover, source = historical_nom_case(tmp_path, monkeypatch)
    store.request_planning_recovery(request_id="dev320", requested_at=source.captured_at)
    # Reproduce the released v1 path, which had no historical-reference selection.
    with monkeypatch.context() as old:
        old.setattr(recovery, "historical_reference", lambda *args: None)
        first = pipeline.run(planning_input=recover(cloudy(source)))
    assert first.evaluation.status == "winner_selected"
    fragmented = store.load_active_daily_main_plan("battery")
    assert all(s.primitive is Primitive.BALANCE_DISCHARGE_ONLY for s in fragmented.segments)
    owner = store.load_daily_assignments()[0]
    result = pipeline.run(planning_input=recover(cloudy(source)))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    repaired = store.load_active_daily_main_plan("battery")
    assert repaired.plan_id != fragmented.plan_id
    assert any(s.primitive is Primitive.BALANCE_BIDIRECTIONAL for s in repaired.segments)
    assert store.load_daily_assignments()[0] == owner
    payload = json.loads(store._path.read_text())
    binding = payload["completed_route_bindings"][repaired.plan_id]
    assert binding["previous_plan_id"] == fragmented.plan_id
    assert binding["reference_plan_id"] == owner.route_plan_id
    restarted = ActivePlanCommitmentStore(store._path)
    restored = _restore_daily_charge_context(
        cloudy(source), restarted, local_timezone=ZoneInfo("UTC")
    )
    assert restored.daily_charge_context.status == "ready"
    before = store._path.read_bytes()
    again = pipeline.run(planning_input=restored)
    assert again.evaluation.status == "plan_retained"
    assert store._path.read_bytes() == before


@pytest.mark.parametrize(
    "unsafe", ["charge", "export", "supplemental", "market_hold", "other_owner"]
)
def test_reset_does_not_resurrect_released_obligations(tmp_path, monkeypatch, unsafe):
    store, pipeline, recover, source = historical_nom_case(tmp_path, monkeypatch)
    owner = store.load_daily_assignments()[0]
    payload = json.loads(store._path.read_text())
    plan = payload["execution_plans"][owner.route_plan_id]
    free = next(s for s in plan["segments"] if s["main_assignment_id"] is None)
    if unsafe in {"charge", "export"}:
        free["primitive"] = "charge_at_power" if unsafe == "charge" else "discharge_at_power"
        free["requested_power_w"] = 1000
        free["charge_source_policy"] = "pv_preferred_grid_allowed" if unsafe == "charge" else None
    elif unsafe == "supplemental":
        free["purpose"] = "supplemental:cancelled"
    elif unsafe == "market_hold":
        free["purpose"] = "market-day:cancelled"
    else:
        free["main_assignment_id"] = "another-day"
    payload["daily_execution_plans"][owner.assignment_id] = plan
    store._path.write_text(json.dumps(payload))
    store.request_planning_recovery(request_id="cancelled", requested_at=source.captured_at)
    result = pipeline.run(planning_input=recover(cloudy(source)))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    restored = store.load_active_daily_main_plan("battery")
    assert all(s.primitive is Primitive.BALANCE_DISCHARGE_ONLY for s in restored.segments)
    binding = json.loads(store._path.read_text())["completed_route_bindings"][restored.plan_id]
    assert "reference_plan_id" not in binding


def test_corrupted_reference_is_rejected_after_restart(tmp_path, monkeypatch):
    store, pipeline, recover, source = historical_nom_case(tmp_path, monkeypatch)
    store.request_planning_recovery(request_id="corrupt", requested_at=source.captured_at)
    pipeline.run(planning_input=recover(cloudy(source)))
    plan = store.load_active_daily_main_plan("battery")
    payload = json.loads(store._path.read_text())
    payload["completed_route_bindings"][plan.plan_id]["reference_plan_id"] = plan.plan_id
    store._path.write_text(json.dumps(payload))
    restarted = ActivePlanCommitmentStore(store._path)
    with pytest.raises(ValueError):
        restarted.load_active_daily_main_plan("battery")


@pytest.mark.parametrize("failure", ["storage", "capability"])
def test_failed_optional_correction_retains_existing_execution(tmp_path, monkeypatch, failure):
    import picot.v2.completed_route_recovery as recovery

    store, pipeline, recover, source = historical_nom_case(tmp_path, monkeypatch)
    store.request_planning_recovery(request_id="dev320-safe", requested_at=source.captured_at)
    with monkeypatch.context() as old:
        old.setattr(recovery, "historical_reference", lambda *args: None)
        pipeline.run(planning_input=recover(cloudy(source)))
    current = store.load_active_daily_main_plan("battery")
    before = store._path.read_bytes()
    if failure == "storage":

        def unavailable(payload):
            raise OSError("disk unavailable")

        monkeypatch.setattr(store, "_write", unavailable)
    else:
        source = replace(
            source,
            capability_snapshot_set=replace(
                source.capability_snapshot_set,
                capabilities=tuple(
                    replace(c, supported_primitives=(Primitive.BALANCE_DISCHARGE_ONLY,))
                    for c in source.capability_snapshot_set.capabilities
                ),
            ),
        )
    result = pipeline.run(planning_input=recover(cloudy(source)))
    assert result.evaluation.status == "plan_retained", result.evaluation.reason
    assert store.load_active_daily_main_plan("battery") == current
    assert store._path.read_bytes() == before
