from datetime import UTC, datetime
from pathlib import Path

from test_v2_delegated_storage_pipeline_integration import (
    BASE,
    WINDOW_END,
    _snapshot,
)

from picot.v2.live_pv_canary_runtime import (
    LivePVCanaryRuntime,
    active_pv_charge_window,
)
from picot.v2.live_pv_mode_strategy import LivePVModeInput
from picot.v2.pipeline import CanonicalPipeline

NOW = datetime(2026, 8, 16, 14, 0, tzinfo=UTC)
TARGET = "input_select.zendure_2400_ac_modus_selecteren"


def _input(*, live_enabled: bool) -> LivePVModeInput:
    return LivePVModeInput(
        now=NOW,
        current_vendor_mode="Alleen slim ontladen",
        charge_window_active=True,
        battery_power_w=300.0,
        evidence_age_seconds=5.0,
        manual_override_active=False,
        live_enabled=live_enabled,
    )


def test_active_window_comes_from_winning_execution_plan() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())

    assert active_pv_charge_window(run, at=BASE) is True
    assert active_pv_charge_window(run, at=WINDOW_END) is False


def test_observer_canary_never_calls_home_assistant_dispatch() -> None:
    calls: list[tuple[str, str]] = []
    runtime = LivePVCanaryRuntime(
        dispatch=lambda mode, entity: calls.append((mode, entity)) or "dispatched"
    )

    result = runtime.apply(_input(live_enabled=False), target_entity=TARGET)

    assert calls == []
    assert result.status == "observer_only"
    assert result.requested_vendor_mode == "Nul op de meter"
    assert result.normal_result == (
        "PicoT zou Zendure nu naar Nul op de meter schakelen, "
        "maar de live-canary staat op Observer."
    )


def test_live_canary_dispatches_exact_mode_through_injected_adapter() -> None:
    calls: list[tuple[str, str]] = []
    runtime = LivePVCanaryRuntime(
        dispatch=lambda mode, entity: calls.append((mode, entity)) or "dispatched"
    )

    result = runtime.apply(_input(live_enabled=True), target_entity=TARGET)

    assert calls == [("Nul op de meter", TARGET)]
    assert result.status == "dispatched"
    assert result.normal_result == (
        "PicoT heeft Zendure naar Nul op de meter geschakeld "
        "voor het actieve PV-laadvenster."
    )


def test_duplicate_request_is_not_dispatched_twice_before_feedback() -> None:
    calls: list[tuple[str, str]] = []
    runtime = LivePVCanaryRuntime(
        dispatch=lambda mode, entity: calls.append((mode, entity)) or "dispatched"
    )

    runtime.apply(_input(live_enabled=True), target_entity=TARGET)
    duplicate = runtime.apply(_input(live_enabled=True), target_entity=TARGET)

    assert len(calls) == 1
    assert duplicate.status == "awaiting_mode_feedback"


def test_addon_defaults_live_canary_to_observer() -> None:
    config = Path("picot_hems/config.yaml").read_text(encoding="utf-8")

    assert '  live_pv_canary_mode: "observer"' in config
    assert "  live_pv_canary_mode: list(observer|live)" in config
    assert '  canonical_execution_mode: "observer"' in config
    assert (
        '  zendure_calibration_entity: "sensor.zendure_2400_ac_kalibreren"'
        in config
    )
    assert "  zendure_calibration_entity: str" in config
    assert "  canonical_execution_mode: list(observer|live)" in config
