from __future__ import annotations

from picot.addon.live_flow_observer import LiveFlowObserver


def test_discharge_while_exporting_becomes_persistent_after_three_samples() -> None:
    observer = LiveFlowObserver(required_consecutive_samples=3)
    event: dict[str, object] = {
        "grid_export_w": 350.0,
        "zendure_discharge_power_w": 500.0,
        "goodwe_solar_power_w": 1800.0,
    }

    first = observer.evaluate(event)
    second = observer.evaluate(event)
    third = observer.evaluate(event)

    assert first["flow_observer_raw_mismatch"] is True
    assert first["flow_observer_persistent_mismatch"] is False
    assert second["flow_observer_consecutive_samples"] == 2
    assert third["flow_observer_persistent_mismatch"] is True
    assert third["flow_observer_recommendation"] == (
        "stop_discharge_and_reassess_pv_charge"
    )
    assert third["flow_observer_control_change_allowed"] is False


def test_consistent_flow_resets_debounce_counter() -> None:
    observer = LiveFlowObserver(required_consecutive_samples=3)
    mismatch = {
        "grid_export_w": 200.0,
        "zendure_discharge_power_w": 300.0,
        "goodwe_solar_power_w": 1200.0,
    }
    consistent = {
        "grid_export_w": 0.0,
        "zendure_discharge_power_w": 300.0,
        "goodwe_solar_power_w": 1200.0,
    }

    observer.evaluate(mismatch)
    result = observer.evaluate(consistent)

    assert result["flow_observer_status"] == "flow_consistent"
    assert result["flow_observer_consecutive_samples"] == 0
    assert result["flow_observer_persistent_mismatch"] is False
