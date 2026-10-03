from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest

from picot.v2.diagnostic_downloads import diagnostic_zip
from picot.v2.household_calendar_history import HouseholdCalendarHistory
from picot.v2.household_calendar_runtime import start_calendar_observer
from picot.v2.household_load_forecast import build_historical_household_load_forecast
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.passive_history.calendar import AMSTERDAM, bounds


def line(stamp: datetime, power: float) -> str:
    return json.dumps({"schema_version": 1, "sampled_at": stamp.isoformat(),
                       "power_w": power, "evidence_ids": ["source-1"],
                       "method_version": "complete-power-balance:v1"}) + "\n"


def drain(history: HouseholdCalendarHistory, source) -> None:
    for _ in range(1000):
        result = history.ingest_batch(source, free_reserve=0)
        if result["caught_up"]:
            return
    raise AssertionError("bounded import did not finish")


def test_resume_transaction_crosses_midnight_without_duplicate_energy(tmp_path):
    source = tmp_path / "source.jsonl"
    start = datetime(2026, 10, 2, 23, 59, tzinfo=AMSTERDAM)
    source.write_text("".join(line(start + timedelta(minutes=i), 600) for i in range(4)))
    original = source.read_bytes()
    path = tmp_path / "calendar.sqlite"
    history = HouseholdCalendarHistory(path)
    assert history.ingest_batch(source, limit=2, free_reserve=0)["caught_up"] is False
    history.close()
    history = HouseholdCalendarHistory(path)
    drain(history, source)
    first = history.report(now=start + timedelta(days=2))
    assert [d["weekday_name"] for d in first["days"]] == ["vrijdag", "zaterdag"]
    assert [d["observed_energy_wh"] for d in first["days"]] == pytest.approx([10, 20])
    assert first["source_progress"]["accepted"] == 4
    drain(history, source)
    assert history.report(now=start + timedelta(days=2)) == first
    assert history.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert source.read_bytes() == original
    history.close()


def test_long_gap_and_invalid_record_are_not_filled(tmp_path):
    source = tmp_path / "source.jsonl"
    start = datetime(2026, 10, 2, 10, tzinfo=AMSTERDAM)
    source.write_text(line(start, 600) + line(start + timedelta(minutes=1), 600)
                      + "broken\n" + line(start + timedelta(minutes=2), 600)
                      + line(start + timedelta(hours=2), 600))
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    drain(history, source)
    report = history.report(now=start + timedelta(days=2))
    day = report["days"][0]
    assert day["observed_energy_wh"] == pytest.approx(10)
    assert sum(q["covered_us"] for q in day["quarters"]) == 60_000_000
    assert day["usable_for_profile"] is False
    assert report["weekday_summary"]["vrijdag"]["eligible_days"] == 0
    assert report["source_progress"]["rejected"] == 1
    history.close()


def test_partial_source_line_waits_for_newline(tmp_path):
    source = tmp_path / "source.jsonl"
    stamp = datetime(2026, 10, 2, tzinfo=UTC)
    source.write_text(line(stamp, 100).rstrip("\n"))
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    result = history.ingest_batch(source, free_reserve=0)
    assert result["offset_bytes"] == 0
    assert result["accepted"] == 0
    assert result["caught_up"] is False
    with source.open("a") as handle:
        handle.write("\n")
    drain(history, source)
    assert history.report(now=stamp)["source_progress"]["accepted"] == 1
    history.close()


def test_rotated_source_replay_skips_old_measurements(tmp_path):
    source = tmp_path / "source.jsonl"
    stamp = datetime(2026, 10, 2, tzinfo=UTC)
    source.write_text(line(stamp, 600) + line(stamp + timedelta(minutes=1), 600))
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    drain(history, source)
    source.rename(tmp_path / "old.jsonl")
    source.write_text(line(stamp, 600) + line(stamp + timedelta(minutes=1), 600)
                      + line(stamp + timedelta(minutes=2), 600)
                      + line(stamp + timedelta(minutes=3), 600))
    drain(history, source)
    report = history.report(now=stamp + timedelta(days=1))
    assert report["source_progress"]["accepted"] == 4
    assert report["source_progress"]["skipped_old"] == 2
    # Rotation is an evidence discontinuity: no guessed bridge over it.
    assert report["days"][0]["observed_energy_wh"] == pytest.approx(20)
    history.close()


