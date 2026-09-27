import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest
from test_financial_result_ledger import _snapshot
from test_v2_financial_measurement_inference import _night_history, _with_soc

from picot.v2.financial_measurement_inference import financial_night_windows
from picot.v2.financial_measurement_observer import FinancialMeasurementObserver
from picot.v2.financial_result_ledger import FinancialResultLedger
from picot.v2.grid_charge_review import ReviewSettings
from picot.v2.power_history import numeric_power_history
from picot.v2.sun_state_history import HomeAssistantSunStateHistoryReader


def test_recorded_sun_state_proves_night_without_unrecorded_attributes(monkeypatch, tmp_path):
    h = _with_soc(_night_history())
    # Standard Recorder records the state, not elevation, azimuth or next_setting.
    payload = [[{"entity_id": "sun.sun", "state": "below_horizon", "attributes": {},
                 "last_updated": (h.starts_at - timedelta(hours=2)).isoformat()}]]

    @contextmanager
    def urlopen(request, timeout):
        class Response:
            def read(self):
                return json.dumps(payload).encode()
        yield Response()

    monkeypatch.setattr("picot.v2.sun_state_history.urlopen", urlopen)
    solar = HomeAssistantSunStateHistoryReader("test").read(
        starts_at=h.starts_at, ends_at=h.ends_at)
    windows = financial_night_windows(solar, h.starts_at, h.ends_at)
    assert len(windows) == 1
    assert (windows[0].starts_at, windows[0].ends_at) == (h.starts_at, h.ends_at)
    ledger = FinancialResultLedger(state_path=tmp_path / "ledger.json")
    numeric = numeric_power_history(h)
    raw = replace(numeric, series=tuple(s for s in numeric.series if s.role != "storage_soc"))
    snapshot = _snapshot()
    ledger.update(snapshot, raw, measurement_history=h)
    observer = FinancialMeasurementObserver(ledger=ledger,
        night_reader=HomeAssistantSunStateHistoryReader("test"),
        publish=lambda _: None, pv_maximum_power_w=4200)
    observer(snapshot, h, snapshot.price_points, ReviewSettings(8160, .1, 1, 2400, 2400, 1, 1, .05),
             False)
    today = ledger.dashboard_view()["today"]
    assert today["status"] == "incomplete"  # Original accounting is untouched.
    assert today["financial_metrics"]["status"] == "estimated"
    assert all(v["value_eur"] is not None for v in today["financial_metrics"]["values"].values())


def _read_payload(monkeypatch, payload):
    @contextmanager
    def urlopen(request, timeout):
        assert timeout == 5
        query = parse_qs(urlparse(request.full_url).query)
        assert query["filter_entity_id"] == ["sun.sun"]
        assert query["no_attributes"] == ["true"]
        # Retain Recorder's start anchor and full state identities/timestamps.
        assert "skip_initial_state" not in query
        assert "minimal_response" not in query

        class Response:
            def read(self):
                return json.dumps(payload).encode()
        yield Response()

    monkeypatch.setattr("picot.v2.sun_state_history.urlopen", urlopen)
    return HomeAssistantSunStateHistoryReader("test").read(
        starts_at=datetime(2026, 9, 27, tzinfo=UTC),
        ends_at=datetime(2026, 9, 27, 8, tzinfo=UTC))


def _state(at, state):
    return {"entity_id": "sun.sun", "last_updated": at, "state": state}


def test_unknown_state_is_retained_as_a_break_in_night_evidence(monkeypatch):
    result = _read_payload(monkeypatch, [[
        _state("2026-09-26T20:00:00Z", "below_horizon"),
        _state("2026-09-27T03:00:00Z", "unknown"),
        _state("2026-09-27T04:00:00Z", "below_horizon"),
        _state("2026-09-27T05:30:00Z", "above_horizon"),
    ]])
    windows = financial_night_windows(result, result.starts_at, result.ends_at)
    assert [(w.starts_at.hour, w.ends_at.hour, w.ends_at.minute) for w in windows] == [
        (0, 3, 0), (4, 5, 30)]
    assert result.observations[1].state == "unavailable"


@pytest.mark.parametrize("payload,reason", [
    ([], "no_sun_state_observations"),
    ({"error": "unavailable"}, "invalid_sun_state_history"),
    ([[{}]], "invalid_sun_state_history"),
    ([[_state("2026-09-26T20:00:00Z", "below_horizon"), {}]], "invalid_sun_state_history"),
    ([[{"entity_id": "sun.sun", "state": "below_horizon"}]], "invalid_sun_state_timestamp"),
    ([[_state("2026-09-27T01:00:00", "below_horizon")]], "invalid_sun_state_timestamp"),
    ([[_state("2026-09-27T01:00:00Z", "below_horizon"),
       _state("2026-09-27T01:00:00Z", "above_horizon")]], "ambiguous_sun_state_history"),
])
def test_invalid_or_missing_response_does_not_prove_night(monkeypatch, payload, reason):
    result = _read_payload(monkeypatch, payload)
    assert result.error == reason
    assert not financial_night_windows(result, result.starts_at, result.ends_at)


def test_future_record_is_not_a_start_anchor(monkeypatch):
    result = _read_payload(monkeypatch, [[
        _state("2026-09-27T01:00:00Z", "below_horizon"),
        _state("2026-09-28T05:30:00Z", "above_horizon"),
    ]])
    windows = financial_night_windows(result, result.starts_at, result.ends_at)
    assert len(windows) == 1
    assert windows[0].starts_at.hour == 1
    assert windows[0].ends_at == result.ends_at


def test_reader_transport_failure_is_explicit_and_contains_no_token(monkeypatch):
    def unavailable(*args, **kwargs):
        raise URLError("sensitive transport detail")

    monkeypatch.setattr("picot.v2.sun_state_history.urlopen", unavailable)
    result = HomeAssistantSunStateHistoryReader("private-token").read(
        starts_at=datetime(2026, 9, 27, tzinfo=UTC),
        ends_at=datetime(2026, 9, 27, 8, tzinfo=UTC))
    assert result.status == "unavailable" and result.error == "URLError"
    assert "private-token" not in repr(result)
    assert "sensitive" not in repr(result)


def test_reader_limits_record_count(monkeypatch):
    start = datetime(2026, 9, 27, tzinfo=UTC)
    result = _read_payload(monkeypatch, [[
        _state((start + timedelta(seconds=n)).isoformat(), "below_horizon")
        for n in range(4097)
    ]])
    assert result.error == "sun_state_history_resource_limit"
