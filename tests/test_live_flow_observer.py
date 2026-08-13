from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.addon.live_flow_observer import LiveFlowObserver


BASE = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)


def _event(
    *,
    at: datetime,
    mode: str,
    requested_mode: str | None = None,
    execution_control_regime: str | None = None,
    grid_import: float = 0.0,
    grid_export: float = 0.0,
    discharge: float = 0.0,
    charge: float = 0.0,
    pv: float = 0.0,
) -> dict[str, object]:
    event: dict[str, object] = {
        "telemetry_updated_at": at.isoformat(),
        "zendure_actual_mode": mode,
        "zendure_requested_mode": requested_mode if requested_mode is not None else mode,
        "grid_import_w": grid_import,
        "grid_export_w": grid_export,
        "zendure_discharge_power_w": discharge,
        "zendure_charge_power_w": charge,
        "goodwe_solar_power_w": pv,
    }
    if execution_control_regime is not None:
        event["execution_control_regime"] = execution_control_regime
    return event


def test_nom_transient_contradiction_does_not_trigger_before_120_seconds() -> None:
    observer = LiveFlowObserver()
    observer.evaluate(
        _event(at=BASE, mode="Nul op de meter", grid_export=900, discharge=800, pv=700)
    )
    result = observer.evaluate(
        _event(
            at=BASE + timedelta(seconds=119),
            mode="Nul op de meter",
            grid_export=900,
            discharge=800,
            pv=700,
        )
    )

    assert result["flow_observer_control_regime"] == "delegated_bidirectional"
    assert result["flow_observer_validation_band"] == "red"
    assert result["flow_observer_persistent_mismatch"] is False


def test_nom_sustained_contradiction_triggers_at_120_seconds() -> None:
    observer = LiveFlowObserver()
    observer.evaluate(
        _event(at=BASE, mode="Nul op de meter", grid_export=900, discharge=800, pv=700)
    )
    result = observer.evaluate(
        _event(
            at=BASE + timedelta(seconds=120),
            mode="Nul op de meter",
            grid_export=900,
            discharge=800,
            pv=700,
        )
    )

    assert result["flow_observer_discharge_while_exporting"] is True
    assert result["flow_observer_persistent_mismatch"] is True
    assert result["flow_observer_recommendation"] == "replan_from_flow_validation"


def test_smart_discharge_red_band_is_actionable_after_120_seconds() -> None:
    observer = LiveFlowObserver()
    green = observer.evaluate(
        _event(at=BASE, mode="Alleen slim ontladen", grid_import=40)
    )
    observer.evaluate(
        _event(at=BASE + timedelta(seconds=1), mode="Alleen slim ontladen", grid_import=180)
    )
    result = observer.evaluate(
        _event(at=BASE + timedelta(seconds=121), mode="Alleen slim ontladen", grid_import=180)
    )

    assert green["flow_observer_validation_band"] == "green"
    assert result["flow_observer_validation_band"] == "red"
    assert result["flow_observer_persistent_mismatch"] is True


def test_smart_discharge_grey_band_is_actionable_after_300_seconds() -> None:
    observer = LiveFlowObserver()
    observer.evaluate(_event(at=BASE, mode="Alleen slim ontladen", grid_import=100))
    result = observer.evaluate(
        _event(at=BASE + timedelta(seconds=300), mode="Alleen slim ontladen", grid_import=100)
    )

    assert result["flow_observer_validation_band"] == "grey"
    assert result["flow_observer_persistent_mismatch"] is True


def test_regime_change_resets_elapsed_timers() -> None:
    observer = LiveFlowObserver()
    observer.evaluate(_event(at=BASE, mode="Alleen slim ontladen", grid_import=200))
    result = observer.evaluate(
        _event(
            at=BASE + timedelta(seconds=119),
            mode="Nul op de meter",
            pv=500,
        )
    )

    assert result["flow_observer_control_regime"] == "delegated_bidirectional"
    assert result["flow_observer_validation_band"] == "green"
    assert result["flow_observer_red_elapsed_s"] == 0.0


def test_standby_validates_battery_power_instead_of_grid_baseline() -> None:
    observer = LiveFlowObserver()
    result = observer.evaluate(
        _event(
            at=BASE,
            mode="Standby",
            grid_import=2200,
            discharge=20,
        )
    )

    assert result["flow_observer_control_regime"] == "standby"
    assert result["flow_observer_validation_band"] == "green"


def test_actual_standby_wins_over_stale_requested_smart_discharge() -> None:
    observer = LiveFlowObserver()
    result = observer.evaluate(
        _event(
            at=BASE,
            mode="Standby",
            requested_mode="Alleen slim ontladen",
            grid_export=2050,
            discharge=0,
            charge=0,
            pv=2270,
        )
    )

    assert result["flow_observer_control_regime"] == "standby"
    assert result["flow_observer_regime_source"] == "actual_device_mode"
    assert result["flow_observer_validation_band"] == "green"
    assert result["flow_observer_persistent_mismatch"] is False
    assert result["flow_observer_recommendation"] == "observe"


def test_canonical_execution_regime_overrides_actual_device_mode_when_present() -> None:
    observer = LiveFlowObserver()
    result = observer.evaluate(
        _event(
            at=BASE,
            mode="Standby",
            execution_control_regime="delegated_discharge_only",
            grid_import=20,
        )
    )

    assert result["flow_observer_control_regime"] == "delegated_discharge_only"
    assert result["flow_observer_regime_source"] == "execution_intent"
    assert result["flow_observer_validation_band"] == "green"
