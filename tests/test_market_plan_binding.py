"""Shared ownership persistence using a charge plan built by the real pipeline.

The proposed trade below is a store-boundary fixture, not financial admission
or an HA execution proof.
"""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup
from test_market_daily_assignment import goal

from picot.domain.energy_path import RetainedExecutionOrigin
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.market_plan_binding import MarketPlanBinding
from picot.planner.market_route_admission import MarketAdmission
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def proposal(store, previous):
    free = next(s for s in previous.segments if s.main_assignment_id is None
                and not s.purpose.startswith("supplemental:")
                and s.primitive is not ExecutionPrimitive.CHARGE_AT_POWER)
    assignment = store.ensure_market_daily_assignment(goal(
        execution_scope_id=previous.execution_scope_id,
        delivery_date=free.starts_at.date(), timezone="UTC", created_at=previous.created_at,
    ))
    parts = []
    for part in previous.segments:
        changes = {"segment_id": "shared:" + part.segment_id}
        if part.main_assignment_id is not None:
            changes["retained_execution_origin"] = part.retained_execution_origin or (
                RetainedExecutionOrigin(previous.plan_id, part.segment_id)
            )
        if part == free:
            export_end = min(part.ends_at, part.starts_at + timedelta(minutes=30))
            changes.update(primitive=ExecutionPrimitive.DISCHARGE_AT_POWER,
                           purpose=assignment.assignment_id, requested_power_w=2400,
                           charge_source_policy=None, ends_at=export_end)
        parts.append(replace(part, **changes))
        if part == free and export_end < part.ends_at:
            parts.append(replace(part, segment_id="remainder:" + part.segment_id,
                                 starts_at=export_end))
    parts = [replace(s, order=i) for i, s in enumerate(parts, 1)]
    plan = replace(previous, plan_id="shared:" + previous.plan_id, segments=tuple(parts))
    binding = MarketPlanBinding(assignment.assignment_id, plan.execution_scope_id, plan.plan_id,
                                plan.snapshot_id, ("shared:" + free.segment_id,), 100, (100,))
    admission = MarketAdmission(assignment.assignment_id, plan.snapshot_id, "admissible",
                                "store-test", 100)
    return dict(plan=plan, previous_plan_id=previous.plan_id, binding=binding, admission=admission)


