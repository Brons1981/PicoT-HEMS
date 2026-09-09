import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from picot.v2.contracts import CurrentStorageState, PriceForecastPoint, StoragePhysicalLimits
from picot.v2.daily_charge_assignment import DailyChargeAssignment
from picot.v2.live_runtime import (
    _planning_input_signature,
    _poll_live_cycle,
    _restore_daily_charge_context,
    _with_planning_input_diagnostics,
)
from picot.v2.pipeline import _bootstrap_snapshot
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.projection import Card, Projection

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
pytest_plugins = ["test_daily_main_plan_recovery"]
NOW = datetime(2026, 9, 7, 14, tzinfo=UTC)
END = datetime(2026, 9, 8, 22, tzinfo=UTC)


def snapshot(at=NOW, *, prices=(), scope="battery", soc=0.5, measured_at=None):
    return replace(
        _bootstrap_snapshot(at),
        price_points=prices,
        horizon_end=END,
        current_storage_states=(
            CurrentStorageState(
                "actual-soc",
                scope,
                "storage-capability",
                soc,
                8160,
                measured_at or at,
                1.0,
                ("soc-source",),
            ),
        ),
    )


def price(start, end, value=0.20):
    return PriceForecastPoint(str(start), start, end, value, 1.0, "publication")


def recover(source, store, timezone=AMSTERDAM):
    return _restore_daily_charge_context(source, store, local_timezone=timezone)


def bundle(source):
    return PlanningInputBundle(source, (), (), source.captured_at, source.captured_at)


def test_missed_publication_creates_days_once_without_forecasts_or_soc_completion(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    source = snapshot(prices=(price(NOW, END),), soc=1.0)
    restored = recover(source, store)
    context = restored.daily_charge_context
    assert context.status == "ready"
    assert [a.delivery_date for a in context.assignments] == [date(2026, 9, 7), date(2026, 9, 8)]
    assert all(a.completed_at is None and a.revision == 0 for a in context.assignments)
    assert context.main_plans == ()
    assert restored.pv_energy_timeline is None
    before = store._path.read_bytes()
    # A changed publication price does not reset the original daily identity.
    second = recover(snapshot(NOW + timedelta(minutes=5), prices=(price(NOW, END, 0.10),)), store)
    assert second.daily_charge_context.assignments == context.assignments
    assert store._path.read_bytes() == before
    assert source.daily_charge_context is None  # input was not mutated


def test_price_gap_delays_only_missing_delivery_day(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    midnight = datetime(2026, 9, 7, 22, tzinfo=UTC)
    source = snapshot(prices=(price(NOW, midnight), price(midnight + timedelta(minutes=15), END)))
    first = recover(source, store).daily_charge_context.assignments
    assert [a.delivery_date for a in first] == [date(2026, 9, 7)]
    complete = replace(
        source,
        price_points=(*source.price_points, price(midnight, midnight + timedelta(minutes=15))),
    )
    second = recover(complete, store).daily_charge_context.assignments
    assert len(second) == 2
    assert second[0] == first[0]


def test_restart_without_prices_restores_exact_plan_with_original_lineage(tmp_path, selected_route):
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window)
    source = snapshot(plan.created_at + timedelta(seconds=10), scope=plan.execution_scope_id)
    with patch.object(store, "_write", side_effect=AssertionError("no publication write")):
        restored = recover(source, store, ZoneInfo(assignment.timezone))
    context = restored.daily_charge_context
    assert context.status == "ready"
    assert context.assignments == (bound,)
    assert context.main_plans == (plan,)
    assert context.snapshot_id == source.snapshot_id
    assert context.main_plans[0].snapshot_id == plan.snapshot_id != source.snapshot_id
    assert restored.active_plan_commitments == ()  # recovery did not admit execution


def test_invalid_new_prices_do_not_discard_recovered_route(tmp_path, selected_route):
    assignment, plan, window = selected_route
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window)
    source = snapshot(plan.created_at, prices=(price(NOW, END, float("nan")),))
    before = store._path.read_bytes()
    context = recover(source, store, ZoneInfo(assignment.timezone)).daily_charge_context
    assert context.status == "blocked"
    assert context.reason == "daily_charge_published_prices_invalid"
    assert context.assignments == (bound,)
    assert context.main_plans == (plan,)
    assert store._path.read_bytes() == before


