from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from picot.v2.daily_charge_assignment import (
    DailyChargeAssignment,
    DailyChargeSegment,
    published_assignments,
)
from picot.v2.daily_charge_assignment import (
    DailyChargeRevisionReason as Reason,
)
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def instant(hour, day=8):
    return datetime(2026, 9, day, hour, tzinfo=UTC)


def assignment(day=date(2026, 9, 8)):
    return DailyChargeAssignment(
        "battery",
        day,
        "Europe/Amsterdam",
        datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(days=1),
    )


def bound():
    return assignment().bind_main_route(
        plan_id="plan-1",
        segments=(DailyChargeSegment("main-pv", instant(10), instant(12)),),
        at=instant(12, 7),
        reason=Reason.INITIAL,
        evidence_id="publication-plan",
    )


def observe(a, at, *, soc=1.0, segment="main-pv", plan="plan-1", allowed=True):
    return a.observe_completion(
        measured_at=at,
        soc=soc,
        evidence_id="telemetry-full",
        plan_id=plan,
        segment_id=segment,
        execution_allowed=allowed,
    )


def reconcile(now, prices, existing=()):
    return published_assignments(
        now=now,
        timezone="Europe/Amsterdam",
        execution_scope_id="battery",
        price_intervals=prices,
        existing=existing,
    )


def test_identity_is_delivery_day_not_publication_time():
    a = assignment()
    assert a.assignment_id == replace(a, created_at=instant(16, 7)).assignment_id
    assert a.starts_at == instant(22, 7)
    assert a.ends_at == instant(22)


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_delivery_day_and_publication_follow_clock_change(day, hours):
    a = assignment(day)
    assert (a.ends_at - a.starts_at).total_seconds() == hours * 3600
    assert reconcile(a.created_at, ((a.starts_at, a.ends_at),))[0].delivery_date == day


def test_only_main_route_completes_and_completion_survives_restart(tmp_path):
    a = bound()
    assert observe(a, instant(1), segment="bridge").completed_at is None
    assert observe(a, a.starts_at).completed_at is None
    full = observe(a, instant(10))
    assert full.completed_at == instant(10)
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.save_daily_assignment(a)
    store.save_daily_assignment(full)
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    (loaded,) = restarted.load_daily_assignments()
    assert loaded == full
    assert observe(loaded, instant(15), soc=0.9) == full
    restarted.clear("battery")
    restarted.clear_all()
    assert restarted.load_daily_assignments() == (full,)


@pytest.mark.parametrize(
    "at,segment,plan,allowed",
    [
        (instant(11), "bridge", "plan-1", True),
        (instant(11), "main-pv", "old-plan", True),
        (instant(11), "main-pv", "plan-1", False),
        (instant(13), "main-pv", "plan-1", True),
    ],
)
def test_wrong_execution_cannot_complete(at, segment, plan, allowed):
    a = bound()
    assert observe(a, at, segment=segment, plan=plan, allowed=allowed) == a


def test_grid_supplement_is_part_of_same_main_route_but_gap_is_not():
    a = bound()
    revised = a.bind_main_route(
        plan_id="plan-2",
        segments=a.main_segments + (DailyChargeSegment("main-grid", instant(14), instant(16)),),
        at=instant(8),
        reason=Reason.TARGET_UNREACHABLE,
        evidence_id="pv-deficit",
    )
    assert revised.assignment_id == a.assignment_id
    assert revised.revision == 2
    assert observe(revised, instant(13), plan="plan-2", segment="main-grid") == revised
    full = observe(revised, instant(15), plan="plan-2", segment="main-grid")
    assert full.completed_at == instant(15)


def test_missed_publication_duplicate_delivery_and_missing_prices_keep_existing():
    prices = ((instant(22, 7), instant(22)),)
    result = reconcile(instant(9), prices)
    assert len(result) == 1
    assert result[0].delivery_date == date(2026, 9, 8)
    assert reconcile(instant(10), prices + prices, result) == result
    assert reconcile(instant(10), (), result) == result
    full = observe(bound(), instant(10))
    assert reconcile(instant(11), prices, (full,)) == (full,)


def test_new_publication_preserves_running_day_and_creates_only_next_day():
    running = bound()
    result = reconcile(instant(11), ((instant(11), instant(22, 9)),), (running,))
    assert result[0] == running
    assert [a.delivery_date for a in result] == [date(2026, 9, 8), date(2026, 9, 9)]


def test_incomplete_tomorrow_does_not_create_day():
    result = reconcile(instant(12, 7), ((instant(12, 7), instant(12)),))
    assert [a.delivery_date for a in result] == [date(2026, 9, 7)]


def test_price_gap_blocks_creation_until_filled():
    prices = ((instant(22, 7), instant(10)), (instant(11), instant(22)))
    assert reconcile(instant(12, 7), prices) == ()
    assert len(reconcile(instant(12, 7), prices + ((instant(10), instant(11)),))) == 1
    # After late startup the elapsed gap is not an invented historic obligation.
    assert len(reconcile(instant(12), prices)) == 1


def test_scope_isolation_and_timezone_change_cannot_duplicate_goal():
    a = bound()
    other = replace(a, execution_scope_id="other")
    assert reconcile(instant(9), (), (other, a)) == (a,)
    with pytest.raises(ValueError, match="timezone change"):
        published_assignments(
            now=instant(9),
            timezone="UTC",
            execution_scope_id="battery",
            price_intervals=(),
            existing=(a,),
        )