def prepared(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    observed = pipeline.run(planning_input=recover()).execution_plan_set.plans[0]
    plan = store.load_active_daily_main_plan(observed.execution_scope_id)
    return store, recover, plan, proposal(store, plan)


def test_shared_plan_restart_preserves_daily_goal_and_completion_lineage(tmp_path, monkeypatch):
    store, recover, original, args = prepared(tmp_path, monkeypatch)
    owners = store.load_daily_assignments()
    store.bind_market_plan(**args)
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    assert restarted.load_daily_assignments() == owners
    assert restarted.load_active_daily_main_plan(original.execution_scope_id) == args["plan"]
    assert restarted.load_market_plan_bindings() == (args["binding"],)
    context = recover().daily_charge_context
    assert context.status == "ready", context.reason
    assert context.active_main_plan_ids == (args["plan"].plan_id,)
    assert context.market_plan_bindings == (args["binding"],)
    main = next(s for s in args["plan"].segments if s.main_assignment_id is not None)
    done = restarted.observe_daily_main_completion(
        execution_scope_id=original.execution_scope_id, plan_id=args["plan"].plan_id,
        segment_id=main.segment_id, confirmed_since=main.starts_at,
        observed_at=main.ends_at, measured_at=main.ends_at, soc=1, evidence_id="measured-full",
    )
    assert done.completed_at == main.ends_at
    assert done.route_plan_id == original.plan_id
    assert restarted.load_market_daily_assignments()[0].status == "pending"


def test_failed_publication_preserves_exact_old_plan_and_all_owners(tmp_path, monkeypatch):
    import os

    store, _, original, args = prepared(tmp_path, monkeypatch)
    path = tmp_path / "plans.json"
    before = path.read_bytes()

    def fail(*args):
        raise OSError("write failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="write failure"):
        store.bind_market_plan(**args)
    assert path.read_bytes() == before
    restarted = ActivePlanCommitmentStore(path)
    assert restarted.load_active_daily_main_plan(original.execution_scope_id) == original
    assert restarted.load_market_plan_bindings() == ()


@pytest.mark.parametrize("corruption", ["main", "origin", "stale", "admission"])
def test_market_cannot_revise_charge_or_publish_stale_evidence(tmp_path, monkeypatch, corruption):
    store, _, _, args = prepared(tmp_path, monkeypatch)
    if corruption in {"main", "origin"}:
        plan = args["plan"]
        parts = tuple(replace(s, **({"requested_power_w": 1} if corruption == "main"
                                    else {"retained_execution_origin": None}))
                      if s.main_assignment_id is not None else s for s in plan.segments)
        args["plan"] = replace(plan, segments=parts)
    elif corruption == "stale":
        args["previous_plan_id"] = "old-plan"
    else:
        args["admission"] = replace(args["admission"], status="rejected")
    before = (tmp_path / "plans.json").read_bytes()
    with pytest.raises(ValueError):
        store.bind_market_plan(**args)
    assert (tmp_path / "plans.json").read_bytes() == before


def test_same_binding_is_idempotent_and_no_second_daily_action(tmp_path, monkeypatch):
    store, _, _, args = prepared(tmp_path, monkeypatch)
    store.bind_market_plan(**args)
    before = (tmp_path / "plans.json").read_bytes()
    assert store.bind_market_plan(**args) == args["binding"]
    assert (tmp_path / "plans.json").read_bytes() == before
    other = dict(args, binding=replace(args["binding"], expected_export_wh=200,
                                      segment_export_wh=(200,)),
                 admission=replace(args["admission"], expected_export_wh=200))
    with pytest.raises(ValueError, match="another action"):
        store.bind_market_plan(**other)


def test_shared_plan_preserves_supplemental_target_and_completion(tmp_path, monkeypatch):
    from test_supplemental_charge_commitment import charged

    store, _, _, _, completed = charged(tmp_path, monkeypatch)
    original = store.load_active_daily_main_plan("battery")
    goal_before = store.load_supplemental_assignments()[0]
    args = proposal(store, original)
    store.bind_market_plan(**args)
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    bound = restarted.load_supplemental_assignments()[0]
    assert replace(bound, plan_id=goal_before.plan_id, segment_ids=goal_before.segment_ids) == (
        goal_before
    )
    assert restarted.load_daily_assignments()[0] == completed
    done = restarted.observe_supplemental_completion(
        execution_scope_id=bound.execution_scope_id, plan_id=bound.plan_id,
        segment_id=bound.segment_ids[-1], confirmed_since=bound.starts_at,
        observed_at=bound.ends_at, measured_at=bound.ends_at, soc=bound.target_soc,
        evidence_id="supplemental-measured",
    )
    assert done.completed_at == bound.ends_at
    assert restarted.load_daily_assignments()[0] == completed


def test_retained_soc_monitor_includes_market_energy_without_price_search(tmp_path, monkeypatch):
    from test_daily_main_charge_windows import inputs

    from picot.planner.independent_daily_intent_simulator import IndependentDailyIntentSimulator
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    store, recover, _, args = prepared(tmp_path, monkeypatch)
    store.bind_market_plan(**args)
    projections = []
    real = IndependentDailyIntentSimulator.simulate_planning_basis

    def record(self, **kwargs):
        projection = real(self, **kwargs)
        projections.append(projection)
        return projection

    monkeypatch.setattr(IndependentDailyIntentSimulator, "simulate_planning_basis", record)
    IndependentDailyReferenceAdapter().main_route_shortfalls(
        snapshot=recover(), conversion_model=inputs()["conversion_model"],
    )
    assert len(projections) == 1
    assert sum(i.storage_to_grid_output_wh for i in projections[0].intervals) == pytest.approx(100)


def test_restart_rejects_changed_main_in_shared_plan(tmp_path, monkeypatch):
    import json

    store, _, original, args = prepared(tmp_path, monkeypatch)
    store.bind_market_plan(**args)
    path = tmp_path / "plans.json"
    payload = json.loads(path.read_text())
    plan = payload["execution_plans"][args["plan"].plan_id]
    main = next(s for s in plan["segments"] if s["main_assignment_id"] is not None)
    main["requested_power_w"] = 1
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="retained instructions"):
        ActivePlanCommitmentStore(path).load_active_daily_main_plan(original.execution_scope_id)


def test_old_store_without_generic_pointer_still_restores_exact_daily_plan(tmp_path, monkeypatch):
    import json

    store, _, original, _ = prepared(tmp_path, monkeypatch)
    path = tmp_path / "plans.json"
    payload = json.loads(path.read_text())
    payload.pop("active_execution_plan_ids")
    payload.pop("execution_plans")
    path.write_text(json.dumps(payload))
    assert store.load_active_daily_main_plan(original.execution_scope_id) == original