def test_corrupt_store_returns_explicit_input_status_without_overwriting(tmp_path):
    path = tmp_path / "plans.json"
    path.write_text("{broken")
    context = recover(
        snapshot(prices=(price(NOW, END),)), ActivePlanCommitmentStore(path)
    ).daily_charge_context
    assert context.status == "blocked"
    assert "refusing destructive reset" in context.reason
    assert path.read_text() == "{broken"


def test_missing_plan_keeps_daily_goal_and_reports_recovery_failure(tmp_path, selected_route):
    assignment, plan, window = selected_route
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    # Earlier identity-only records must not be replaced by a new selection.
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window)
    data = json.loads(store._path.read_text())
    del data["daily_execution_plans"]
    store._path.write_text(json.dumps(data))
    before = store._path.read_bytes()
    context = recover(
        snapshot(plan.created_at), store, ZoneInfo(assignment.timezone)
    ).daily_charge_context
    assert context.status == "blocked"
    assert context.assignments == (bound,)
    assert context.main_plans == ()
    assert store._path.read_bytes() == before


def test_missing_soc_can_reconcile_known_scope_but_cannot_complete(tmp_path):
    source = replace(
        snapshot(prices=(price(NOW, END),)),
        current_storage_states=(),
        storage_physical_limits=(
            StoragePhysicalLimits(
                "battery",
                "storage-capability",
                0.1,
                1.0,
                2400,
                2400,
                ("limits",),
                "test:v1",
            ),
        ),
    )
    context = recover(
        source, ActivePlanCommitmentStore(tmp_path / "plans.json")
    ).daily_charge_context
    assert context.status == "ready"
    assert len(context.assignments) == 2
    assert all(a.completed_at is None for a in context.assignments)


