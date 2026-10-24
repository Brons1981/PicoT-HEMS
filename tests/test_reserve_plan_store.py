"""Reserve publication owns only added charging; daily completion stays immutable."""

from dataclasses import replace

import pytest
from test_daily_main_active_pipeline import setup

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import ProjectedEnergyState, RetainedExecutionOrigin
from picot.domain.evaluation import EvaluationRecord
from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def proposed(previous, *, created_at=None):
    at = created_at or previous.created_at
    free = next(
        s
        for s in previous.segments
        if s.main_assignment_id is None
        and s.starts_at >= at
        and s.primitive in (Primitive.BALANCE_DISCHARGE_ONLY, Primitive.STANDBY)
    )
    segments = []
    for old in previous.segments:
        origin = old.retained_execution_origin or (
            RetainedExecutionOrigin(previous.plan_id, old.segment_id)
            if old.main_assignment_id
            else None
        )
        part = replace(
            old,
            segment_id=f"reserve-test:{len(segments)}",
            source_path_segment_id=f"reserve-path:{len(segments)}",
            retained_execution_origin=origin,
        )
        if old == free:
            part = replace(
                part,
                primitive=Primitive.CHARGE_AT_POWER,
                requested_power_w=2400,
                purpose="reserve:test",
                charge_source_policy=(ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED),
            )
        segments.append(part)
    plan = replace(
        previous,
        plan_id="reserve-test",
        created_at=at,
        evaluation_id="reserve-evaluation",
        winning_candidate_id="reserve-candidate",
        winning_energy_path_id="reserve-path",
        segments=tuple(segments),
    )
    evaluation = EvaluationRecord(
        plan.evaluation_id,
        1,
        plan.snapshot_id,
        plan.strategy_version,
        "reserve-candidates",
        (plan.winning_candidate_id,),
        (),
        (),
        (),
        (),
        "reserve",
        plan.winning_candidate_id,
        at,
        "reserve-test",
    )
    checkpoint = (plan.execution_scope_id, plan.valid_until, 2000.0)
    states = (ProjectedEnergyState(at=plan.valid_until, confidence=1, storage_energy_wh=2100),)
    return dict(
        plan=plan,
        previous_plan_id=previous.plan_id,
        checkpoints=(checkpoint,),
        evaluation_record=evaluation,
        projected_states=states,
    )