@pytest.mark.parametrize("soc", [float("nan"), float("inf"), -0.1, 1.01])
def test_invalid_soc_never_proves_completion(soc):
    with pytest.raises(ValueError, match="SOC"):
        observe(bound(), instant(11), soc=soc)


def test_completion_at_main_end_counts_for_original_day():
    a = assignment().bind_main_route(
        plan_id="plan-1",
        segments=(DailyChargeSegment("main-pv", instant(20), instant(22)),),
        at=instant(12, 7),
        reason=Reason.INITIAL,
        evidence_id="initial",
    )
    full = observe(a, instant(22))
    assert full.completed_at == a.ends_at
    assert full.delivery_date == date(2026, 9, 8)


def test_completed_assignment_cannot_be_reset_by_stale_writer(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    a = bound()
    store.save_daily_assignment(a)
    full = observe(a, instant(10))
    store.save_daily_assignment(full)
    with pytest.raises(ValueError, match="completed"):
        store.save_daily_assignment(a)
    assert store.load_daily_assignments() == (full,)


def test_same_revision_cannot_replace_route_and_stale_revision_is_rejected(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    a = bound()
    store.save_daily_assignment(a)
    with pytest.raises(ValueError, match="new daily revision"):
        store.save_daily_assignment(replace(a, route_plan_id="untracked-change"))
    revised = a.bind_main_route(
        plan_id="new",
        segments=a.main_segments,
        at=instant(8),
        reason=Reason.PV_LOWER,
        evidence_id="impact",
    )
    store.save_daily_assignment(revised)
    with pytest.raises(ValueError, match="stale"):
        store.save_daily_assignment(a)
    assert store.load_daily_assignments() == (revised,)


@pytest.mark.parametrize(
    "content",
    [
        "{invalid",
        "[]",
        '{"schema_version":2,"commitments":{}}',
        '{"schema_version":1,"commitments":{},"daily_assignments":{"broken":{}}}',
    ],
)
def test_corrupt_state_is_not_overwritten_as_a_new_assignment(tmp_path, content):
    path = tmp_path / "plans.json"
    path.write_text(content)
    store = ActivePlanCommitmentStore(path)
    with pytest.raises(ValueError):
        store.load_daily_assignments()
    with pytest.raises(ValueError):
        store.save_daily_assignment(assignment())
    assert path.read_text() == content


def test_existing_store_schema_needs_no_destructive_migration(tmp_path):
    path = tmp_path / "plans.json"
    path.write_text('{"schema_version":1,"commitments":{},"other_evidence":"keep"}')
    store = ActivePlanCommitmentStore(path)
    assert store.load_daily_assignments() == ()
    store.save_daily_assignment(bound())
    import json

    assert json.loads(path.read_text())["other_evidence"] == "keep"


def test_revision_requires_specific_cause_and_completed_route_is_final():
    a = bound()
    with pytest.raises(ValueError, match="initial reason"):
        a.bind_main_route(
            plan_id="new",
            segments=a.main_segments,
            at=instant(8),
            reason=Reason.INITIAL,
            evidence_id="repeat-publication",
        )
    full = observe(a, instant(10))
    with pytest.raises(ValueError, match="completed"):
        full.bind_main_route(
            plan_id="new",
            segments=a.main_segments,
            at=instant(11),
            reason=Reason.LOAD,
            evidence_id="new-load",
        )


def test_persisted_cycle_from_missed_publication_to_next_delivery_day(tmp_path):
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    (created,) = store.reconcile_daily_publication(
        now=instant(8),
        timezone="Europe/Amsterdam",
        execution_scope_id="battery",
        price_intervals=((instant(22, 7), instant(22)),),
    )
    planned = created.bind_main_route(
        plan_id="plan-1",
        segments=(DailyChargeSegment("main-pv", instant(10), instant(12)),),
        at=instant(8),
        reason=Reason.INITIAL,
        evidence_id="initial-selection",
    )
    store.save_daily_assignment(planned)
    supplemented = planned.bind_main_route(
        plan_id="plan-2",
        segments=planned.main_segments
        + (DailyChargeSegment("main-grid", instant(14), instant(16)),),
        at=instant(11),
        reason=Reason.TARGET_UNREACHABLE,
        evidence_id="pv-shortfall",
    )
    store.save_daily_assignment(supplemented)
    restarted = ActivePlanCommitmentStore(path)
    (current,) = restarted.reconcile_daily_publication(
        now=instant(13),
        timezone="Europe/Amsterdam",
        execution_scope_id="battery",
        price_intervals=(),
    )
    assert current == supplemented
    completed = observe(current, instant(15), plan="plan-2", segment="main-grid")
    restarted.save_daily_assignment(completed)
    today, tomorrow = restarted.reconcile_daily_publication(
        now=instant(16),
        timezone="Europe/Amsterdam",
        execution_scope_id="battery",
        price_intervals=((instant(16), instant(22, 9)),),
    )
    assert today == completed
    assert today.assignment_id == created.assignment_id
    assert tomorrow.delivery_date == date(2026, 9, 9)
    assert tomorrow.completed_at is None and tomorrow.revision == 0
    persisted = path.read_bytes()
    restarted.reconcile_daily_publication(
        now=instant(17),
        timezone="Europe/Amsterdam",
        execution_scope_id="battery",
        price_intervals=((instant(16), instant(22, 9)),),
    )
    assert path.read_bytes() == persisted