def test_previous_day_owner_is_retained_for_a_pre_midnight_sample(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    yesterday = DailyChargeAssignment("battery", date(2026, 9, 7), AMSTERDAM.key, NOW)
    store.save_daily_assignment(yesterday)
    midnight = datetime(2026, 9, 7, 22, tzinfo=UTC)
    source = snapshot(
        midnight + timedelta(seconds=10), measured_at=midnight - timedelta(seconds=10)
    )
    assert recover(source, store).daily_charge_context.assignments == (yesterday,)
    fresh = snapshot(midnight + timedelta(seconds=20))
    assert recover(fresh, store).daily_charge_context.assignments == ()
    assert store.load_daily_assignments() == (yesterday,)  # history is preserved


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_runtime_publication_uses_local_dst_delivery_day(tmp_path, day, hours):
    start = datetime.combine(day, datetime.min.time(), tzinfo=AMSTERDAM).astimezone(UTC)
    end = (
        datetime.combine(day, datetime.min.time(), tzinfo=AMSTERDAM) + timedelta(days=1)
    ).astimezone(UTC)
    source = snapshot(start - timedelta(hours=8), prices=(price(start, end),))
    context = recover(
        source, ActivePlanCommitmentStore(tmp_path / "plans.json")
    ).daily_charge_context
    assert len(context.assignments) == 1
    a = context.assignments[0]
    assert a.delivery_date == day
    assert (a.ends_at - a.starts_at).total_seconds() == hours * 3600


def test_poll_signature_uses_goal_changes_but_not_recovery_timing(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    source = snapshot(prices=(price(NOW, END),))
    restored = recover(source, store)
    first = _planning_input_signature(bundle(restored))
    timing_only = replace(
        restored, daily_charge_context=replace(restored.daily_charge_context, duration_ms=1234)
    )
    assert _planning_input_signature(bundle(timing_only)) == first
    empty = replace(restored, daily_charge_context=None)
    assert _planning_input_signature(bundle(empty)) != first
    with pytest.raises(ValueError, match="belong to this Planning Input"):
        replace(restored, snapshot_id="another-snapshot")


def test_card_one_passively_exposes_daily_recovery_without_selecting_a_plan(tmp_path):
    restored = recover(
        snapshot(prices=(price(NOW, END),)), ActivePlanCommitmentStore(tmp_path / "plans.json")
    )
    original = Projection(tuple(Card(f"card-{i}", "ready", {}) for i in range(9)), 0.1)
    projected = _with_planning_input_diagnostics(original, bundle(restored))
    attrs = projected.cards[0].attributes
    assert attrs["daily_charge_recovery_status"] == "ready"
    assert len(attrs["daily_charge_assignments"]) == 2
    assert attrs["daily_charge_recovered_plan_ids"] == []
    assert projected.cards[1:] == original.cards[1:]


def test_live_poll_prepares_daily_state_before_deciding_whether_to_run(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    midnight = datetime(2026, 9, 7, 22, tzinfo=UTC)
    current = snapshot(prices=(price(NOW, midnight),))
    executions = []
    preparations = []

    def prepare(value):
        prepared = recover(value.snapshot, store)
        preparations.append(prepared.daily_charge_context)
        return replace(value, snapshot=prepared), None

    def execute(value, diagnostics):
        executions.append(value.snapshot.daily_charge_context)
        return True

    signature = _poll_live_cycle(
        previous_signature=None,
        load_bundle=lambda: bundle(current),
        prepare_bundle=prepare,
        execute=execute,
    )
    assert len(executions) == 1
    original_day = executions[0].assignments[0]
    current = snapshot(NOW + timedelta(minutes=1), prices=current.price_points)
    signature = _poll_live_cycle(
        previous_signature=signature,
        load_bundle=lambda: bundle(current),
        prepare_bundle=prepare,
        execute=execute,
    )
    assert len(preparations) == 2 and len(executions) == 1
    published = replace(current, price_points=(price(NOW, END),))
    _poll_live_cycle(
        previous_signature=signature,
        load_bundle=lambda: bundle(published),
        prepare_bundle=prepare,
        execute=execute,
    )
    assert len(executions) == 2
    assert len(executions[1].assignments) == 2
    assert executions[1].assignments[0] == original_day


def test_timezone_change_and_failed_write_are_explicit_recovery_failures(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    source = snapshot(prices=(price(NOW, END),))
    original = recover(source, store).daily_charge_context
    before = store._path.read_bytes()
    changed = recover(source, store, ZoneInfo("UTC")).daily_charge_context
    assert changed.status == "blocked"
    assert "explicit migration" in changed.reason
    assert changed.assignments == original.assignments
    assert store._path.read_bytes() == before
    empty = ActivePlanCommitmentStore(tmp_path / "new.json")
    with patch.object(empty, "_write", side_effect=OSError("disk full")):
        failed = recover(source, empty).daily_charge_context
    assert failed.status == "blocked" and failed.reason == "disk full"
    assert failed.assignments == ()
    assert empty.load_daily_assignments() == ()


def test_recovery_does_not_reopen_completed_goal_after_discharge(tmp_path, selected_route):
    assignment, plan, window = selected_route
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window)
    segment = bound.main_segments[0]
    completed = bound.observe_completion(
        measured_at=segment.starts_at,
        soc=1.0,
        evidence_id="observed-main-full",
        plan_id=plan.plan_id,
        segment_id=segment.segment_id,
        execution_allowed=True,
    )
    store.save_daily_assignment(completed)
    source = snapshot(segment.starts_at + timedelta(seconds=30), soc=0.9)
    context = recover(source, store, ZoneInfo(assignment.timezone)).daily_charge_context
    assert context.status == "ready"
    assert context.assignments == (completed,)
    assert context.main_plans == (plan,)