def case(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    previous = store.load_active_daily_main_plan("battery")
    return store, proposed(previous)


def test_reserve_binding_restart_and_idempotence_preserve_daily_goals(tmp_path, monkeypatch):
    store, args = case(tmp_path, monkeypatch)
    goals = store.load_daily_assignments()
    store.bind_reserve_plan(**args)
    assert store.load_daily_assignments() == goals
    restarted = ActivePlanCommitmentStore(store._path)
    assert restarted.load_reserve_plan_ids() == (args["plan"].plan_id,)
    assert restarted.load_active_daily_main_plan("battery") == args["plan"]
    before = store._path.read_bytes()
    restarted.bind_reserve_plan(**args)
    assert store._path.read_bytes() == before


@pytest.mark.parametrize("fault", ["previous", "protected", "projection", "evaluation"])
def test_invalid_reserve_publication_is_atomic(tmp_path, monkeypatch, fault):
    store, args = case(tmp_path, monkeypatch)
    if fault == "previous":
        args["previous_plan_id"] = "stale"
    elif fault == "protected":
        plan = args["plan"]
        changed = tuple(
            replace(s, requested_power_w=1200) if s.main_assignment_id else s for s in plan.segments
        )
        args["plan"] = replace(plan, segments=changed)
    elif fault == "projection":
        args["projected_states"] = (replace(args["projected_states"][0], storage_energy_wh=1999),)
    else:
        args["evaluation_record"] = replace(args["evaluation_record"], evaluation_id="wrong")
    before = store._path.read_bytes()
    with pytest.raises(ValueError):
        store.bind_reserve_plan(**args)
    assert store._path.read_bytes() == before


@pytest.mark.parametrize("fault", ["checkpoint", "lineage", "protected"])
def test_corrupt_reserve_binding_is_rejected_on_restart(tmp_path, monkeypatch, fault):
    store, args = case(tmp_path, monkeypatch)
    store.bind_reserve_plan(**args)
    payload = store._load_payload()
    record = payload["reserve_plan_bindings"][args["plan"].plan_id]
    if fault == "checkpoint":
        record["checkpoints"][0]["projected_energy_wh"] = 1999
    elif fault == "lineage":
        record["previous_plan_id"] = args["plan"].plan_id
    else:
        parts = payload["execution_plans"][args["plan"].plan_id]["segments"]
        next(s for s in parts if s["main_assignment_id"])["requested_power_w"] = 1200
    store._write(payload)
    with pytest.raises(ValueError):
        ActivePlanCommitmentStore(store._path).load_active_daily_main_plan("battery")


def test_completed_daily_goal_is_not_reopened_by_reserve(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    previous = store.load_active_daily_main_plan("battery")
    owner = next(a for a in store.load_daily_assignments() if a.route_plan_id == previous.plan_id)
    end = owner.main_segments[-1].ends_at
    completed = replace(
        owner,
        completed_at=end,
        completion_evidence_id="observed-full",
        completion_segment_id=owner.main_segments[-1].segment_id,
    )
    store.save_daily_assignment(completed)
    args = proposed(previous, created_at=end)
    goals = store.load_daily_assignments()
    store.bind_reserve_plan(**args)
    assert store.load_daily_assignments() == goals
    assert next(a for a in goals if a.assignment_id == owner.assignment_id).completed_at == end
    assert (
        ActivePlanCommitmentStore(store._path).load_active_daily_main_plan("battery")
        == args["plan"]
    )


def test_failed_write_preserves_active_pointer(tmp_path, monkeypatch):
    store, args = case(tmp_path, monkeypatch)
    before = store._path.read_bytes()

    def failed(payload):
        raise OSError("write failed")

    monkeypatch.setattr(store, "_write", failed)
    with pytest.raises(OSError):
        store.bind_reserve_plan(**args)
    assert store._path.read_bytes() == before


def test_reserve_publication_keeps_market_budget_and_segments(tmp_path, monkeypatch):
    from test_market_window_transition import legacy_morning

    store, _, _, _, binding = legacy_morning(tmp_path, monkeypatch)
    previous = store.load_active_daily_main_plan("battery")
    daily = store.load_daily_assignments()
    markets = store.load_market_daily_assignments()
    args = proposed(previous)
    store.bind_reserve_plan(**args)
    renewed = next(
        b for b in store.load_market_plan_bindings() if b.assignment_id == binding.assignment_id
    )
    assert renewed.plan_id == args["plan"].plan_id
    assert renewed.expected_export_wh == binding.expected_export_wh
    assert renewed.segment_export_wh == binding.segment_export_wh
    assert store.load_daily_assignments() == daily
    assert store.load_market_daily_assignments() == markets
    assert (
        ActivePlanCommitmentStore(store._path).load_active_daily_main_plan("battery")
        == args["plan"]
    )


@pytest.mark.parametrize("fault", ["scope", "past", "after_checkpoint"])
def test_invalid_reserve_checkpoint_cannot_publish(tmp_path, monkeypatch, fault):
    store, args = case(tmp_path, monkeypatch)
    scope, at, amount = args["checkpoints"][0]
    if fault == "scope":
        scope = "other"
    elif fault == "past":
        at = args["plan"].created_at
    else:
        part = next(s for s in args["plan"].segments if s.purpose.startswith("reserve:"))
        at = part.starts_at
    args["checkpoints"] = ((scope, at, amount),)
    args["projected_states"] = (ProjectedEnergyState(at=at, confidence=1, storage_energy_wh=2100),)
    before = store._path.read_bytes()
    with pytest.raises(ValueError):
        store.bind_reserve_plan(**args)
    assert store._path.read_bytes() == before


def test_committed_reserve_survives_splitting_and_cannot_be_silently_removed(tmp_path, monkeypatch):
    store, args = case(tmp_path, monkeypatch)
    store.bind_reserve_plan(**args)
    previous = args["plan"]
    reserve = next(s for s in previous.segments if s.purpose.startswith("reserve:"))
    midpoint = reserve.starts_at + (reserve.ends_at - reserve.starts_at) / 2
    parts = []
    for old in previous.segments:
        if old == reserve:
            parts.extend(
                (
                    replace(old, segment_id="split-left", ends_at=midpoint),
                    replace(old, segment_id="split-right", starts_at=midpoint),
                )
            )
        else:
            parts.append(old)
    parts = tuple(replace(s, order=n + 1) for n, s in enumerate(parts))
    split = replace(previous, plan_id="split-plan", segments=parts)
    store._retains_reserve_instructions(previous, split)
    removed = replace(
        split,
        segments=tuple(
            replace(
                s,
                purpose="retained-route",
                primitive=Primitive.BALANCE_DISCHARGE_ONLY,
                requested_power_w=None,
                charge_source_policy=None,
            )
            if s.purpose.startswith("reserve:")
            else s
            for s in split.segments
        ),
    )
    before = store._path.read_bytes()
    with pytest.raises(ValueError, match="reserve instructions"):
        store._preserve_market_bindings(store._load_payload(), removed)
    assert store._path.read_bytes() == before
    changed_power = replace(
        split,
        segments=tuple(
            replace(s, requested_power_w=1200) if s.purpose.startswith("reserve:") else s
            for s in split.segments
        ),
    )
    with pytest.raises(ValueError, match="reserve instructions"):
        store._retains_reserve_instructions(previous, changed_power)
