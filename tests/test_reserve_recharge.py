from dataclasses import replace
from datetime import timedelta

from test_portfolio_recharge import case

from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def test_completed_daily_goal_is_not_reopened_for_reserve_acquisition(tmp_path):
    store, snapshot, _, _, model, pipeline, recover = case(tmp_path)
    original = store.load_active_daily_main_plan("battery")
    main = next(
        s
        for s in original.segments
        if s.main_assignment_id is not None and s.primitive.value == "charge_at_power"
    )
    completed = store.observe_daily_main_completion(
        execution_scope_id="battery",
        plan_id=original.plan_id,
        segment_id=main.segment_id,
        confirmed_since=main.starts_at,
        observed_at=main.ends_at,
        measured_at=main.ends_at,
        soc=1.0,
        evidence_id="measured-full",
    )
    assert completed is not None and completed.completed_at is not None
    now = main.ends_at + timedelta(minutes=1)
    snapshot = replace(
        snapshot,
        captured_at=now,
        daily_charge_context=None,
        current_storage_states=tuple(
            replace(s, measured_at=now, current_soc=0.99) for s in snapshot.current_storage_states
        ),
        capability_snapshot_set=replace(
            snapshot.capability_snapshot_set,
            captured_at=now,
            capabilities=tuple(
                replace(c, fresh_at=now) for c in snapshot.capability_snapshot_set.capabilities
            ),
        ),
    )
    snapshot = recover(snapshot)
    assert snapshot.daily_charge_context.status == "ready"
    baseline, _ = IndependentDailyReferenceAdapter().committed_plan_projection(
        snapshot=snapshot,
        plan=original,
        conversion_model=model,
    )
    checkpoint = (
        "battery",
        original.valid_until,
        baseline.intervals[-1].storage_energy_at_end_wh + 500,
    )
    snapshot = replace(snapshot, storage_reserve_checkpoints=(checkpoint,))
    before = store.load_daily_assignments()
    run = pipeline.run(planning_input=snapshot)
    assert run.execution_plan_set.plans, run.evaluation.reason
    assert store.load_daily_assignments() == before
    updated = store.load_active_daily_main_plan("battery")
    assert updated.plan_id != original.plan_id, run.evaluation.reason
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    assert restarted.load_active_daily_main_plan("battery") == updated
    assert restarted.load_daily_assignments() == before
    fresh = recover(snapshot)
    assert fresh.daily_charge_context.status == "ready", fresh.daily_charge_context.reason
    repeated = pipeline.run(planning_input=fresh)
    assert repeated.execution_plan_set.plans[0].plan_id == updated.plan_id


def test_generic_reserve_chooses_cheaper_available_charge_without_mutation(tmp_path):
    from picot.planner.evaluation_engine import EvaluationEngine
    from picot.v2.reserve_recharge import portfolio

    store, snapshot, _, _, model, _, _ = case(tmp_path)
    plan = store.load_active_daily_main_plan("battery")
    adapter = IndependentDailyReferenceAdapter()
    baseline, _ = adapter.committed_plan_projection(
        snapshot=snapshot,
        plan=plan,
        conversion_model=model,
    )
    cheap_start = snapshot.captured_at + timedelta(hours=8)
    cheap_end = cheap_start + timedelta(hours=1)
    snapshot = replace(
        snapshot,
        storage_reserve_checkpoints=(
            (
                "battery",
                plan.valid_until,
                baseline.intervals[-1].storage_energy_at_end_wh + 500,
            ),
        ),
        price_points=tuple(
            replace(
                snapshot.price_points[0],
                point_id=f"price-{n}",
                starts_at=start,
                ends_at=end,
                value_eur_per_kwh=price,
            )
            for n, (start, end, price) in enumerate(
                (
                    (snapshot.captured_at, cheap_start, 0.50),
                    (cheap_start, cheap_end, 0.05),
                    (cheap_end, plan.valid_until, 0.50),
                )
            )
        ),
    )
    before = store._load_payload()
    options = portfolio(snapshot, plan, model)
    assert options is not None
    result = EvaluationEngine().evaluate(
        options.comparable.candidate_set,
        options.comparable.strategy,
        options.comparable.outcome_set,
        created_at=snapshot.captured_at,
    )
    assert result.winning_energy_path is not None
    added = [s for s in result.winning_energy_path.segments if s.purpose.startswith("reserve:")]
    assert added
    assert all(cheap_start <= s.starts_at < s.ends_at <= cheap_end for s in added), [
        (s.starts_at, s.ends_at, s.primitive) for s in added
    ]
    assert store._load_payload() == before


def test_reserve_above_capacity_has_no_winner_and_no_writes(tmp_path):
    from picot.planner.evaluation_engine import EvaluationEngine
    from picot.v2.reserve_recharge import portfolio

    store, snapshot, _, _, model, _, _ = case(tmp_path)
    plan = store.load_active_daily_main_plan("battery")
    snapshot = replace(snapshot, storage_reserve_checkpoints=(("battery", plan.valid_until, 9000),))
    before = store._load_payload()
    options = portfolio(snapshot, plan, model)
    result = EvaluationEngine().evaluate(
        options.comparable.candidate_set,
        options.comparable.strategy,
        options.comparable.outcome_set,
        created_at=snapshot.captured_at,
    )
    assert result.winning_energy_path is None
    assert store._load_payload() == before


def test_reserve_missing_context_or_capabilities_rejects_without_store_mutation(tmp_path):
    import pytest

    from picot.v2.reserve_recharge import portfolio

    store, snapshot, _, _, model, _, _ = case(tmp_path)
    plan = store.load_active_daily_main_plan("battery")
    snapshot = replace(snapshot, storage_reserve_checkpoints=(
        ("battery", plan.valid_until, 5000.0),
    ))
    before = store.load_daily_assignments()
    for field in ("daily_charge_context", "capability_snapshot_set"):
        with pytest.raises(ValueError, match="reserve_acquisition_context_missing"):
            portfolio(replace(snapshot, **{field: None}), plan, model)
        assert store.load_active_daily_main_plan("battery") == plan
        assert store.load_daily_assignments() == before
