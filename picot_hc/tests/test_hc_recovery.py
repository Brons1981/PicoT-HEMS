from types import SimpleNamespace

import pytest
from picot_hc.core import Store
from picot_hc.day_ahead import build
from picot_hc.warmup_energy import WarmupEnergy
from test_day_ahead import setup
from test_energy_proposals import sample
from test_heating import NOW
from test_room_floor import case as floor_case
from test_warmup_energy import inputs

case = floor_case


def test_idle_cv_does_not_stop_airco_and_is_not_taken_over(case):
    f = case
    f.at_time(NOW + 121)
    f.at_time(NOW + 152)
    cv = f.states[f.config["cv"]]
    cv["state"] = "heat"
    cv["attributes"].update(temperature=16, current_temperature=19.5, hvac_action="idle")
    p = f.at_time(NOW + 183)
    assert p["desired"] == {"beneden": 20}
    assert len(f.calls) == 1
    cv["attributes"].update(temperature=23.5, hvac_action="heating")
    f.at_time(NOW + 214)
    assert f.calls[-1][1]["hvac_mode"] == "off"
    f.at_time(NOW + 245)
    cv["attributes"].update(temperature=16, hvac_action="idle")
    f.at_time(NOW + 450)
    assert f.calls[-1][1]["temperature"] == 20
    assert all(c[1]["entity_id"] != f.config["cv"] for c in f.calls)


@pytest.mark.parametrize(
    "action,current,target", [("idle", 19, 23), (None, 19, 16), ("heating", 19, 16)]
)
def test_cv_uncertain_or_requested_heat_still_has_priority(case, action, current, target):
    cv = case.states[case.config["cv"]]
    cv["state"] = "heat"
    cv["attributes"].update(temperature=target, current_temperature=current, hvac_action=action)
    assert not case.at_time(NOW + 121)["desired"]


def test_preheat_over_low_block_before_deadline_and_night_stays_off(case):
    f = case
    f.runtime.schedule.data["settings"].update(learning_enabled=True, initial_preheat_minutes=45)
    f.temperature("beneden", 18)
    p = f.at_time(NOW + 27 * 3600 + 14 * 60)
    assert not p["preheating"]
    prices = f.states[f.config["price_entity"]]["attributes"]["raw_today"]
    from datetime import UTC, datetime

    prices[0]["end"] = datetime.fromtimestamp(NOW + 48 * 3600, UTC).isoformat()
    p = f.at_time(NOW + 27 * 3600 + 15 * 60)
    assert p["preheating"] and not p["room_floor_mode"]
    assert p["zones"]["beneden"]["target"] == 20
    assert f.calls[-1][1]["temperature"] == 20


def test_normal_comfort_start_is_a_complete_learning_session(tmp_path):
    model = WarmupEnergy(Store(tmp_path / "normal.sqlite"))
    v, p = inputs(NOW)
    v["current"], v["next"] = v["next"], None
    p.update(preheating=False, learning_status=dict(phase="comfort"))
    for minute in range(33):
        s = dict(sample(minute * 60, 1200), indoor=min(20, 18 + minute / 15))
        model.observe(s, v, p, NOW + minute * 60)
    assert len(model.records) == 1
    assert model.events[-1]["kind"] == "completed"
    restored = WarmupEnergy(model.store)
    assert restored.events == model.events


def test_forecast_can_use_complete_start_records(tmp_path):
    store, args = setup(tmp_path)
    startup = WarmupEnergy(store, cold_start=True)
    startup.records = list(args[5].records)
    args[5].records = []
    assert build(*args)["status"] == "unavailable"
    result = build(*args, startup=startup)
    assert result["status"] == "provisional" and result["slots"]


def test_explicit_low_block_forecast_cools_before_heating(tmp_path):
    _, args = setup(tmp_path)
    settings = args[0]
    settings["windows"] = [
        dict(day=d, start=a, end=b, target=t, hard=h)
        for d in range(7)
        for a, b, t, h in [
            ("00:00", "18:00", 17, False),
            ("18:00", "22:00", 20, True),
            ("22:00", "00:00", 17, False),
        ]
    ]
    result = build(*args)
    assert result["status"] == "provisional"
    assert result["slots"][0]["phase"] == "off"
    assert result["slots"][0]["energy_wh"] == 0
    assert any(s["phase"] == "warmup" and s["target"] == 20 for s in result["slots"])
    assert not any(s["target"] == 17 and s["energy_wh"] > 0 for s in result["slots"])
    modified = list(args)
    modified[6] = SimpleNamespace(samples=[], estimate=lambda c, n: dict(cooling_rate=None))
    assert "no_floor_cooling_measurements" in build(*modified)["reasons"]


def test_normal_comfort_start_captures_precommand_energy(tmp_path):
    from unittest.mock import patch

    import test_startup_energy as helpers
    from picot_hc.startup_energy import StartupEnergy

    original = helpers.inputs

    def comfort(now):
        view, plan, command = original(now)
        view["current"] = dict(view["next"], starts_at=now)
        view["next"] = None
        plan.update(preheating=False, learning_status=dict(phase="comfort"))
        return view, plan, command

    model = StartupEnergy(Store(tmp_path / "startup.sqlite"))
    with patch.object(helpers, "inputs", side_effect=comfort):
        helpers.run(model, NOW)
    assert len(model.model.records) == 1
    assert model.model.records[0]["confirmation_delay_seconds"] == 120


def test_forecast_stops_unfinished_comfort_warmup_at_night_boundary(tmp_path):
    from datetime import datetime

    from picot_hc.schedule import TZ

    _, original = setup(tmp_path)
    args = list(original)
    args[-1] = datetime(2026, 11, 3, 21, 55, tzinfo=TZ).timestamp()
    args[0]["windows"] = [
        dict(day=d, start=a, end=b, target=t, hard=h)
        for d in range(7)
        for a, b, t, h in [
            ("00:00", "18:00", 17, False),
            ("18:00", "22:00", 20, True),
            ("22:00", "00:00", 17, False),
        ]
    ]
    result = build(*args)
    assert result["status"] == "provisional"
    assert result["slots"][0]["phase"] == "warmup"
    boundary = next(
        s
        for s in result["slots"]
        if datetime.fromisoformat(s["starts_at"]).astimezone(TZ).strftime("%d %H:%M") == "03 22:00"
    )
    assert boundary["phase"] == "off" and boundary["energy_wh"] == 0
    assert len(result["slots"]) <= 300
    assert all(
        a["ends_at"] == b["starts_at"]
        for a, b in zip(result["slots"], result["slots"][1:], strict=False)
    )


def test_warmup_rejection_reason_survives_restart(tmp_path):
    from test_warmup_energy import run

    model = WarmupEnergy(Store(tmp_path / "rejected.sqlite"))
    run(model, NOW, fault="weather")
    restored = WarmupEnergy(model.store)
    assert any(
        e["kind"] == "rejected" and e["reason"] == "weather_changed" for e in restored.events
    )
    assert not restored.records


def test_preheating_does_not_override_hard_lower_window(case):
    case.runtime.schedule.data["settings"].update(learning_enabled=True)
    case.runtime.schedule.data["settings"]["windows"][2]["hard"] = True
    assert not case.at_time(NOW + 27 * 3600 + 30 * 60)["preheating"]
