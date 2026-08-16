from datetime import UTC, datetime, timedelta

from picot.v2.live_pv_mode_strategy import (
    LivePVModeInput,
    LivePVModeStrategy,
)

BASE = datetime(2026, 8, 16, 14, 0, tzinfo=UTC)
NOM = "Nul op de meter"
SMART_DISCHARGE = "Alleen slim ontladen"


def _input(
    *,
    now: datetime = BASE,
    current_mode: str = SMART_DISCHARGE,
    charge_window_active: bool = False,
    battery_power_w: float = 0.0,
    evidence_age_seconds: float = 0.0,
    manual_override_active: bool = False,
    live_enabled: bool = True,
) -> LivePVModeInput:
    return LivePVModeInput(
        now=now,
        current_vendor_mode=current_mode,
        charge_window_active=charge_window_active,
        battery_power_w=battery_power_w,
        evidence_age_seconds=evidence_age_seconds,
        manual_override_active=manual_override_active,
        live_enabled=live_enabled,
    )


def test_new_favourable_charge_window_requests_nom() -> None:
    decision = LivePVModeStrategy().evaluate(
        _input(charge_window_active=True)
    )

    assert decision.requested_vendor_mode == NOM
    assert decision.reason == "favourable_pv_charge_window_started"
    assert decision.dispatch_allowed is True


def test_nom_switches_to_smart_discharge_after_five_minute_turning_point() -> None:
    strategy = LivePVModeStrategy()

    first = strategy.evaluate(
        _input(current_mode=NOM, battery_power_w=-120.0)
    )
    early = strategy.evaluate(
        _input(
            now=BASE + timedelta(minutes=4, seconds=59),
            current_mode=NOM,
            battery_power_w=-120.0,
        )
    )
    ready = strategy.evaluate(
        _input(
            now=BASE + timedelta(minutes=5),
            current_mode=NOM,
            battery_power_w=-120.0,
        )
    )

    assert first.requested_vendor_mode is None
    assert early.requested_vendor_mode is None
    assert ready.requested_vendor_mode == SMART_DISCHARGE
    assert ready.reason == "battery_discharge_turning_point_sustained"


def test_brief_discharge_does_not_trigger_mode_change() -> None:
    strategy = LivePVModeStrategy()
    strategy.evaluate(_input(current_mode=NOM, battery_power_w=-120.0))

    strategy.evaluate(
        _input(
            now=BASE + timedelta(minutes=3),
            current_mode=NOM,
            battery_power_w=80.0,
        )
    )
    decision = strategy.evaluate(
        _input(
            now=BASE + timedelta(minutes=6),
            current_mode=NOM,
            battery_power_w=-120.0,
        )
    )

    assert decision.requested_vendor_mode is None
    assert decision.reason == "discharge_turning_point_pending"


def test_smart_discharge_is_held_for_at_least_fifteen_minutes() -> None:
    strategy = LivePVModeStrategy()
    strategy.record_applied_mode(SMART_DISCHARGE, applied_at=BASE)

    decision = strategy.evaluate(
        _input(
            now=BASE + timedelta(minutes=14, seconds=59),
            current_mode=SMART_DISCHARGE,
            charge_window_active=True,
        )
    )

    assert decision.requested_vendor_mode is None
    assert decision.reason == "smart_discharge_minimum_hold_active"


def test_new_charge_window_may_request_nom_after_hold_expires() -> None:
    strategy = LivePVModeStrategy()
    strategy.record_applied_mode(SMART_DISCHARGE, applied_at=BASE)

    decision = strategy.evaluate(
        _input(
            now=BASE + timedelta(minutes=15),
            current_mode=SMART_DISCHARGE,
            charge_window_active=True,
        )
    )

    assert decision.requested_vendor_mode == NOM


def test_manual_override_blocks_all_dispatch() -> None:
    decision = LivePVModeStrategy().evaluate(
        _input(
            charge_window_active=True,
            manual_override_active=True,
        )
    )

    assert decision.requested_vendor_mode is None
    assert decision.dispatch_allowed is False
    assert decision.reason == "manual_override_active"


def test_stale_evidence_blocks_all_dispatch() -> None:
    decision = LivePVModeStrategy().evaluate(
        _input(
            charge_window_active=True,
            evidence_age_seconds=61.0,
        )
    )

    assert decision.requested_vendor_mode is None
    assert decision.dispatch_allowed is False
    assert decision.reason == "evidence_stale"


def test_observer_mode_never_allows_dispatch() -> None:
    decision = LivePVModeStrategy().evaluate(
        _input(charge_window_active=True, live_enabled=False)
    )

    assert decision.requested_vendor_mode == NOM
    assert decision.dispatch_allowed is False
    assert decision.reason == "favourable_pv_charge_window_started"
