from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.domain.market_user_rule import MarketUserRule
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

BASE = datetime(2026, 9, 8, 12, tzinfo=UTC)


def goal(**updates):
    args = dict(
        rule=MarketUserRule("user-trade", 1, 0.25, 0.05),
        execution_scope_id="battery",
        delivery_date=date(2026, 9, 9),
        timezone="Europe/Amsterdam",
        created_at=BASE,
        usable_capacity_wh=8160,
    )
    args.update(updates)
    return MarketDailyAssignment(**args)


@pytest.mark.parametrize(
    "status,export",
    [("pending", None), ("skipped", None), ("completed", 1800.0), ("stopped", 300.0)],
)
def test_day_budget_is_not_repeated_after_restart_or_rule_revision(tmp_path, status, export):
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    original = store.ensure_market_daily_assignment(goal())
    if status != "pending":
        original = store.close_market_daily_assignment(
            assignment_id=original.assignment_id,
            status=status,
            at=BASE + timedelta(days=1),
            evidence_id="measured-outcome",
            measured_export_wh=export,
        )
    before = path.read_bytes()
    restarted = ActivePlanCommitmentStore(path)
    found = restarted.ensure_market_daily_assignment(
        goal(rule=MarketUserRule("user-trade", 2, 0.5, 0.1), created_at=BASE + timedelta(hours=1))
    )
    assert found == original
    assert found.battery_energy_wh == 2040
    assert path.read_bytes() == before
    assert restarted.load_daily_assignments() == ()
    assert restarted.load_active_daily_main_plan("battery") is None


def test_different_days_and_rules_have_separate_identity(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    for item in (
        goal(),
        goal(delivery_date=date(2026, 9, 10)),
        goal(rule=MarketUserRule("other", 1, 0.25, 0.05)),
    ):
        store.ensure_market_daily_assignment(item)
    assert len(store.load_market_daily_assignments()) == 3


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_real_local_delivery_day(day, hours):
    item = goal(delivery_date=day, created_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert item.ends_at - item.starts_at == timedelta(hours=hours)


def test_outcome_is_idempotent_but_cannot_be_changed(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    item = store.ensure_market_daily_assignment(goal())
    args = dict(
        assignment_id=item.assignment_id, status="skipped", at=BASE, evidence_id="soc-insufficient"
    )
    done = store.close_market_daily_assignment(**args)
    assert store.close_market_daily_assignment(**args) == done
    with pytest.raises(ValueError, match="overwritten"):
        store.close_market_daily_assignment(**(args | {"status": "pending"}))


def test_write_failure_preserves_existing_documents(tmp_path, monkeypatch):
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    item = store.ensure_market_daily_assignment(goal())
    before = path.read_bytes()

    def fail(*args):
        raise OSError("write failure")

    monkeypatch.setattr(store, "_write", fail)
    with pytest.raises(OSError):
        store.close_market_daily_assignment(
            assignment_id=item.assignment_id, status="skipped", at=BASE, evidence_id="soc"
        )
    assert path.read_bytes() == before
    assert ActivePlanCommitmentStore(path).load_market_daily_assignments() == (item,)


def test_corrupt_identity_is_rejected(tmp_path):
    import json

    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    item = store.ensure_market_daily_assignment(goal())
    raw = json.loads(path.read_text())
    raw["market_daily_assignments"]["wrong-key"] = raw["market_daily_assignments"].pop(
        item.assignment_id
    )
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="invalid stored"):
        store.load_market_daily_assignments()


def test_timezone_change_cannot_replenish_same_day(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    item = store.ensure_market_daily_assignment(goal())
    with pytest.raises(ValueError, match="timezone"):
        store.ensure_market_daily_assignment(replace(item, timezone="UTC"))
