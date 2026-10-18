from datetime import UTC, datetime, timedelta

from picot_energy_devices.regulation import PowerReport, RegulationObserver


def evaluate(observer, second, *, ev=2.2, raw=61.285, age=0):
    now = datetime(2026, 10, 18, tzinfo=UTC) + timedelta(seconds=second)
    return observer.evaluate(PowerReport(raw, now), PowerReport(0, now),
                             PowerReport(ev, now - timedelta(seconds=age)), now=now)


def test_confirmed_idle_tracks_every_raw_change_without_rounding():
    observer = RegulationObserver()
    for second in range(30):
        result = evaluate(observer, second)
        assert result["quantization_w"] == 20
    for second, raw in enumerate([33.763, 61.285, -18.432, 42.78], start=30):
        result = evaluate(observer, second, raw=raw)
        assert result["candidate_w"] == raw
        assert result["quantization_w"] == 0
        assert result["excluded_ev_w"] == 0


def test_charging_resumes_correction_immediately():
    observer = RegulationObserver()
    for second in range(31):
        evaluate(observer, second)
    result = evaluate(observer, 31, ev=2300, raw=2500)
    assert result["candidate_w"] == 200
    assert result["excluded_ev_w"] == 2300


def test_missing_or_stale_measurement_cannot_confirm_idle():
    observer = RegulationObserver()
    for second in range(29):
        evaluate(observer, second)
    assert evaluate(observer, 29, age=10)["status"] == "blocked"
    assert evaluate(observer, 30)["quantization_w"] == 20
    assert evaluate(observer, 90)["quantization_w"] == 20


def test_repeated_report_cannot_advance_idle_confirmation():
    observer = RegulationObserver()
    for second in range(31):
        evaluate(observer, second, age=second)
    assert evaluate(observer, 31)["quantization_w"] == 20
