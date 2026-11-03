from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from picot_hc.core import Store
from picot_hc.day_ahead import DayAhead, build, conditions
from picot_hc.energy_model import EnergyModel
from picot_hc.schedule import TZ, wall_time
from picot_hc.warmup_energy import WarmupEnergy


def setup(tmp_path, day="2026-11-03"):
    now = datetime.fromisoformat(day + "T12:00:00").replace(tzinfo=TZ).timestamp()
    store = Store(tmp_path / "forecast.sqlite")
    model, warmup = EnergyModel(store), WarmupEnergy(store)
    record = dict(
        source_id="a" * 64,
        identity="room",
        target=20,
        indoor=20,
        outdoor=10,
        measured_at=now - 100,
        mean_power_w=600,
        used_wh=300,
        duration_seconds=1800,
    )
    model.records = [record]
    warmup.records = [dict(record, indoor=17, used_wh=1200, duration_seconds=3600)]
    context = dict(valid=True, indoor=18, outdoor=10, identity="room")
    settings = dict(
        enabled=True,
        learning_enabled=True,
        initial_preheat_minutes=45,
        max_preheat_minutes=180,
        setback_temperature=17,
        optimization_band=1,
        windows=[dict(day=d, start="18:00", end="22:00", target=20, hard=True) for d in range(7)],
    )
    cooling = SimpleNamespace(samples=[], estimate=lambda c, n: dict(cooling_rate=0.5))
    args = (settings, True, context, "a" * 64, model, warmup, cooling, {}, {}, now)
    return store, args


def test_noon_covers_tomorrow_warmup_and_maintenance_without_hems(tmp_path):
    _, args = setup(tmp_path)
    value = build(*args)
    assert value["status"] == "provisional"
    assert value["execution_authorized"] is False
    assert value["delivery_date"] == "2026-11-04"
    rows = [s for s in value["slots"] if s["starts_at"].startswith("2026-11-04")]
    assert any(s["phase"] == "warmup" and s["energy_wh"] > 0 for s in rows)
    assert any(s["phase"] == "maintain" and s["energy_wh"] > 0 for s in rows)
    assert all(a["ends_at"] == b["starts_at"] for a, b in zip(rows, rows[1:], strict=False))


@pytest.mark.parametrize("day,hours", [("2026-03-28", 35), ("2026-10-24", 37)])
def test_actual_dst_duration_is_preserved(tmp_path, day, hours):
    _, args = setup(tmp_path, day)
    value = build(*args)
    assert value["slots"]
    start = datetime.fromisoformat(value["slots"][0]["starts_at"])
    end = datetime.fromisoformat(value["slots"][-1]["ends_at"])
    assert (end - start).total_seconds() == hours * 3600


def test_unknown_energy_is_not_zero_demand(tmp_path):
    _, args = setup(tmp_path)
    args[4].records = []
    value = build(*args)
    assert value["status"] == "unavailable" and value["slots"] == []
    assert "no_energy_measurements" in value["reasons"]


def test_forecast_is_saved_republished_after_restart_and_withdrawn(tmp_path):
    store, args = setup(tmp_path)
    sent = []
    publisher = SimpleNamespace(submit=sent.append)
    first = DayAhead(store, publisher)
    first.tick(*args)
    restored = DayAhead(store, publisher)
    assert restored.view() == first.view()
    restored.tick(*args)
    assert sent[-1]["attributes"]["revision"] == first.view()["revision"]
    changed = list(args)
    changed[1] = False
    restored.tick(*changed)
    assert sent[-1]["state"] == "disabled"
    assert not restored.view()["slots"]


def test_daily_weather_is_labelled_scenario_and_hourly_has_priority(tmp_path):
    _, args = setup(tmp_path)
    now = args[-1]
    tomorrow = datetime.fromtimestamp(now, TZ).date() + timedelta(days=1)
    at = wall_time(tomorrow, 18 * 60)
    daily = dict(
        stale=False,
        temperature_unit="°C",
        rows=[dict(time=wall_time(tomorrow, 0), temperature=12, templow=5)],
    )
    assert conditions({}, daily, at, now, 10) == (5, None, "daily_cold_side_scenario")
    hourly = dict(
        status="ready",
        received=now,
        intervals=[dict(starts_at=at, ends_at=at + 3600, outdoor=8, weather={})],
    )
    assert conditions(hourly, daily, at, now, 10)[::2] == (8, "hourly")


def test_noon_refresh_and_minor_temperature_changes_do_not_republish_plan(tmp_path):
    store, args = setup(tmp_path)
    publisher = SimpleNamespace(submit=lambda value: None)
    worker = DayAhead(store, publisher)
    before = list(args)
    before[-1] -= 60
    worker.tick(*before)
    first = worker.view()["revision"]
    worker.tick(*args)
    second = worker.view()["revision"]
    assert second != first
    small = list(args)
    small[2] = dict(args[2], indoor=args[2]["indoor"] + 0.01)
    small[-1] += 30
    worker.tick(*small)
    assert worker.view()["revision"] == second
    changed = list(args)
    changed[0] = dict(args[0], setback_temperature=18)
    changed[-1] += 60
    worker.tick(*changed)
    assert worker.view()["revision"] != second


def test_failure_withdraws_old_display_and_retries(tmp_path):
    store, args = setup(tmp_path)
    sent = []
    worker = DayAhead(store, SimpleNamespace(submit=sent.append))
    worker.tick(*args)
    worker.failed(args[-1] + 1)
    assert worker.view()["status"] == "unavailable"
    worker.tick(*args)
    assert worker.view()["slots"]
