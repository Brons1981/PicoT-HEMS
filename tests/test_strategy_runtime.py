"""Settings activation is serialized with planning and forces fresh input."""

import json
from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread

import pytest
from test_daily_material_replanning import bundle, prepared
from test_v2_live_replan_poll_cycle import BASE, _bundle, _with_active_commitment

from picot.domain.runtime import RuntimeObservationKind
from picot.runtime.runtime_monitor import RuntimeMonitorSession
from picot.v2.live_runtime import (
    PlanningResetBarrier,
    _poll_live_cycle,
    _update_user_rules_and_replan,
)
from picot.v2.user_rules import UserRuleStore
from picot.v2.web_ui import WebViewStore


def test_strategy_update_waits_for_older_cycle_and_preserves_unrelated_rules(tmp_path):
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25)
    store.update(preserve_pv_during_grid_charge=False, maximum_trading_soc_percent=25,
                 market_minimum_spread_eur_per_kwh=.073, market_wear_eur_per_kwh=.025)
    original = store.current()
    barrier, replan = PlanningResetBarrier(), Event()
    entered, release, updated = Event(), Event(), Event()
    activated, result, errors = [], [], []
    web = WebViewStore()
    web.publish({"run_id": "before"})

    def cycle():
        entered.set()
        assert release.wait(2)
        assert store.current() == original
        assert not activated

    def update():
        try:
            result.append(_update_user_rules_and_replan(
                store=store, barrier=barrier, replan_requested=replan,
                web_view_store=web, payload={"strategy_position": 0},
                activate_profile=activated.append,
            ))
        except Exception as exc:
            errors.append(exc)
        finally:
            updated.set()

    cycle_thread = Thread(target=lambda: barrier.run_cycle(cycle))
    update_thread = Thread(target=update)
    cycle_thread.start()
    assert entered.wait(2)
    update_thread.start()
    try:
        assert not updated.wait(.05)
        assert not replan.is_set()
    finally:
        release.set()
        cycle_thread.join(2)
        update_thread.join(2)
    assert not errors
    assert len(activated) == 1
    assert activated[0].maximum_trading_soc_percent == 0
    assert activated[0].market_rule() is None
    assert activated[0].preserve_pv_during_grid_charge is False
    assert activated[0].market_wear_eur_per_kwh == .025
    assert activated[0].market_minimum_spread_eur_per_kwh == .073
    assert replan.is_set()
    assert result[0]["user_rule_revision"] == original.revision + 1
    assert result[0]["replan_requested"] is True
    assert result[0]["reset_generation"] == 1
    assert json.loads(web.latest_json())["user_rules"]["strategy_position"] == 0


def test_unavailable_trade_mode_cannot_activate_or_request_planning(tmp_path):
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25)
    original = store.current()
    barrier, event, activated = PlanningResetBarrier(), Event(), []
    with pytest.raises(ValueError):
        _update_user_rules_and_replan(
            store=store, barrier=barrier, replan_requested=event,
            web_view_store=WebViewStore(), payload={"strategy_position": 4},
            activate_profile=activated.append,
        )
    assert store.current() == original
    assert not activated and not event.is_set()
    assert barrier.generation == 0


def test_zero_trade_setting_wakes_real_monitor_and_uses_second_fresh_capture(tmp_path):
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25)
    event = Event()
    _update_user_rules_and_replan(
        store=store, barrier=PlanningResetBarrier(), replan_requested=event,
        web_view_store=WebViewStore(), payload={"strategy_position": 0},
        activate_profile=lambda profile: None,
    )
    assert event.is_set()
    # The live loop consumes this event by clearing its prior signature.
    event.clear()
    observation = _with_active_commitment(_bundle(captured_at=BASE, price=.2))
    fresh = _with_active_commitment(
        _bundle(captured_at=BASE + timedelta(seconds=1), price=.2)
    )
    loaded, executed = [observation, fresh], []

    def prepare(bundle):
        profile = store.current()
        return replace(bundle, snapshot=replace(
            bundle.snapshot, market_user_rule=profile.market_rule(),
            user_rule_revision=profile.revision,
            user_strategy_setting=profile.strategy_setting(),
        )), None

    monitor = RuntimeMonitorSession()
    _poll_live_cycle(
        previous_signature=None,
        load_bundle=lambda: loaded.pop(0), prepare_bundle=prepare,
        execute=lambda bundle, diagnostics: executed.append(bundle),
        runtime_monitor=monitor, runtime_now=lambda: BASE + timedelta(seconds=2),
    )
    assert not loaded
    assert len(executed) == 1
    assert executed[0].snapshot.snapshot_id == fresh.snapshot.snapshot_id
    assert executed[0].snapshot.market_user_rule is None
    assert executed[0].snapshot.user_rule_revision == store.current().revision
    assert executed[0].snapshot.user_strategy_setting.position == 0
    assert executed[0].snapshot.active_plan_commitments == fresh.snapshot.active_plan_commitments
    assert executed[0].snapshot.solcast_planning_basis == fresh.snapshot.solcast_planning_basis


def test_strategy_revision_is_material_even_when_both_market_rules_are_absent(
    tmp_path, monkeypatch,
):
    _, snapshot, producer = prepared(tmp_path, monkeypatch)
    store = UserRuleStore(tmp_path / "strategy.json", migrated_trading_soc_percent=0)
    first = store.current()
    before = replace(snapshot, market_user_rule=None, user_rule_revision=first.revision,
                     user_strategy_setting=first.strategy_setting())
    producer.observe(bundle(before))
    second = store.update(strategy_position=0)
    after = replace(before, user_rule_revision=second.revision,
                    user_strategy_setting=second.strategy_setting())
    observed = producer.observe(bundle(after))
    assert len(observed) == 1
    assert observed[0].kind is RuntimeObservationKind.USER_RULES_CHANGED
    assert observed[0].material_transition