@pytest.mark.parametrize("day,count", [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)])
def test_dst_day_has_correct_quarters_and_energy(tmp_path, day, count):
    start, end = bounds(day)
    source = tmp_path / "source.jsonl"
    source.write_text("".join(line(datetime.fromtimestamp(t / 1_000_000, UTC), 1000)
                              for t in range(start, end + 1, 60_000_000)))
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    drain(history, source)
    report = history.report(now=datetime.fromtimestamp(end / 1_000_000, UTC)
                            + timedelta(days=1))
    result = report["days"][0]
    assert result["expected_quarters"] == count
    assert result["coverage_fraction"] == pytest.approx(1)
    assert result["observed_energy_wh"] == pytest.approx(count * 250)
    assert len(result["quarters"]) == count
    history.close()


def test_batch_error_rolls_back_both_values_and_cursor(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    stamp = datetime(2026, 10, 2, tzinfo=UTC)
    source.write_text(line(stamp, 600) + line(stamp + timedelta(minutes=1), 600))
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    real = history._integrate

    def failure(*args):
        real(*args)
        raise OSError("interrupted transaction")

    monkeypatch.setattr(history, "_integrate", failure)
    with pytest.raises(OSError):
        history.ingest_batch(source, free_reserve=0)
    assert history.db.execute("SELECT count(*) FROM quarter").fetchone()[0] == 0
    assert history.db.execute("SELECT count(*) FROM checkpoint").fetchone()[0] == 0
    monkeypatch.setattr(history, "_integrate", real)
    drain(history, source)
    assert history.report(now=stamp)["source_progress"]["accepted"] == 2
    history.close()


def test_publication_and_diagnostic_export_include_separate_calendar(tmp_path):
    source = tmp_path / "source.jsonl"
    stamp = datetime(2026, 10, 2, tzinfo=UTC)
    source.write_text(line(stamp, 200))
    report = tmp_path / "picot_v2_household_calendar.json"
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    drain(history, source)
    history.publish(report, now=stamp)
    with ZipFile(BytesIO(diagnostic_zip((source, report)))) as archive:
        result = json.loads(archive.read(report.name))
        assert result["observer_only"] is True
        assert result["source_progress"]["caught_up"] is True
        assert result["days"][0]["closed"] is False
    assert not list(tmp_path.glob("*.pending"))
    history.close()


def test_retrospective_weekday_comparison_uses_only_prior_days(tmp_path):
    source = tmp_path / "source.jsonl"
    first = datetime(2026, 8, 3, 10, tzinfo=AMSTERDAM)  # Monday
    records = []
    for day in range(29):
        stamp = first + timedelta(days=day)
        power = 1200 if stamp.weekday() >= 5 else 200
        records.extend(line(stamp + timedelta(minutes=i), power) for i in range(16))
    source.write_text("".join(records))
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    drain(history, source)
    report = history.report(now=first + timedelta(days=30))
    comparison = report["model_comparison"]
    assert comparison["common_quarters"] > 0
    assert comparison["models"]["same_weekday"]["mean_absolute_quarter_error_wh"] < 0.001
    assert comparison["models"]["workday_weekend"]["mean_absolute_quarter_error_wh"] < 0.001
    assert comparison["models"]["current_clock_quarter"]["mean_absolute_quarter_error_wh"] > 20
    monday = report["quarter_profiles"]["maandag"][40]
    assert monday["expected_energy_wh"] == pytest.approx(50)
    last_day = report["days"][-1]
    frozen = last_day["retrospective_comparison"]
    # Appending a future high-load Monday must not leak into prior-day scoring.
    with source.open("a") as handle:
        future = first + timedelta(days=35)
        handle.write("".join(line(future + timedelta(minutes=i), 9000) for i in range(16)))
    drain(history, source)
    new_report = history.report(now=first + timedelta(days=40))
    same = next(d for d in new_report["days"] if d["local_date"] == last_day["local_date"])
    assert same["retrospective_comparison"] == frozen
    history.close()


def test_baseline_comparison_matches_existing_forecaster(tmp_path):
    from picot.v2.household_calendar_report import _predictions

    source = tmp_path / "source.jsonl"
    start = datetime(2026, 8, 3, 10, tzinfo=UTC)
    source.write_text("".join(line(start + timedelta(days=d, minutes=i), (d + 1) * 100)
                              for d in range(15) for i in range(16)))
    observations = HouseholdLoadHistoryStore(source).load()
    target = start + timedelta(days=14)
    baseline = build_historical_household_load_forecast(
        run_id="r", snapshot_id="s", starts_at=target,
        horizon_end=target + timedelta(minutes=15),
        observations=tuple(o for o in observations if o.sampled_at < target),
    )
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    drain(history, source)
    rows = [dict(q) for q in history.db.execute("SELECT * FROM quarter")]
    by_utc = {q["start_us"]: q for q in rows}
    row = by_utc[int(target.timestamp() * 1_000_000)]
    predictions = _predictions(row, by_utc, {row["clock_quarter"]: rows})
    assert baseline is not None
    assert predictions["current_clock_quarter"] == pytest.approx(
        baseline.intervals[0].expected_energy_wh)
    history.close()


def test_observer_default_enabled_and_child_has_no_supervisor_token(tmp_path, monkeypatch):
    import picot.v2.household_calendar_runtime as runtime

    calls = []

    class Child:
        pid = 123

    def launch(*args, **kwargs):
        calls.append((args, kwargs))
        return Child()

    monkeypatch.setenv("SUPERVISOR_TOKEN", "private")
    monkeypatch.setattr(runtime.subprocess, "Popen", launch)
    assert start_calendar_observer({}, source=tmp_path / "source") is not None
    assert "SUPERVISOR_TOKEN" not in calls[0][1]["env"]
    assert start_calendar_observer({"household_calendar_history_enabled": False},
                                   source=tmp_path / "source") is None
    assert len(calls) == 1


def test_observer_start_failure_never_propagates(tmp_path, monkeypatch):
    import picot.v2.household_calendar_runtime as runtime

    def unavailable(*args, **kwargs):
        raise OSError("cannot launch observer")

    monkeypatch.setattr(runtime.subprocess, "Popen", unavailable)
    assert start_calendar_observer({}, source=tmp_path / "source") is None


def test_storage_pressure_pauses_without_consuming_source(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text(line(datetime.now(UTC), 600))
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    assert history.ingest_batch(source, free_reserve=10**30)["state"] == "paused_storage"
    assert history.db.execute("SELECT count(*) FROM checkpoint").fetchone()[0] == 0
    history.close()


def test_unsupported_database_is_not_reinitialised(tmp_path):
    path = tmp_path / "calendar.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=9")
    with pytest.raises(ValueError, match="unsupported"):
        HouseholdCalendarHistory(path)


def test_calendar_http_view_is_independent_of_pipeline_and_bounded(tmp_path):
    from threading import Thread
    from urllib.request import urlopen

    from picot.v2.web_ui import WebViewStore, create_web_server

    report = tmp_path / "picot_v2_household_calendar.json"
    source = tmp_path / "source.jsonl"
    now = datetime(2026, 10, 2, tzinfo=UTC)
    source.write_text(line(now, 200))
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    drain(history, source)
    history.publish(report, now=now)
    history.close()
    store = WebViewStore()
    store.set_diagnostic_paths((report,), incident_history_path=source)
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/household-calendar",
                     timeout=2) as response:
            data = json.loads(response.read())
        assert data["status"] == "ready"
        assert "quarters" not in data["days"][0]
        assert "retrospective_comparison" not in data["days"][0]
        assert store.latest_json() is None  # No planning run required or invented.
        report.write_text("broken")
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/household-calendar",
                     timeout=2) as response:
            assert json.loads(response.read())["status"] == "unavailable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_calendar_report_failure_preserves_previous_publication(tmp_path, monkeypatch):
    history = HouseholdCalendarHistory(tmp_path / "calendar.sqlite")
    report = tmp_path / "report.json"
    now = datetime(2026, 10, 2, tzinfo=UTC)
    history.publish(report, now=now)
    previous = report.read_bytes()

    def failure(*args, **kwargs):
        raise OSError("publish failed")

    monkeypatch.setattr("picot.v2.household_calendar_history.os.replace", failure)
    with pytest.raises(OSError):
        history.publish(report, now=now + timedelta(days=1))
    assert report.read_bytes() == previous
    assert not list(tmp_path.glob("*.pending"))
    history.close()


def test_dead_observer_restarts_with_backoff_without_waiting(tmp_path, monkeypatch):
    import picot.v2.household_calendar_runtime as runtime

    calls = []

    class Child:
        def poll(self):
            return 1

    monkeypatch.setattr(runtime, "start_calendar_observer",
                        lambda options, *, source: calls.append(source))
    child = Child()
    source = tmp_path / "source.jsonl"
    assert runtime.maintain_calendar_observer(child, {}, source=source, now=1,
                                             restart_after=300) == (child, 300)
    assert calls == []
    assert runtime.maintain_calendar_observer(child, {}, source=source, now=301,
                                             restart_after=300) == (None, 601)
    assert calls == [source]
    assert runtime.maintain_calendar_observer(None, {}, source=source, now=302,
                                             restart_after=601) == (None, 601)
    assert calls == [source]
