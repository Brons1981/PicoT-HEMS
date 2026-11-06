from datetime import datetime
from types import SimpleNamespace

from picot_hc.day_ahead import DayAhead
from picot_hc.schedule import TZ
from test_day_ahead import setup


def test_unknown_warmup_preserves_release_and_never_publishes_temperatures(tmp_path):
    store, args = setup(tmp_path)
    args = list(args)
    args[-1] = datetime(2026, 11, 3, 21, 30, tzinfo=TZ).timestamp()
    args[0]["windows"] = [
        dict(day=d, start=a, end=b, target=t, hard=h)
        for d in range(7)
        for a, b, t, h in [
            ("00:00", "18:00", 17, False),
            ("18:00", "22:00", 20, True),
            ("22:00", "00:00", 17, False),
        ]
    ]
    args[2]["indoor"] = 18.5
    args[5].records = []
    sent = []
    model = DayAhead(store, SimpleNamespace(submit=sent.append))
    model.tick(*args)
    published = sent[-1]
    assert published["state"] == "partial"
    value = published["attributes"]
    assert value["load_facts"]
    releases = [r for r in value["load_facts"] if r["operation"] == "load_released"]
    assert releases and releases[0]["starts_at"].startswith("2026-11-03T21:00")
    assert releases[0]["energy_wh"] == 0
    assert any(r["energy_wh"] is None for r in value["load_facts"])
    assert all("target" not in r for r in value["slots"])
    assert all("target" not in r for r in value["load_facts"])
    # Restart preserves the independently usable facts.
    assert DayAhead(store, SimpleNamespace(submit=lambda x: None)).view() == model.view()


def test_bad_measurements_keep_timing_but_do_not_invent_zero(tmp_path):
    store, args = setup(tmp_path)
    args[2]["valid"] = False
    sent = []
    model = DayAhead(store, SimpleNamespace(submit=sent.append))
    model.tick(*args)
    facts = sent[-1]["attributes"]["load_facts"]
    assert facts and any(r["operation"] == "load_expected" for r in facts)
    assert all(r["energy_wh"] is None for r in facts)


def test_model_failure_keeps_schedule_and_cooling_facts(tmp_path):
    store, args = setup(tmp_path)
    args = list(args)
    args[-1] = datetime(2026, 11, 3, 21, 30, tzinfo=TZ).timestamp()
    args[0]["windows"].extend(
        dict(day=d, start="22:00", end="00:00", target=17, hard=False) for d in range(7)
    )
    args[5].estimate = lambda *a: (_ for _ in ()).throw(ValueError("broken warmup"))
    sent = []
    DayAhead(store, SimpleNamespace(submit=sent.append)).tick(*args)
    value = sent[-1]["attributes"]
    assert value["status"] == "partial"
    assert "forecast_generation_failed" in value["reasons"]
    assert any(f["energy_wh"] == 0 for f in value["load_facts"])


def test_missing_cooling_does_not_erase_maintenance_energy(tmp_path):
    store, args = setup(tmp_path)
    args = list(args)
    args[-1] = datetime(2026, 11, 3, 21, 30, tzinfo=TZ).timestamp()
    args[2]["indoor"] = 20
    args[5].records = []
    args[6] = SimpleNamespace(samples=[], estimate=lambda *a: dict(cooling_rate=None))
    sent = []
    DayAhead(store, SimpleNamespace(submit=sent.append)).tick(*args)
    assert any(
        f["energy_wh"] is not None and f["energy_wh"] > 0
        for f in sent[-1]["attributes"]["load_facts"]
    )


def test_complete_public_forecast_contains_no_climate_targets(tmp_path):
    store, args = setup(tmp_path)
    sent = []
    DayAhead(store, SimpleNamespace(submit=sent.append)).tick(*args)
    value = sent[-1]["attributes"]
    assert value["slots"] and value["status"] in ("ready", "provisional")
    assert all("target" not in row for row in value["slots"])
    assert all(row["energy_wh"] is not None for row in value["load_facts"])


def test_cold_room_or_missing_cooling_cannot_promise_zero(tmp_path):
    from picot_hc.load_facts import build

    _, args = setup(tmp_path)
    settings = args[0]
    settings["windows"] = [
        dict(day=d, start="00:00", end="00:00", target=17, hard=False) for d in range(7)
    ]
    for temperature, rate in ((16.9, 0.5), (19, None), (19, -1)):
        context = dict(args[2], indoor=temperature)
        cooling = SimpleNamespace(estimate=lambda *a, rate=rate: dict(cooling_rate=rate))
        facts = build(settings, True, context, cooling, args[-1], 18)
        assert facts and all(f["energy_wh"] is None for f in facts)
