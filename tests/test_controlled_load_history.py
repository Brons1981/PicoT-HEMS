import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from picot.v2.controlled_load_history import attribute, paired_forecasts
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.planning_input import HouseholdLoadObservation
from picot_hc.energy_measurement import measurement

NOW = datetime(2026, 10, 22, 18, tzinfo=UTC)
CONFIG = {
    "zones": [
        dict(
            id="beneden",
            device="climate.airco_woonkamer",
            power="sensor.kwh_meter_airco_vermogen",
            energy="sensor.kwh_meter_airco_energie_import",
        )
    ]
}


def reading(power="1500", age=0):
    return measurement(
        CONFIG,
        {
            "sensor.kwh_meter_airco_vermogen": dict(
                state=power,
                last_reported=(NOW - timedelta(seconds=age)).isoformat(),
                attributes={"unit_of_measurement": "W"},
            )
        },
        NOW.timestamp(),
    )


def observation(power=2000, when=NOW):
    return HouseholdLoadObservation(power, when, ("balance",), "test")


def test_confirmed_meter_end_to_end_preserves_total_and_persists(tmp_path):
    value = attribute(observation(), reading(), NOW)
    assert value.power_w == 2000
    assert value.controlled_power_w == 1500
    store = HouseholdLoadHistoryStore(tmp_path / "history.jsonl")
    store.append(value)
    assert store.load() == (value,)


@pytest.mark.parametrize(
    "power,age", [("unavailable", 0), ("NaN", 0), ("-1", 0), ("1500", 61), ("1500", -1), (True, 0)]
)
def test_missing_or_invalid_is_not_zero(power, age):
    payload = reading(power, age)
    assert payload["status"] == "unavailable"
    assert attribute(observation(), payload, NOW).controlled_power_w is None


def test_zero_is_evidence_and_reconfigured_meter_is_not_confirmed():
    assert attribute(observation(), reading("0"), NOW).controlled_power_w == 0
    other = {"zones": [dict(CONFIG["zones"][0], power="sensor.other")]}
    assert measurement(other, {}, NOW.timestamp())["status"] == "unavailable"


def test_skew_future_and_subset_cannot_be_clamped_into_plausibility():
    assert attribute(observation(1000), reading(), NOW).controlled_power_w is None
    assert attribute(observation(), reading(age=31), NOW).controlled_power_w is None
    future = dict(reading(), generated_at=(NOW + timedelta(seconds=1)).isoformat())
    assert attribute(observation(), future, NOW).controlled_power_w is None
    ev = replace(observation(), identified_external_power_w=800, external_power_observed=True)
    assert attribute(ev, reading(), NOW).controlled_power_w is None
    assert attribute(ev, reading("1000"), NOW).controlled_power_w == 1000


def test_legacy_history_remains_unknown_and_unchanged(tmp_path):
    path = tmp_path / "history.jsonl"
    payload = dict(
        schema_version=1,
        power_w=2000,
        sampled_at=NOW.isoformat(),
        evidence_ids=["old"],
        method_version="old",
    )
    original = json.dumps(payload) + "\n"
    path.write_text(original)
    (restored,) = HouseholdLoadHistoryStore(path).load()
    assert restored.controlled_power_w is None
    assert path.read_text() == original
    payload.update(controlled_power_w="bad", controlled_source_id="bad")
    path.write_text(json.dumps(payload) + "\n")
    (restored,) = HouseholdLoadHistoryStore(path).load()
    assert restored.power_w == 2000 and restored.controlled_power_w is None


def test_paired_prediction_conserves_energy_and_excludes_unmatched_history():
    source = reading()["source_id"]
    samples = []
    for days, total, controlled in [(1, 2000, 1500), (2, 1000, 500)]:
        for minute in (0, 8, 14):
            samples.append(
                replace(
                    observation(total, NOW - timedelta(days=days) + timedelta(minutes=minute)),
                    controlled_power_w=controlled,
                    controlled_source_id=source,
                )
            )
    # Unpaired history must neither dilute heating nor inflate the residual.
    samples.append(observation(10000, NOW - timedelta(days=1) + timedelta(minutes=5)))
    kwargs = dict(
        source_id=source,
        run_id="run",
        snapshot_id="snapshot",
        starts_at=NOW,
        horizon_end=NOW + timedelta(minutes=15),
    )
    forecasts = paired_forecasts(samples, **kwargs)
    energy = {k: v.intervals[0].expected_energy_wh for k, v in forecasts.items()}
    assert energy["residual"] == pytest.approx(125)
    assert energy["controlled"] == pytest.approx(291.6666666667)
    assert energy["total"] == pytest.approx(energy["residual"] + energy["controlled"])
    assert paired_forecasts(samples[:3], **kwargs) is None
    assert paired_forecasts(samples, **dict(kwargs, source_id="f" * 64)) is None


