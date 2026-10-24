import copy
import io
import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from picot_hc.core import Store
from picot_hc.energy_model import EnergyModel
from picot_hc.hourly_weather import HourlyWeather, contexts, parse, planning_models
from test_energy_proposals import sample

NOW = 1792692000.0
ENTITY = "weather.home"
ATTRS = dict(supported_features=3, temperature_unit="°C", wind_speed_unit="km/h")


def rows(count=4, **changes):
    return [
        dict(
            datetime=datetime.fromtimestamp(NOW + i * 3600, UTC).isoformat(),
            temperature=10,
            wind_speed=18,
            condition="sunny",
            **changes,
        )
        for i in range(count)
    ]


def forecast(points=None, **changes):
    return dict(
        type="hourly",
        status="ready",
        entity_id=ENTITY,
        received=NOW,
        intervals=parse(points or rows(), ENTITY, ATTRS),
        **changes,
    )


def weather(day=True, outdoor=10):
    return dict(source=ENTITY, wind_m_s=5, sky="clear", daylight=day)


def test_unsupported_hourly_is_explicit_and_never_invents_daily_slots():
    reader = HourlyWeather(ENTITY)
    state = {ENTITY: dict(state="cloudy", attributes=dict(supported_features=1))}
    value = reader.collect(state, NOW, "http://unused", "unused")
    assert value["status"] == "unsupported"
    assert value["intervals"] == []
    assert contexts(value, NOW, NOW + 3600, NOW) is None


def test_http_action_is_hourly_cached_and_failures_are_isolated():
    reader = HourlyWeather(ENTITY)
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(json.loads(request.data))
            return io.BytesIO(
                json.dumps(dict(service_response={ENTITY: dict(forecast=rows())})).encode()
            )

    state = {ENTITY: dict(state="sunny", attributes=ATTRS)}
    with patch("picot_hc.hourly_weather.build_opener", return_value=Opener()):
        value = reader.collect(state, NOW, "http://ha/api", "secret")
        assert value["status"] == "ready"
        reader.collect(state, NOW + 1, "http://ha/api", "secret")
    assert calls == [dict(entity_id=ENTITY, type="hourly")]
    assert "secret" not in json.dumps(value)
    assert reader.view(NOW + 3601)["status"] == "stale"
    reader.next_attempt = 0
    with patch("picot_hc.hourly_weather.fetch", side_effect=OSError("secret")):
        result = reader.collect(state, NOW + 1800, "http://ha/api", "secret")
    assert result["status"] == "unavailable"
    assert result["intervals"] == []
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "fault",
    ["daily", "gap", "duplicate", "naive", "wind", "temperature", "cloud", "unit", "boolean"],
)
def test_invalid_or_nonhourly_forecasts_cannot_become_intervals(fault):
    points, attrs = rows(), dict(ATTRS)
    if fault in ("daily", "gap", "duplicate"):
        step = {"daily": 86400, "gap": 7200, "duplicate": 0}[fault]
        points[1]["datetime"] = datetime.fromtimestamp(NOW + step, UTC).isoformat()
    elif fault == "naive":
        points[1]["datetime"] = "2026-10-22T12:00:00"
    elif fault == "wind":
        points[1].pop("wind_speed")
    elif fault == "temperature":
        points[1]["temperature"] = float("nan")
    elif fault == "cloud":
        points[1]["condition"] = "unknown"
    elif fault == "unit":
        attrs["wind_speed_unit"] = "unknown"
    else:
        points[1]["wind_speed"] = True
    with pytest.raises((ValueError, KeyError)):
        parse(points, ENTITY, attrs)


def test_exact_coverage_expiry_and_unknown_day_do_not_use_current_sun():
    points = rows()
    for row in points:
        row["condition"] = "cloudy"
    value = forecast(points)
    supported = contexts(value, NOW + 900, NOW + 4500, NOW)
    assert len(supported) == 4
    assert {p["weather"]["daylight"] for p in supported} == {False, True}
    assert contexts(value, NOW, NOW + 4 * 3600, NOW) is None
    assert contexts(value, NOW - 1, NOW + 3600, NOW) is None
    assert contexts(value, NOW + 4000, NOW + 5000, NOW + 3601) is None


