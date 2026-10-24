from datetime import UTC, datetime

import pytest
from picot_hc.core import Store
from picot_hc.energy_model import EnergyModel
from picot_hc.thermal_weather import comparable, observed
from test_energy_proposals import NOW, sample


def states(wind=18, unit="km/h", sky="sunny"):
    return {
        "weather.test": dict(
            state=sky,
            last_updated=datetime.fromtimestamp(NOW, UTC).isoformat(),
            attributes=dict(wind_speed=wind, wind_speed_unit=unit),
        ),
        "sun.sun": dict(state="above_horizon"),
    }


def weather(**changes):
    return dict(source="weather.test", wind_m_s=5, sky="clear", daylight=True, **changes)


@pytest.mark.parametrize(
    "wind,unit", [(18, "km/h"), (5, "m/s"), (5 / 0.44704, "mph"), (5 / 0.514444, "kn")]
)
def test_actual_weather_attributes_normalize_units(wind, unit):
    result = observed(dict(weather_entity="weather.test"), states(wind, unit), NOW)
    assert result["wind_m_s"] == pytest.approx(5)
    assert result["sky"] == "clear"


@pytest.mark.parametrize("fault", ["stale", "future", "unit", "bool", "missing_sun", "unknown"])
def test_incomplete_or_stale_weather_is_not_claimed(fault):
    items = states()
    at = NOW
    if fault == "stale":
        at += 1801
    if fault == "future":
        at -= 1
    if fault == "unit":
        items["weather.test"]["attributes"]["wind_speed_unit"] = "furlongs"
    if fault == "bool":
        items["weather.test"]["attributes"]["wind_speed"] = True
    if fault == "missing_sun":
        del items["sun.sun"]
    if fault == "unknown":
        items["weather.test"]["state"] = "unknown"
    assert observed(dict(weather_entity="weather.test"), items, at) is None


def test_numeric_cloud_cover_and_day_night_are_distinct():
    items = states()
    items["weather.test"]["attributes"]["cloud_coverage"] = 90
    items["sun.sun"]["state"] = "below_horizon"
    point = observed(dict(weather_entity="weather.test"), items, NOW)
    assert point["sky"] == "overcast"
    assert not point["daylight"]
    assert not comparable(dict(weather=weather()), dict(weather=point))
    assert not comparable({}, dict(weather=point))


def test_measured_holding_weather_is_persisted_and_selects_compatible_evidence(tmp_path):
    store = Store(tmp_path / "hc.sqlite")
    model = EnergyModel(store)
    for minute in range(63):
        model.observe(dict(sample(minute * 60), weather=weather()), NOW - 3720 + minute * 60)
    loaded = EnergyModel(store)
    assert loaded.estimate(dict(sample(), weather=weather()), NOW)["power_w"] == 750
    for change in (
        dict(wind_m_s=8),
        dict(sky="overcast"),
        dict(daylight=False),
        dict(source="weather.other"),
    ):
        query = dict(sample(), weather=dict(weather(), **change))
        assert loaded.estimate(query, NOW)["power_w"] is None
    assert loaded.estimate(sample(), NOW)["power_w"] is None


def test_weather_change_discards_partial_holding_period(tmp_path):
    model = EnergyModel(Store(tmp_path / "hc.sqlite"))
    for minute in range(21):
        point = dict(weather(), sky="overcast" if minute >= 10 else "clear")
        model.observe(dict(sample(minute * 60), weather=point), NOW + minute * 60)
    assert model.records == []


def test_cv_weather_matching_preserves_screened_gas_requirements(tmp_path):
    from picot_hc.cv_energy_model import estimate
    from test_cv_energy_model import evidence
    from test_cv_warmup import NOW as cv_now

    _, records, query = evidence(tmp_path)
    for record in records:
        record["weather"] = weather()
    query["weather"] = weather()
    assert estimate(records, query, cv_now + 1600)["gas_m3"] == pytest.approx(0.625)
    query["weather"]["sky"] = "overcast"
    assert estimate(records, query, cv_now + 1600)["gas_m3"] is None
    query["weather"] = weather()
    records[0]["gas_screening"]["provisional"] = True
    assert estimate(records, query, cv_now + 1600)["gas_m3"] is None


def test_new_weather_does_not_inherit_short_lead_or_deep_setback(tmp_path):
    from picot_hc.learning import Learning

    model = Learning(Store(tmp_path / "hc.sqlite"))
    view = dict(
        settings=dict(
            enabled=True, learning_enabled=True, initial_preheat_minutes=45, max_preheat_minutes=180
        )
    )
    model.data = dict(
        signature=model.signature(view),
        lead=20,
        depth=3,
        outcomes=[dict(weather=weather(), next_lead_minutes=20, next_depth=3)] * 3,
    )
    known = model.status(view, dict(weather=weather()))
    assert known["lead_minutes"] == 20
    assert known["setback_depth"] == 3
    changed = model.status(view, dict(weather=dict(weather(), wind_m_s=10)))
    assert changed["lead_minutes"] == 45
    assert changed["setback_depth"] == 1
    assert changed["weather_samples"] == 0


def test_runtime_context_uses_existing_weather_entity():
    from test_downstairs_comfort import DownstairsComfortTests

    fixture = DownstairsComfortTests()
    fixture.setUp()
    try:
        config = fixture.config
        config["weather_entity"] = "weather.test"
        fixture.ctl.states.update(states())
        view = fixture.schedule.view(NOW)
        result = fixture.heat.learning_context(config, view, NOW, set())
        assert result["weather"] == weather()
    finally:
        fixture.doCleanups()


def test_weather_change_restores_comfort_after_learned_coast():
    from test_cooling import CoolingTests
    from test_downstairs_comfort import NOW as comfort_now

    fixture = CoolingTests()
    fixture.setUp()
    try:
        fixture.config["weather_entity"] = "weather.test"
        fixture.states.update(states())
        original_poll = fixture.poll

        def poll(advance=60):
            fixture.states["weather.test"]["last_updated"] = fixture.stamp(fixture.now + advance)
            return original_poll(advance)

        fixture.poll = poll
        fixture.measured_cooling()
        fixture.now = comfort_now + 3 * 3600 + 30 * 60
        fixture.temperature("beneden", 20)
        plan = fixture.poll()
        assert plan["learning_status"]["phase"] == "coast"
        assert plan["zones"]["beneden"]["target"] == 19.5
        fixture.states["weather.test"]["state"] = "cloudy"
        plan = fixture.poll()
        assert plan["learning_status"]["cooling_samples"] == 0
        assert plan["zones"]["beneden"]["target"] == 20
    finally:
        fixture.doCleanups()
