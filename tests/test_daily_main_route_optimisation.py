"""A shortfall changes the route, never the daily goal or another owner."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_main_charge_windows import inputs

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.daily_charge_assignment import DailyChargeRevisionReason
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def fresh(source, *, pv_factor=1.0, soc=None, tag="next"):
    at = source.captured_at + timedelta(seconds=5)
    snapshot_id, run_id = f"snapshot-{tag}", f"run-{tag}"
    pv = source.pv_energy_timeline
    return replace(
        source,
        captured_at=at,
        snapshot_id=snapshot_id,
        run_id=run_id,
        daily_charge_context=None,
        current_storage_states=tuple(
            replace(
                s,
                measured_at=at,
                current_soc=s.current_soc if soc is None else soc,
            )
            for s in source.current_storage_states
        ),
        pv_energy_timeline=replace(
            pv,
            snapshot_id=snapshot_id,
            run_id=run_id,
            intervals=tuple(
                replace(
                    i,
                    pv_energy_wh=i.pv_energy_wh * pv_factor,
                    forecast_lower_energy_wh=i.forecast_lower_energy_wh * pv_factor,
                    forecast_central_energy_wh=i.forecast_central_energy_wh * pv_factor,
                    forecast_upper_energy_wh=i.forecast_upper_energy_wh * pv_factor,
                )
                for i in pv.intervals
            ),
        ),
        household_load_forecast=replace(
            source.household_load_forecast,
            snapshot_id=snapshot_id,
            run_id=run_id,
        ),
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            snapshot_id=snapshot_id,
            captured_at=at,
        ),
    )


def test_lost_pv_adds_grid_to_same_goal_and_persists_revision(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover(fresh(recover(), soc=0.9, tag="initial")))
    original = store.load_daily_assignments()[0]
    old_plan = store.load_active_daily_main_plan("battery")
    assert all(s.primitive is not ExecutionPrimitive.CHARGE_AT_POWER for s in old_plan.segments)
    source = recover(fresh(first.planning_input, pv_factor=0.0))
    result = pipeline.run(planning_input=source)
    revised = store.load_daily_assignments()[0]
    assert result.evaluation.commitment_decision == "triggered_revision", result.evaluation.reason
    assert result.evaluation.daily_main_shortfall.assignment_id == original.assignment_id
    assert revised.assignment_id == original.assignment_id
    assert revised.delivery_date == original.delivery_date
    assert revised.revision == original.revision + 1
    assert revised.revision_reason is DailyChargeRevisionReason.TARGET_UNREACHABLE
    assert revised.completed_at is None
    active = store.load_active_daily_main_plan("battery")
    assert any(s.primitive is ExecutionPrimitive.CHARGE_AT_POWER for s in active.segments)
    assert all(s.starts_at >= source.captured_at for s in active.segments)
    payload = json.loads((tmp_path / "plans.json").read_text())
    assert payload["daily_main_history"][old_plan.plan_id]["plan"]["plan_id"] == old_plan.plan_id
    evidence = payload["daily_main_revision_triggers"][active.plan_id]
    assert evidence["projected_main_peak_wh"] < evidence["target_wh"]
    assert evidence["snapshot_id"] == source.snapshot_id
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    assert restarted.load_active_daily_main_plan("battery") == active
    assert (
        IndependentDailyReferenceAdapter().main_route_shortfalls(
            snapshot=recover(source),
            conversion_model=inputs()["conversion_model"],
        )
        == ()
    )


def test_better_soc_keeps_route_without_window_search(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    before = (tmp_path / "plans.json").read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("a feasible bound route must not search price windows")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", forbidden)
    result = pipeline.run(planning_input=recover(fresh(first.planning_input, soc=0.9)))
    assert result.evaluation.commitment_decision == "retained"
    assert (tmp_path / "plans.json").read_bytes() == before


def test_stale_shortfall_cannot_authorise_another_snapshot(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover(fresh(recover(), soc=0.9, tag="initial")))
    source = recover(fresh(first.planning_input, pv_factor=0.0))
    adapter = IndependentDailyReferenceAdapter()
    (trigger,) = adapter.main_route_shortfalls(
        snapshot=source,
        conversion_model=inputs()["conversion_model"],
    )
    newer = recover(fresh(source, tag="newer"))
    before = (tmp_path / "plans.json").read_bytes()
    with pytest.raises(ValueError, match="shortfall trigger"):
        adapter.main_charge_windows(
            snapshot=newer,
            assignment=store.load_daily_assignments()[0],
            conversion_model=inputs()["conversion_model"],
            optimisation_trigger=trigger,
        )
    assert (tmp_path / "plans.json").read_bytes() == before


def test_physically_unreachable_revision_keeps_open_goal_and_original_plan(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover(fresh(recover(), soc=0.9, tag="initial")))
    source = fresh(first.planning_input, pv_factor=0.0, soc=0.1)
    source = replace(
        source,
        storage_physical_limits=tuple(
            replace(limit, maximum_charge_input_power_w=100.0)
            for limit in source.storage_physical_limits
        ),
    )
    before = (tmp_path / "plans.json").read_bytes()
    result = pipeline.run(planning_input=recover(source))
    assert result.execution_record.status == "observer_fallback_ready"
    assert result.evaluation.commitment_decision == "retained"
    assert (tmp_path / "plans.json").read_bytes() == before
    assert store.load_daily_assignments()[0].completed_at is None


def test_failed_revision_write_keeps_original_route_and_active_pointer(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover(fresh(recover(), soc=0.9, tag="initial")))
    source = recover(fresh(first.planning_input, pv_factor=0.0))
    before = (tmp_path / "plans.json").read_bytes()
    original = store.load_active_daily_main_plan("battery")

    def disk_failure(payload):
        raise OSError("test disk unavailable")

    monkeypatch.setattr(store, "_write", disk_failure)
    result = pipeline.run(planning_input=source)
    assert result.execution_record.status == "observer_fallback_ready"
    assert "test disk unavailable" in result.evaluation.reason
    assert (tmp_path / "plans.json").read_bytes() == before
    assert store.load_active_daily_main_plan("battery") == original
