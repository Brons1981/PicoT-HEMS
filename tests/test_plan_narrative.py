from dataclasses import replace
from datetime import UTC, datetime, timedelta

from test_daily_main_active_pipeline import setup

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import ProjectedEnergyState
from picot.v2.plan_narrative import build_plan_narrative


def test_admitted_input_energy_and_retained_windows(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    result = build_plan_narrative(first)
    assert result["energy_available"]
    assert result["days"]
    assert any(w["kind"] == "grid_charge" for w in result["windows"])
    paths = {p.path_id: p for p in first.candidate_set.energy_paths}
    chosen = paths[first.execution_plan_set.plans[0].winning_energy_path_id]
    expected = sum(s.pv_storage_input_wh or 0 for s in chosen.projected_states) / 1000
    assert abs(sum(d["pv_charge_kwh"] for d in result["days"]) - expected) < 1e-6
    retained = build_plan_narrative(pipeline.run(planning_input=recover()))
    assert retained["windows"] == result["windows"]
    assert retained["energy_available"] is False
    assert retained["days"] == []


def test_rejected_candidate_never_supplies_active_forecast(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    plans = tuple(replace(p, winning_energy_path_id="unavailable-active-path")
                  for p in run.execution_plan_set.plans)
    run = replace(run, execution_plan_set=replace(run.execution_plan_set, plans=plans))
    result = build_plan_narrative(run)
    assert result["energy_available"] is False
    assert result["days"] == []
    assert result["windows"]


def test_fallback_has_no_narrative(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    run = replace(run, evaluation=replace(run.evaluation, status="fallback_active"))
    result = build_plan_narrative(run)
    assert result["days"] == result["windows"] == []


def test_local_midnight_energy_split_and_actual_full_checkpoint(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    now = datetime(2026, 10, 31, 22, 30, tzinfo=UTC)
    end = now + timedelta(hours=1)
    plan = replace(run.execution_plan_set.plans[0], valid_until=end + timedelta(hours=1))
    path = next(p for p in run.candidate_set.energy_paths
                if p.path_id == plan.winning_energy_path_id)
    state = ProjectedEnergyState(at=end, confidence=1, battery_soc=1,
        flow_starts_at=now, pv_storage_input_wh=2000, pv_other_wh=1000,
        grid_storage_input_wh=4000)
    path = replace(path, projected_states=(state,))
    context = replace(run.planning_input.daily_charge_context,
                      timezone="Europe/Amsterdam", restored_at=now)
    run = replace(run, planning_input=replace(run.planning_input, captured_at=now,
                  daily_charge_context=context, capability_snapshot_set=None),
                  candidate_set=replace(run.candidate_set, energy_paths=(path,)),
                  execution_plan_set=replace(run.execution_plan_set, plans=(plan,)))
    result = build_plan_narrative(run)
    assert [d["date"] for d in result["days"]] == ["2026-10-31", "2026-11-01"]
    assert [d["pv_charge_kwh"] for d in result["days"]] == [1, 1]
    assert [d["pv_other_kwh"] for d in result["days"]] == [0.5, 0.5]
    assert [d["grid_charge_kwh"] for d in result["days"]] == [2, 2]
    assert result["days"][0]["full_at"] is None
    assert result["days"][1]["full_at"] == end.isoformat()
    midnight = now + timedelta(minutes=30)
    at_midnight = replace(state, at=midnight)
    path = replace(path, projected_states=(at_midnight,))
    run = replace(run, candidate_set=replace(run.candidate_set, energy_paths=(path,)))
    last_day = build_plan_narrative(run)["days"][-1]
    assert last_day["full_at"] == midnight.isoformat()
    assert last_day["pv_charge_kwh"] is None
    assert last_day["grid_charge_kwh"] is None
    path = replace(path, projected_states=(replace(state, battery_soc=0.99),))
    run = replace(run, candidate_set=replace(run.candidate_set, energy_paths=(path,)))
    assert all(d["full_at"] is None for d in build_plan_narrative(run)["days"])


def test_pv_only_power_charge_is_not_a_grid_window(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    plans = tuple(replace(p, segments=tuple(replace(s,
        charge_source_policy=ChargeSourcePolicy.PV_ONLY)
        if s.primitive.value == "charge_at_power" else s for s in p.segments))
        for p in run.execution_plan_set.plans)
    run = replace(run, execution_plan_set=replace(run.execution_plan_set, plans=plans))
    assert not any(w["kind"] == "grid_charge" for w in build_plan_narrative(run)["windows"])


def test_incomplete_flow_evidence_is_not_a_zero_or_partial_total(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    paths = tuple(replace(p, projected_states=tuple(replace(s, flow_starts_at=None)
        if index == 1 else s for index, s in enumerate(p.projected_states)))
        for p in run.candidate_set.energy_paths)
    run = replace(run, candidate_set=replace(run.candidate_set, energy_paths=paths))
    result = build_plan_narrative(run)
    assert result["energy_available"] is False
    assert all(d["pv_charge_kwh"] is None for d in result["days"])


def test_overlapping_full_path_projections_are_not_added_twice(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    plan = run.execution_plan_set.plans[0]
    path = next(p for p in run.candidate_set.energy_paths
                if p.path_id == plan.winning_energy_path_id)
    other_path = replace(path, path_id="second-path")
    other_plan = replace(plan, plan_id="second-plan", winning_energy_path_id="second-path")
    run = replace(run, candidate_set=replace(run.candidate_set, energy_paths=(path, other_path)),
                  execution_plan_set=replace(run.execution_plan_set, plans=(plan, other_plan),
                      plan_ids=(plan.plan_id, other_plan.plan_id)))
    result = build_plan_narrative(run)
    assert result["energy_available"] is False
    assert result["days"] == []
    assert result["windows"]



