"""Two delivery days through discovery, Evaluation, Plan Builder and Store."""

import json
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_charge_windows import dev243_snapshot_and_conversion

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.execution_plan_projection import project_execution_plan_set
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def recover(snapshot, store):
    return _restore_daily_charge_context(
        snapshot, store, local_timezone=ZoneInfo("Europe/Amsterdam")
    )


def select(snapshot, assignment, conversion):
    windows = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot,
        assignment=assignment,
        conversion_model=conversion,
    )
    assert windows.windows
    tariffs = IndependentDailyTariffAdapter().build(
        snapshot,
        horizon_end=windows.windows[0].schedule.horizon_end,
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot,
        windows=windows,
        tariffs=tariffs,
        opportunity_ids=("published-prices",),
    )
    evaluation = EvaluationEngine().evaluate(
        portfolio.candidate_set,
        portfolio.strategy,
        portfolio.outcome_set,
        created_at=snapshot.captured_at,
    )
    source = next(
        s for s in portfolio.sources if s.candidate_id == evaluation.record.winning_candidate_id
    )
    plan_set = ExecutionPlanBuilder().build(
        evaluation,
        created_at=snapshot.captured_at,
        fallback_policy_id="guarded-nom",
    )
    return source.window, plan_set, evaluation


@pytest.fixture(scope="module")
def two_days(tmp_path_factory):
    snapshot, conversion = dev243_snapshot_and_conversion()
    snapshot = replace(
        snapshot,
        capability_snapshot_set=replace(
            snapshot.capability_snapshot_set,
            capabilities=tuple(
                replace(
                    c,
                    supported_primitives=(
                        ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
                        ExecutionPrimitive.CHARGE_AT_POWER,
                    ),
                )
                for c in snapshot.capability_snapshot_set.capabilities
            ),
        ),
    )
    path = tmp_path_factory.mktemp("two-main-days") / "plans.json"
    store = ActivePlanCommitmentStore(path)
    source = recover(snapshot, store)
    today, tomorrow = source.daily_charge_context.assignments
    first_window, first_set, _ = select(source, today, conversion)
    first = store.bind_daily_main_plan(plan=first_set.plans[0], window=first_window)
    source = recover(snapshot, store)
    second_window, second_set, second_evaluation = select(source, tomorrow, conversion)
    return dict(
        source=source,
        conversion=conversion,
        first=first,
        first_plan=first_set.plans[0],
        first_window=first_window,
        second_window=second_window,
        second_set=second_set,
        evaluation=second_evaluation,
        initial_bytes=path.read_bytes(),
        tomorrow=tomorrow,
    )


def stored(tmp_path, case):
    path = tmp_path / "plans.json"
    path.write_bytes(case["initial_bytes"])
    return ActivePlanCommitmentStore(path)


def test_next_day_preserves_current_main_action_and_explicit_origin(two_days, tmp_path):
    case = two_days
    store = stored(tmp_path, case)
    plan = case["second_set"].plans[0]
    retained = [s for s in plan.segments if s.retained_execution_origin is not None]
    assert retained
    for segment in retained:
        origin = segment.retained_execution_origin
        assert segment.main_assignment_id == case["first"].assignment_id
        assert origin.plan_id == case["first_plan"].plan_id
        original = next(s for s in case["first_plan"].segments if s.segment_id == origin.segment_id)
        assert segment.segment_id != original.segment_id
        assert (
            segment.starts_at,
            segment.ends_at,
            segment.primitive,
            segment.requested_power_w,
        ) == (
            original.starts_at,
            original.ends_at,
            original.primitive,
            original.requested_power_w,
        )
    bound = store.bind_daily_main_plan(plan=plan, window=case["second_window"])
    first, second = store.load_daily_assignments()
    assert first == case["first"]
    assert second == bound
    assert second.completed_at is None and first.completed_at is None
    assert {s.segment_id for s in retained}.isdisjoint(s.segment_id for s in second.main_segments)
    assert store.load_daily_main_plan(bound.assignment_id) == plan
    assert store.load_daily_main_plan(first.assignment_id) == case["first_plan"]
    projected = project_execution_plan_set(
        case["second_set"],
        run_id=case["source"].run_id,
        captured_at=case["source"].captured_at,
        observer_only=True,
    )
    assert [s.retained_execution_origin for s in projected.plans[0].segments] == [
        s.retained_execution_origin for s in plan.segments
    ]