def test_assembly_attributes_actual_evidence_without_changing_active_forecast(
    tmp_path, monkeypatch
):
    from picot.v2.planning_input import (
        HomeAssistantStateReader,
        SourceBinding,
        SourceEvidence,
        assemble_planning_input,
    )

    options = tmp_path / "options.json"
    options.write_text("{}")
    powers = dict(
        grid_power="2000",
        pv_power="0",
        storage_power_signed="0",
        storage_power_to_house="0",
        storage_power_from_house="0",
    )
    sources = {
        role: SourceEvidence(
            role, "test", role, "sensor." + role, power, "W", NOW, "available", "mapping"
        )
        for role, power in powers.items()
    }
    sources["controlled_load_measurement"] = SourceEvidence(
        "meter",
        "energy_devices",
        "controlled_load_measurement",
        "sensor.picot_hc_load_measurement",
        "available",
        None,
        NOW,
        "available",
        "meter-mapping",
        external_load_payload=reading(),
    )
    monkeypatch.setattr(HomeAssistantStateReader, "read", lambda self, b: sources[b.semantic_role])
    bindings = tuple(
        SourceBinding(s.category, s.semantic_role, s.entity_id) for s in sources.values()
    )
    kwargs = dict(
        token="test",
        bindings=bindings,
        options_path=str(options),
        captured_at=NOW,
        household_load_fallback_power_w=700,
    )
    result = assemble_planning_input(**kwargs)
    assert result.household_load_observation.controlled_power_w == 1500
    assert result.household_load_observation.power_w == 2000
    original_forecast = result.snapshot.household_load_forecast
    sources["controlled_load_measurement"] = replace(
        sources["controlled_load_measurement"],
        external_load_payload=dict(
            reading(),
            estimated_component=dict(
                contract="modeled-load:v1",
                status="estimated",
                power_w=100,
                source_id="b" * 64,
                generated_at=NOW.isoformat(),
            ),
        ),
    )
    modeled = assemble_planning_input(**kwargs)
    assert modeled.household_load_observation.modeled_power_w == 100
    assert modeled.household_load_observation.controlled_power_w == 1500
    assert modeled.snapshot.household_load_forecast == original_forecast
    assert (
        modeled.controlled_load_summary["modeled_component"]["active_forecast_corrected"] is False
    )
    history = tuple(
        replace(
            observation(1000, NOW - timedelta(days=day) + timedelta(minutes=minute)),
            controlled_power_w=200,
            controlled_source_id=reading()["source_id"],
            modeled_power_w=100,
            modeled_source_id="b" * 64,
            replaceable_modeled_power_w=50,
        )
        for day in (1, 2, 3)
        for minute in range(0, 1440, 5)
    )
    joint = assemble_planning_input(**kwargs, household_load_observations=history)
    unreviewed = assemble_planning_input(
        **kwargs,
        household_load_observations=tuple(
            replace(p, replaceable_modeled_power_w=None) for p in history
        ),
    )
    assert joint.load_replacement_basis.modeled_source_id == "b" * 64
    assert unreviewed.load_replacement_basis.modeled_source_id is None
    assert joint.snapshot.household_load_forecast == unreviewed.snapshot.household_load_forecast
    assert sum(
        i.expected_energy_wh for i in joint.load_replacement_basis.component
    ) == pytest.approx(9000)
    sources["controlled_load_measurement"] = replace(
        sources["controlled_load_measurement"], external_load_payload=None
    )
    missing = assemble_planning_input(**kwargs)
    assert missing.household_load_observation.controlled_power_w is None
    assert missing.snapshot.household_load_forecast == original_forecast
    assert missing.controlled_load_summary["active_forecast_corrected"] is False
    sources["controlled_load_measurement"] = replace(
        sources["controlled_load_measurement"], external_load_payload=reading()
    )
    sources["grid_power"] = replace(sources["grid_power"], observed_at=NOW - timedelta(seconds=31))
    assert assemble_planning_input(**kwargs).household_load_observation.controlled_power_w is None


def test_paired_model_matches_existing_weighting_across_partial_quarters():
    from picot.v2.household_load_forecast import build_historical_household_load_forecast

    source = reading()["source_id"]
    samples = []
    for days in range(1, 10):
        for minute in range(30):
            samples.append(
                replace(
                    observation(
                        300 + days * 70 + minute,
                        NOW - timedelta(days=days) + timedelta(minutes=minute),
                    ),
                    controlled_power_w=days * 50,
                    controlled_source_id=source,
                )
            )
    kwargs = dict(
        run_id="run",
        snapshot_id="snapshot",
        starts_at=NOW + timedelta(minutes=3),
        horizon_end=NOW + timedelta(minutes=24),
    )
    actual = paired_forecasts(samples, source_id=source, **kwargs)
    expected = build_historical_household_load_forecast(observations=samples, **kwargs)
    for a, e in zip(actual["total"].intervals, expected.intervals, strict=True):
        assert (a.starts_at, a.ends_at, a.confidence) == (e.starts_at, e.ends_at, e.confidence)
        assert a.expected_energy_wh == pytest.approx(e.expected_energy_wh)


def test_publication_is_bounded_and_failure_releases_worker(monkeypatch):
    import picot_hc.energy_measurement as module

    queued, sent = [], []

    class DeferredThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            queued.append(self.target)

    monkeypatch.setattr(module, "Thread", DeferredThread)

    def fail(url, token, path, payload):
        sent.append((path, payload))
        raise OSError("offline")

    monkeypatch.setattr(module, "ha_request", fail)
    publisher = module.MeasurementPublisher("http://fake/api", "test")
    publisher.submit(reading())
    publisher.submit(reading("0"))
    assert len(queued) == 1
    queued.pop()()
    assert not publisher.lock.locked()
    assert sent[0][0] == "/states/sensor.picot_hc_load_measurement"
    assert sent[0][1]["attributes"]["power_w"] == 1500
    publisher.submit(reading("unavailable"))
    queued.pop()()
    assert sent[1][1]["state"] == "unavailable"