def test_future_conditions_change_real_learned_energy_without_relabelling_observations(tmp_path):
    model = EnergyModel(Store(tmp_path / "hc.sqlite"))
    for day, power, outdoor in ((2, 600, 10), (1, 1200, 8)):
        for minute in range(63):
            point = dict(sample(minute * 60, power), outdoor=outdoor, weather=weather())
            model.observe(point, NOW - day * 86400 + minute * 60)
    before = copy.deepcopy(model.records)
    current = dict(sample(), weather=weather())
    assert model.estimate(current, NOW)["power_w"] == 750
    points = rows()
    points[1]["temperature"] = 8
    plan = dict(hourly_weather=forecast(points))
    (bounded,), _ = planning_models(plan, [model], current, NOW, NOW + 120, NOW + 7200)
    assert bounded.estimate(current, NOW)["power_w"] == 1500
    assert model.records == before
    points[1]["wind_speed"] = 54
    plan["hourly_weather"] = forecast(points)
    (bounded,), _ = planning_models(plan, [model], current, NOW, NOW + 120, NOW + 7200)
    assert bounded.estimate(current, NOW)["power_w"] is None
    assert model.records == before


def cooling_for(store, plan, sample, now):
    from picot_hc.cooling import Cooling

    model = Cooling(store)
    plan["learning_context"] = dict(
        valid=True,
        indoor=sample["indoor"],
        outdoor=10,
        identity=sample["identity"],
        weather=weather(),
    )
    model.samples = [
        dict(
            end=now - 3600 - i * 1800,
            indoor=18,
            outdoor=outdoor,
            identity=sample["identity"],
            coefficient=0.005,
            weather=weather(),
        )
        for outdoor in (10, 8)
        for i in range(3)
    ]
    return model


def test_delayed_recipe_prices_future_weather_and_rejects_missing_coverage(tmp_path):
    from picot_hc.delayed_start import candidates
    from test_delayed_start import evidence

    startup, steady, standby, point, view, plan = evidence(tmp_path)
    point["weather"] = weather()
    for model in (startup.model, steady):
        originals = copy.deepcopy(model.records)
        for record in model.records:
            record["weather"] = weather()
        for record in originals:
            record.update(weather=weather(), outdoor=8)
            if "mean_power_w" in record:
                record["mean_power_w"] = 1200
            model.records.append(record)
    cooling = cooling_for(steady.store, plan, point, NOW)
    baseline = candidates(
        point, view, plan, startup.model, steady, standby.estimate(NOW), NOW, NOW + 900, NOW + 6300
    )
    points = rows()
    points[1]["temperature"] = 8
    plan["hourly_weather"] = forecast(points)
    options = candidates(
        point,
        view,
        plan,
        startup.model,
        steady,
        standby.estimate(NOW),
        NOW,
        NOW + 900,
        NOW + 6300,
        cooling=cooling,
    )
    assert baseline and options
    assert options[0]["maintenance"]["power_w"] == 1500
    assert baseline[0]["maintenance"]["power_w"] == 750
    assert options[0]["hourly_forecast_used"] is True
    plan["hourly_weather"]["intervals"].pop()
    assert (
        candidates(
            point,
            view,
            plan,
            startup.model,
            steady,
            standby.estimate(NOW),
            NOW,
            NOW + 900,
            NOW + 10000,
            cooling=cooling,
        )
        == []
    )


def test_cv_recipe_includes_future_gas_bound_not_only_electricity(tmp_path):
    from picot_hc.cv_plans import candidates
    from test_cv_plans import setup

    now, point, view, plan, context, standby = setup(tmp_path)
    point["weather"] = context["sample"]["weather"] = weather()
    for model in (context["warmup"], context["maintenance"].evidence):
        original = copy.deepcopy(model.records)
        for record in model.records:
            record["weather"] = weather()
        for record in original:
            record.update(weather=weather(), outdoor=8)
            record["command_id"] += "-cold"
            record["household_gas_delta_m3"] *= 2
            model.records.append(record)
    cooling = cooling_for(context["warmup"].store, plan, point, now)
    points = rows(count=7)
    for row in points:
        row["datetime"] = datetime.fromtimestamp(
            datetime.fromisoformat(row["datetime"]).timestamp() + 7200, UTC
        ).isoformat()
    points[1]["temperature"] = 8
    plan["hourly_weather"] = dict(forecast(points), received=now)
    options = candidates(
        point,
        view,
        plan,
        context,
        standby,
        now,
        now + 120,
        view["next"]["ends_at"],
        cooling=cooling,
    )
    assert options
    for recipe in options:
        assert recipe["startup_gas_m3"] == pytest.approx(1.25)
        assert recipe["maintenance"]["gas_m3_per_hour"] == pytest.approx(1.25)
        hours = (view["next"]["ends_at"] - recipe["reaches_at"]) / 3600
        assert recipe["non_electric_cost_eur"] == pytest.approx((1.25 + 1.25 * hours) * 1.4)


def test_forecast_intent_allows_expected_weather_but_never_sensor_change(tmp_path):
    from test_start_intent import setup

    intent, _, _, point, view, plan, _, _ = setup(tmp_path)
    intent.current["recipe"]["hourly_forecast_used"] = True
    plan["hourly_weather"] = forecast()
    changed = dict(point, weather=weather(), outdoor=7)
    assert intent.valid(changed, view, plan, NOW + 30)
    changed["identity"] = "different sensor"
    assert not intent.valid(changed, view, plan, NOW + 30)
    changed["identity"] = point["identity"]
    plan["hourly_weather"]["status"] = "stale"
    assert not intent.valid(changed, view, plan, NOW + 30)


