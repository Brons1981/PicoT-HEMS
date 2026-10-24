from dataclasses import replace
from datetime import timedelta

import pytest
from picot.v2.controlled_load_history import attribute
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.modeled_load_history import attribute_model, modeled_forecasts
from picot_hc.cv_auxiliary_history import AuxiliaryHistory
from test_controlled_load_history import NOW, observation, reading


def config():
    return dict(
        cv_auxiliary_mode="estimated",
        cv_auxiliary_running_w=100,
        cv_auxiliary_postrun_w=50,
        cv_auxiliary_postrun_seconds=300,
        cv_status="binary_sensor.cv",
        cv_dhw_active="binary_sensor.dhw",
    )


def states(now, active="on"):
    return {
        key: dict(state=value, last_reported=now.isoformat())
        for key, value in (("binary_sensor.cv", active), ("binary_sensor.dhw", "off"))
    }


def test_publish_attribute_and_persist_estimate_distinct_from_meter(tmp_path):
    modeled = AuxiliaryHistory().sample(config(), states(NOW), NOW.timestamp())
    payload = dict(reading("1500"), estimated_component=modeled)
    obs = attribute_model(attribute(observation(2000), payload, NOW), payload, NOW)
    assert obs.power_w == 2000
    assert obs.controlled_power_w == 1500
    assert obs.modeled_power_w == 100
    assert obs.modeled_source_id != obs.controlled_source_id
    store = HouseholdLoadHistoryStore(tmp_path / "history.jsonl")
    store.append(obs)
    assert store.load() == (obs,)


@pytest.mark.parametrize("fault", ["sum", "stale", "future", "identity", "nan", "meter_missing"])
def test_invalid_modeled_subset_preserves_physical_and_measured_history(fault):
    point = AuxiliaryHistory().sample(config(), states(NOW), NOW.timestamp())
    measured = attribute(observation(2000), reading(), NOW)
    if fault == "sum":
        point["power_w"] = 501
    elif fault in ("stale", "future"):
        point["generated_at"] = (
            NOW + timedelta(seconds=1 if fault == "future" else -61)
        ).isoformat()
    elif fault == "identity":
        point["source_id"] = measured.controlled_source_id
    elif fault == "nan":
        point["power_w"] = float("nan")
    else:
        measured = observation(2000)
    assert attribute_model(measured, dict(estimated_component=point), NOW) == measured


def test_restart_off_is_unknown_and_tail_is_not_repeated():
    model = AuxiliaryHistory()
    assert model.sample(config(), states(NOW, "off"), NOW.timestamp())["status"] == "unavailable"
    point = model.sample(config(), states(NOW), NOW.timestamp())
    assert point["power_w"] == 100
    for second in range(30, 391, 30):
        now = NOW + timedelta(seconds=second)
        point = model.sample(config(), states(now, "off"), now.timestamp())
        assert point["power_w"] == (50 if second < 330 else 0)
    later = NOW + timedelta(seconds=1000)
    assert (
        model.sample(config(), states(later, "off"), later.timestamp())["status"] == "unavailable"
    )


def test_parallel_estimated_history_conserves_total_and_refuses_unknown_samples():
    source = AuxiliaryHistory().sample(config(), states(NOW), NOW.timestamp())["source_id"]
    samples = []
    for day in (1, 2):
        for minute in (0, 8, 14):
            item = replace(
                observation(1000, NOW - timedelta(days=day) + timedelta(minutes=minute)),
                controlled_power_w=200,
                controlled_source_id="a" * 64,
                modeled_power_w=100,
                modeled_source_id=source,
            )
            samples.append(item)
    kwargs = dict(
        source_id=source,
        run_id="run",
        snapshot_id="snap",
        starts_at=NOW,
        horizon_end=NOW + timedelta(minutes=15),
    )
    forecasts = modeled_forecasts(samples, **kwargs)
    assert forecasts is not None
    values = {k: sum(i.expected_energy_wh for i in v.intervals) for k, v in forecasts.items()}
    assert values == dict(total=250, residual=225, controlled=25)
    assert all(
        i.method_version.startswith("modeled-") for v in forecasts.values() for i in v.intervals
    )
    assert samples[0].controlled_power_w == 200
    samples[0] = replace(samples[0], modeled_power_w=None, modeled_source_id=None)
    assert modeled_forecasts(samples, **kwargs) is None


def test_corrupt_optional_model_does_not_erase_valid_meter_history(tmp_path):
    import json

    store = HouseholdLoadHistoryStore(tmp_path / "history.jsonl")
    original = attribute(observation(), reading(), NOW)
    store.append(original)
    value = json.loads(store.path.read_text())
    value.update(modeled_power_w=2000, modeled_source_id="b" * 64)
    store.path.write_text(json.dumps(value))
    assert store.load() == (original,)
