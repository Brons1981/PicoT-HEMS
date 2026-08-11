from datetime import datetime, timedelta, timezone

from picot.addon.pv_deviation_evaluator import PvDeviationEvaluator


BASE = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)


def _event(
    minute: int,
    *,
    expected_w: float = 3000.0,
    actual_w: float = 3000.0,
    status: str = "available",
) -> dict[str, object]:
    return {
        "pv_forecast_comparison_status": status,
        "pv_expected_power_w": expected_w,
        "pv_actual_power_w": actual_w,
        "telemetry_updated_at": (BASE + timedelta(minutes=minute)).isoformat(),
        "solcast_today_confidence": 0.72,
    }


def test_requires_history_before_marking_persistent_deviation() -> None:
    evaluator = PvDeviationEvaluator()

    result = evaluator.evaluate(_event(0, actual_w=1800.0))
    assert result["pv_deviation_evaluator_status"] == "insufficient_history"
    assert result["pv_deviation_replan_candidate"] is False

    result = evaluator.evaluate(_event(5, actual_w=1800.0))
    assert result["pv_deviation_evaluator_status"] == "insufficient_history"
    assert result["pv_deviation_replan_candidate"] is False


def test_persistent_under_forecast_becomes_replan_candidate() -> None:
    evaluator = PvDeviationEvaluator()

    evaluator.evaluate(_event(0, actual_w=1800.0))
    evaluator.evaluate(_event(5, actual_w=1800.0))
    result = evaluator.evaluate(_event(10, actual_w=1800.0))

    assert result["pv_deviation_evaluator_status"] == "persistent_under_forecast"
    assert result["pv_rolling_deviation_percent"] == -40.0
    assert result["pv_deviation_history_seconds"] == 600.0
    assert result["pv_deviation_replan_candidate"] is True


def test_persistent_over_forecast_is_classified_separately() -> None:
    evaluator = PvDeviationEvaluator()

    evaluator.evaluate(_event(0, actual_w=4000.0))
    evaluator.evaluate(_event(5, actual_w=4000.0))
    result = evaluator.evaluate(_event(10, actual_w=4000.0))

    assert result["pv_deviation_evaluator_status"] == "persistent_over_forecast"
    assert round(float(result["pv_rolling_deviation_percent"]), 2) == 33.33
    assert result["pv_deviation_replan_candidate"] is True


def test_single_cloud_dip_does_not_become_persistent_under_forecast() -> None:
    evaluator = PvDeviationEvaluator()

    evaluator.evaluate(_event(0, actual_w=3000.0))
    evaluator.evaluate(_event(5, actual_w=1000.0))
    result = evaluator.evaluate(_event(10, actual_w=3000.0))

    assert result["pv_deviation_evaluator_status"] == "within_tolerance"
    assert round(float(result["pv_rolling_deviation_percent"]), 2) == -22.22
    assert result["pv_deviation_replan_candidate"] is False


def test_low_expected_power_is_not_used_for_percentage_classification() -> None:
    evaluator = PvDeviationEvaluator()

    result = evaluator.evaluate(_event(0, expected_w=200.0, actual_w=0.0))

    assert result["pv_deviation_evaluator_status"] == "low_expected_power"
    assert result["pv_rolling_deviation_percent"] is None
    assert result["pv_deviation_replan_candidate"] is False


def test_unavailable_comparison_cannot_become_replan_candidate() -> None:
    evaluator = PvDeviationEvaluator()

    result = evaluator.evaluate(_event(0, status="unavailable"))

    assert result["pv_deviation_evaluator_status"] == "unavailable"
    assert result["pv_deviation_replan_candidate"] is False


def test_energy_windows_integrate_expected_and_actual_energy() -> None:
    evaluator = PvDeviationEvaluator()

    result: dict[str, object] = {}
    for minute in range(0, 61, 5):
        result = evaluator.evaluate(
            _event(minute, expected_w=4000.0, actual_w=3800.0)
        )

    assert result["pv_energy_15m_status"] == "available"
    assert result["pv_energy_30m_status"] == "available"
    assert result["pv_energy_60m_status"] == "available"
    assert round(float(result["pv_energy_15m_expected_kwh"]), 3) == 1.0
    assert round(float(result["pv_energy_30m_expected_kwh"]), 3) == 2.0
    assert round(float(result["pv_energy_60m_expected_kwh"]), 3) == 4.0
    assert round(float(result["pv_energy_60m_actual_kwh"]), 3) == 3.8
    assert round(float(result["pv_energy_60m_deviation_percent"]), 2) == -5.0


def test_energy_windows_are_observation_only_for_replan_logic() -> None:
    evaluator = PvDeviationEvaluator()

    result: dict[str, object] = {}
    for minute in range(0, 61, 5):
        actual = 0.0 if minute < 30 else 6000.0
        result = evaluator.evaluate(_event(minute, expected_w=3000.0, actual_w=actual))

    assert result["pv_energy_60m_status"] == "available"
    assert result["pv_energy_60m_deviation_percent"] is not None
    assert result["pv_deviation_evaluator_status"] == "persistent_over_forecast"
    assert result["pv_deviation_replan_candidate"] is True
    # Replan remains driven by the existing 15-minute rolling evaluator, not
    # by any of the new 15/30/60-minute energy-window fields.
    assert "pv_energy_replan_candidate" not in result
