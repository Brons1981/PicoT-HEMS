from dataclasses import replace
from datetime import timedelta

import pytest
from picot_hc.cv_auxiliary_history import AuxiliaryHistory
from test_controlled_load_history import NOW, observation, reading
from test_modeled_load_history import config, states

from picot.v2.controlled_load_history import attribute
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.modeled_load_history import attribute_model, joint_forecasts


@pytest.mark.parametrize("late_dhw", [False, True])
def test_delayed_review_updates_only_optional_subset_after_persistence(tmp_path, late_dhw):
    history = HouseholdLoadHistoryStore(tmp_path / "history.jsonl")
    model = AuxiliaryHistory()
    for seconds in (0, 30, 60, 90):
        now = NOW + timedelta(seconds=seconds)
        points = states(now)
        if late_dhw and seconds == 90:
            points["binary_sensor.dhw"]["state"] = "on"
        estimate = model.sample(config(), points, now.timestamp())
        physical = replace(attribute(observation(2000), reading(), NOW), sampled_at=now)
        payload = dict(estimated_component=estimate)
        captured = attribute_model(physical, payload, now)
        history.append(captured)
        if seconds < 90:
            assert history.load()[0].replaceable_modeled_power_w is None
    loaded = history.load()
    assert loaded[0].replaceable_modeled_power_w == (0 if late_dhw else 100)
    assert loaded[0].power_w == 2000
    assert loaded[0].controlled_power_w == 1500
    assert loaded[0].modeled_power_w == 100
    assert loaded[-1].replaceable_modeled_power_w is None


def test_joint_weighting_keeps_retained_model_part_in_residual():
    samples = [
        replace(
            observation(1000, NOW - timedelta(days=day) + timedelta(minutes=minute)),
            controlled_power_w=200,
            controlled_source_id="a" * 64,
            modeled_power_w=100,
            modeled_source_id="b" * 64,
            replaceable_modeled_power_w=50,
        )
        for day in (1, 2)
        for minute in (0, 8, 14)
    ]
    options = dict(
        source_id="a" * 64,
        modeled_source_id="b" * 64,
        run_id="run",
        snapshot_id="snap",
        starts_at=NOW,
        horizon_end=NOW + timedelta(minutes=15),
    )
    forecast = joint_forecasts(samples, **options)
    values = {k: sum(i.expected_energy_wh for i in v.intervals) for k, v in forecast.items()}
    assert values == dict(total=250, controlled=62.5, residual=187.5)
    samples[0] = replace(samples[0], replaceable_modeled_power_w=None)
    assert joint_forecasts(samples, **options) is None


def test_gap_discards_unreviewed_attribution():
    model = AuxiliaryHistory()
    model.sample(config(), states(NOW), NOW.timestamp())
    later = NOW + timedelta(seconds=91)
    result = model.sample(config(), states(later), later.timestamp())
    assert result["reviewed_components"] == []


def test_fast_polling_keeps_review_publication_within_consumer_limit():
    model = AuxiliaryHistory()
    for seconds in range(0, 1505, 5):
        now = NOW + timedelta(seconds=seconds)
        value = model.sample(config(), states(now), now.timestamp())
    assert len(value["reviewed_components"]) == 80
    physical = replace(attribute(observation(2000), reading(), NOW), sampled_at=now)
    received = attribute_model(physical, dict(estimated_component=value), now)
    assert len(received.modeled_reviews) == 80