def test_real_runtime_fetches_daily_and_hourly_separately_without_training_forecasts():
    from pathlib import Path

    from picot_hc.__main__ import Runtime
    from test_weather import ENTITY as existing_entity
    from test_weather import WeatherTests

    fixture = WeatherTests()
    fixture.setUp()
    try:
        fixture.state["attributes"]["supported_features"] = 3
        fixture.rows = rows()
        runtime = Runtime(
            fixture.config,
            Store(Path(fixture.tmp.name) / "hourly.sqlite"),
            fixture.ha(),
            "test-token",
        )
        runtime.collect()
        kinds = [
            payload["type"]
            for path, payload in fixture.calls
            if path.endswith("weather/get_forecasts?return_response")
        ]
        assert kinds == ["hourly", "daily"]
        data = runtime.store.latest()["weather"]
        assert data["hourly"]["type"] == "hourly"
        assert data["hourly"]["status"] == "ready"
        assert len(data["hourly"]["intervals"]) == 3
        assert data["hourly"]["entity_id"] == existing_entity
        assert data["forecast"]["type"] == "daily"
        assert runtime.energy_proposals.model.records == []
    finally:
        fixture.doCleanups()


@pytest.mark.parametrize("case", ["ready", "stale", "unsupported", "unlearned_wind"])
def test_real_start_guard_rechecks_future_weather_before_dispatch(case):
    from test_energy_start import EnergyStartTests

    fixture = EnergyStartTests()
    fixture.setUp()
    try:
        fixture.prepare()
        fixture.config["weather_entity"] = ENTITY
        fixture.states[ENTITY] = dict(
            state="sunny",
            last_updated=fixture.stamp(fixture.now),
            attributes=dict(ATTRS, wind_speed=18),
        )
        fixture.states["sun.sun"] = dict(state="above_horizon")
        for records in (
            fixture.runtime.startup_energy.model.records,
            fixture.runtime.energy_proposals.model.records,
            fixture.heat.learning.cooling.samples,
        ):
            for record in records:
                record["weather"] = weather()
        points = rows(count=7)
        for row in points:
            row["datetime"] = datetime.fromtimestamp(
                datetime.fromisoformat(row["datetime"]).timestamp() + fixture.now - NOW, UTC
            ).isoformat()
        if case == "unlearned_wind":
            points[1]["wind_speed"] = 54
        value = dict(forecast(points), received=fixture.now)
        if case in ("stale", "unsupported"):
            value["status"] = case
        fixture.runtime.weather.hourly.data = value
        fixture.runtime.start_intent.current["recipe"]["hourly_forecast_used"] = True
        fixture.fresh()
        fixture.runtime.collect()
        assert len(fixture.calls) == (1 if case == "ready" else 0)
        if case == "ready":
            assert fixture.calls[0][1]["hvac_mode"] == "heat"
    finally:
        fixture.doCleanups()


def test_unknown_future_daylight_requires_both_real_evidence_populations(tmp_path):
    model = EnergyModel(Store(tmp_path / "both.sqlite"))
    points = rows()
    for row in points:
        row["condition"] = "cloudy"
    plan = dict(hourly_weather=forecast(points))
    query = dict(sample(), weather=dict(weather(), sky="overcast"))
    for daylight, watts, day in ((True, 600, 2), (False, 1200, 1)):
        for minute in range(63):
            observed = dict(
                sample(minute * 60, watts),
                weather=dict(weather(), sky="overcast", daylight=daylight),
            )
            model.observe(observed, NOW - day * 86400 + minute * 60)
        (bounded,), _ = planning_models(plan, [model], query, NOW, NOW + 120, NOW + 7200)
        assert bounded.estimate(query, NOW)["power_w"] == (None if daylight else 1500)


def test_dst_fold_preserves_two_distinct_local_two_oclock_hours():
    points = rows()
    for row, stamp in zip(
        points,
        [
            "2026-10-25T01:00:00+02:00",
            "2026-10-25T02:00:00+02:00",
            "2026-10-25T02:00:00+01:00",
            "2026-10-25T03:00:00+01:00",
        ],
        strict=True,
    ):
        row["datetime"] = stamp
    intervals = parse(points, ENTITY, ATTRS)
    assert len(intervals) == 3
    assert all(i["ends_at"] - i["starts_at"] == 3600 for i in intervals)
    assert intervals[2]["starts_at"] - intervals[1]["starts_at"] == 3600
