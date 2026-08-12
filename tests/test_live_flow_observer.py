from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.addon.live_flow_observer import LiveFlowObserver


BASE = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)


def _event(
    *,
    at: datetime,
    mode: str,
    grid_import: float = 0.0,
    grid_export: float = 0.0,
    discharge: float = 0.0,
    charge: float = 0.0,
    pv: float = 0.0,
) -> dict[str, object]:
    return {
        "telemetry_updated_at": at.isoformat(),
        "zendure_requested_mode": mode,
        "grid_import_w": grid_import,
        "grid_export_w": grid_export,
        "zendure_discharge_power_w": discharge,
        "zendure_charge_power_w": charge,
        "goodwe_solar_power_w": pv,
    }


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
