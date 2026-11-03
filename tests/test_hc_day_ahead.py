from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_accepted_loads import bundle_for, integral
from test_controlled_load_history import NOW, observation, reading
from test_ev_deadline_advice import scenario

from picot.v2.hc_day_ahead import apply, validate
from picot.v2.load_replacement import replace_profile


def payload(snapshot):
    start = snapshot.captured_at
    return dict(
        contract="hc-day-ahead:v1",
        scope="beneden",
        source_assumption="airco",
        source_id="a" * 64,
        execution_authorized=False,
        status="provisional",
        timezone="Europe/Amsterdam",
        revision="revision1",
        generated_at=start.isoformat(),
        valid_until=(start + timedelta(hours=2)).isoformat(),
        delivery_date=(
            start.astimezone(ZoneInfo("Europe/Amsterdam")).date() + timedelta(days=1)
        ).isoformat(),
        slots=[
            dict(
                starts_at=(start + timedelta(hours=14)).isoformat(),
                ends_at=(start + timedelta(hours=15)).isoformat(),
                energy_wh=1200,
            )
        ],
    )


def test_forecast_replaces_heating_then_near_term_profile_replaces_forecast(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    value = payload(snapshot)
    result = apply(bundle, value, bundle.load_replacement_basis)
    status = result.controlled_load_summary["hc_day_ahead"]
    assert status["applied"], status
    slot = validate(value, snapshot.captured_at)[0]
    left, right = slot["start"], slot["end"]
    old = integral(snapshot.household_load_forecast, left, right)
    assert integral(result.snapshot.household_load_forecast, left, right) == pytest.approx(
        old * 0.6 + 1200
    )
    assert apply(result, value, result.load_replacement_basis) == result
    near = replace_profile(
        result.snapshot, result.load_replacement_basis, [dict(start=left, end=right, energy=500)]
    )
    assert integral(near.household_load_forecast, left, right) == pytest.approx(old * 0.6 + 500)


def test_no_basis_missing_stale_and_disabled_preserve_historical_forecast(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    value = payload(snapshot)
    for change, basis in [
        (value, None),
        (None, bundle.load_replacement_basis),
        (dict(value, valid_until=snapshot.captured_at.isoformat()), bundle.load_replacement_basis),
        (dict(value, status="disabled"), bundle.load_replacement_basis),
    ]:
        result = apply(bundle, change, basis)
        assert result.snapshot == snapshot
        assert result.controlled_load_summary["hc_day_ahead"]["applied"] is False


@pytest.mark.parametrize("energy", [-1, float("nan"), float("inf"), True, 20001])
def test_malformed_energy_cannot_enter_planning(tmp_path, energy):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = payload(snapshot)
    value["slots"][0]["energy_wh"] = energy
    with pytest.raises(ValueError):
        validate(value, snapshot.captured_at)


def test_atomic_ingestion_uses_forecast_and_preserves_cv_component(tmp_path, monkeypatch):
    from picot.v2.planning_input import (
        HomeAssistantStateReader,
        SourceBinding,
        SourceEvidence,
        assemble_planning_input,
    )

    options = tmp_path / "options.json"
    options.write_text("{}")
    powers = dict(
        grid_power="1000",
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
        "meter",
        external_load_payload=dict(
            reading("200"),
            estimated_component=dict(
                contract="modeled-load:v1",
                status="estimated",
                power_w=100,
                source_id="b" * 64,
                generated_at=NOW.isoformat(),
            ),
        ),
    )
    sources["hc_day_ahead_forecast"] = SourceEvidence(
        "hc",
        "energy_devices",
        "hc_day_ahead_forecast",
        "sensor.picot_hc_day_ahead",
        "provisional",
        None,
        NOW,
        "available",
        "hc",
    )
    monkeypatch.setattr(HomeAssistantStateReader, "read", lambda self, b: sources[b.semantic_role])
    history = tuple(
        replace(
            observation(1000, NOW - timedelta(days=d) + timedelta(minutes=m)),
            controlled_power_w=200,
            controlled_source_id=reading()["source_id"],
            modeled_power_w=100,
            modeled_source_id="b" * 64,
            replaceable_modeled_power_w=50,
        )
        for d in (1, 2, 3)
        for m in range(0, 1440, 5)
    )
    kwargs = dict(
        token="test",
        options_path=str(options),
        captured_at=NOW,
        bindings=tuple(
            SourceBinding(s.category, s.semantic_role, s.entity_id) for s in sources.values()
        ),
        household_load_observations=history,
    )
    original = assemble_planning_input(**kwargs)
    assert original.load_replacement_basis.modeled_source_id == "b" * 64
    value = payload(original.snapshot)
    value["source_id"] = reading()["source_id"]
    sources["hc_day_ahead_forecast"] = replace(
        sources["hc_day_ahead_forecast"], external_load_payload=value
    )
    updated = assemble_planning_input(**kwargs)
    status = updated.controlled_load_summary["hc_day_ahead"]
    assert status["applied"], status
    slot = validate(value, NOW)[0]
    left, right = slot["start"], slot["end"]
    # Original 1000 Wh/h: replace only 200 Wh of airco by 1200 Wh.
    assert integral(updated.snapshot.household_load_forecast, left, right) == pytest.approx(2000)
    # Combined attribution still includes the 50 Wh reviewed CV auxiliary part.
    assert sum(
        i.expected_energy_wh
        * max(timedelta(), min(right, i.ends_at) - max(left, i.starts_at))
        / (i.ends_at - i.starts_at)
        for i in updated.load_replacement_basis.component
    ) == pytest.approx(1250)
    assert updated.household_load_observation == original.household_load_observation