@pytest.mark.parametrize("damage", ["omitted", "power", "origin"])
def test_new_horizon_cannot_hide_a_change_to_the_running_main(two_days, tmp_path, damage):
    case = two_days
    store = stored(tmp_path, case)
    window, plan = case["second_window"], case["second_set"].plans[0]
    if damage == "omitted":
        window = replace(window, retained_main_segments=())
    else:
        modified = []
        changed = False
        for segment in plan.segments:
            if segment.retained_execution_origin is not None and not changed:
                if damage == "power":
                    segment = replace(segment, requested_power_w=1200)
                else:
                    segment = replace(segment, retained_execution_origin=None)
                changed = True
            modified.append(segment)
        plan = replace(plan, segments=tuple(modified))
    before = store._path.read_bytes()
    with pytest.raises(ValueError, match="main|origin"):
        store.bind_daily_main_plan(plan=plan, window=window)
    assert store._path.read_bytes() == before


def test_a_new_horizon_can_retain_only_the_remaining_part_of_an_active_segment(two_days, tmp_path):
    case = two_days
    store = stored(tmp_path, case)
    active = case["first"].main_segments[0]
    at = active.starts_at + timedelta(seconds=5)
    old = case["source"]
    source = replace(
        old,
        captured_at=at,
        snapshot_id="snapshot-later",
        run_id="run-later",
        daily_charge_context=None,
        current_storage_states=tuple(
            replace(s, measured_at=at) for s in old.current_storage_states
        ),
        pv_energy_timeline=replace(
            old.pv_energy_timeline, snapshot_id="snapshot-later", run_id="run-later"
        ),
        household_load_forecast=replace(
            old.household_load_forecast, snapshot_id="snapshot-later", run_id="run-later"
        ),
        capability_snapshot_set=replace(
            old.capability_snapshot_set, snapshot_id="snapshot-later", captured_at=at
        ),
    )
    source = recover(source, store)
    window, plan_set, _ = select(source, case["tomorrow"], case["conversion"])
    plan = plan_set.plans[0]
    continuation = next(s for s in plan.segments if s.retained_execution_origin is not None)
    assert continuation.starts_at == at
    assert continuation.retained_execution_origin.segment_id == active.segment_id
    store.bind_daily_main_plan(plan=plan, window=window)
    assert store.load_daily_assignments()[0] == case["first"]


def test_snapshot_recovery_error_cannot_be_ignored_by_main_discovery(two_days):
    case = two_days
    source = replace(
        case["source"],
        daily_charge_context=replace(
            case["source"].daily_charge_context,
            status="blocked",
            reason="stored route unavailable",
        ),
    )
    with pytest.raises(ValueError, match="context_blocked"):
        IndependentDailyReferenceAdapter().main_charge_windows(
            snapshot=source,
            assignment=case["tomorrow"],
            conversion_model=case["conversion"],
        )


def test_previous_records_without_origin_fields_remain_readable_and_idempotent(two_days, tmp_path):
    case = two_days
    store = stored(tmp_path, case)
    payload = json.loads(store._path.read_text())
    for record in payload["daily_execution_plans"].values():
        for segment in record["segments"]:
            segment.pop("main_assignment_id", None)
            segment.pop("retained_execution_origin", None)
    store._path.write_text(json.dumps(payload))
    before = store._path.read_bytes()
    loaded = store.load_daily_main_plan(case["first"].assignment_id)
    assert loaded.plan_id == case["first_plan"].plan_id
    assert all(s.main_assignment_id is None for s in loaded.segments)
    assert store.bind_daily_main_plan(plan=loaded, window=case["first_window"]) == case["first"]
    assert store._path.read_bytes() == before


def test_restart_rejects_a_corrupted_retained_origin(two_days, tmp_path):
    case = two_days
    store = stored(tmp_path, case)
    bound = store.bind_daily_main_plan(
        plan=case["second_set"].plans[0],
        window=case["second_window"],
    )
    payload = json.loads(store._path.read_text())
    segments = payload["daily_execution_plans"][bound.assignment_id]["segments"]
    retained = next(s for s in segments if s["retained_execution_origin"] is not None)
    retained["retained_execution_origin"]["segment_id"] = "not-the-original-main"
    store._path.write_text(json.dumps(payload))
    before = store._path.read_bytes()
    with pytest.raises(ValueError, match="refusing to invent"):
        store.load_daily_main_plan(bound.assignment_id)
    assert store._path.read_bytes() == before
    assert store.load_daily_assignments()[0] == case["first"]


def test_next_day_cannot_hide_an_unreachable_running_main_goal(two_days):
    case = two_days
    source = replace(
        case["source"],
        current_storage_states=tuple(
            replace(s, current_soc=0.1) for s in case["source"].current_storage_states
        ),
    )
    result = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=source,
        assignment=case["tomorrow"],
        conversion_model=case["conversion"],
    )
    assert result.windows == ()
    assert result.reason == "retained_main_goal_requires_explicit_optimisation"
    assert source.daily_charge_context.assignments[0] == case["first"]
