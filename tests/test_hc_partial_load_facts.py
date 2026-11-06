from datetime import timedelta

import pytest
from test_accepted_loads import bundle_for, integral
from test_ev_deadline_advice import scenario
from test_hc_day_ahead import payload

from picot.v2.hc_day_ahead import apply


def partial(snapshot):
    value = payload(snapshot)
    at = snapshot.captured_at + timedelta(hours=1)
    rows = []
    for n, energy in enumerate((None, 0, None, 500)):
        rows.append(
            dict(
                starts_at=(at + timedelta(hours=n)).isoformat(),
                ends_at=(at + timedelta(hours=n + 1)).isoformat(),
                timing_status="known",
                operation="load_released" if energy == 0 else "load_expected",
                energy_status="unknown" if energy is None else "provisional",
                energy_wh=energy,
                reason="test_evidence",
            )
        )
    return dict(value, status="partial", slots=[], load_facts=rows)


def test_partial_facts_replace_only_known_energy_and_keep_timing_in_snapshot(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    value = partial(snapshot)
    result = apply(bundle, value, bundle.load_replacement_basis)
    assert result.controlled_load_summary["hc_day_ahead"]["applied"]
    assert len(result.snapshot.external_load_facts) == 4
    for fact in result.snapshot.external_load_facts:
        before = integral(snapshot.household_load_forecast, fact.starts_at, fact.ends_at)
        after = integral(result.snapshot.household_load_forecast, fact.starts_at, fact.ends_at)
        assert after == pytest.approx(
            before if fact.energy_wh is None else before * 0.6 + fact.energy_wh
        )
    assert apply(result, value, result.load_replacement_basis) == result


def test_timing_survives_unknown_or_invalid_energy_but_stale_facts_do_not(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    value = partial(snapshot)
    for row in value["load_facts"]:
        row.update(energy_wh=float("nan"), energy_status="provisional")
    result = apply(bundle, value, bundle.load_replacement_basis)
    assert len(result.snapshot.external_load_facts) == 4
    assert all(f.energy_wh is None for f in result.snapshot.external_load_facts)
    assert result.snapshot.household_load_forecast == snapshot.household_load_forecast
    stale = dict(value, valid_until=snapshot.captured_at.isoformat())
    assert not apply(bundle, stale, bundle.load_replacement_basis).snapshot.external_load_facts


def test_no_attribution_keeps_timing_without_subtracting_household_energy(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    result = apply(bundle, partial(snapshot), None)
    assert result.snapshot.external_load_facts
    assert result.snapshot.household_load_forecast == snapshot.household_load_forecast


def test_hc_publication_reaches_hems_as_partial_electrical_advice(tmp_path):
    from types import SimpleNamespace

    from picot_hc.core import Store
    from picot_hc.day_ahead import DayAhead
    from picot_hc.schedule import TZ

    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    local = snapshot.captured_at.astimezone(TZ)
    release = (local + timedelta(hours=1)).replace(second=0, microsecond=0)
    assert release.date() == local.date()
    boundary = release.strftime("%H:%M")
    settings = dict(enabled=True, learning_enabled=True, initial_preheat_minutes=45,
        max_preheat_minutes=180, setback_temperature=17, optimization_band=1,
        windows=[dict(day=d, start=a, end=b, target=t, hard=h)
            for d in range(7) for a,b,t,h in [("00:00",boundary,20,True),
            (boundary,"00:00",17,False)]])
    model = SimpleNamespace(records=[], estimate=lambda *a: {})
    cooling = SimpleNamespace(samples=[], estimate=lambda *a: dict(cooling_rate=0.5))
    sent = []
    DayAhead(Store(tmp_path/"hc.sqlite"),SimpleNamespace(submit=sent.append)).tick(
        settings,True,dict(valid=True,indoor=18.5,outdoor=10,identity="room"),
        "a"*64,model,model,cooling,{}, {}, snapshot.captured_at.timestamp())
    message = sent[-1]["attributes"]
    result = apply(bundle,message,bundle.load_replacement_basis)
    assert result.controlled_load_summary["hc_day_ahead"]["applied"]
    assert result.snapshot.external_load_facts
    stop = next(f for f in result.snapshot.external_load_facts if f.energy_wh == 0)
    assert stop.starts_at == release
    before = integral(snapshot.household_load_forecast,stop.starts_at,stop.ends_at)
    after = integral(result.snapshot.household_load_forecast, stop.starts_at, stop.ends_at)
    assert after == pytest.approx(before * 0.6)


@pytest.mark.parametrize("broken", ["date", "operation", "not_a_row"])
def test_invalid_optional_fact_does_not_suppress_complete_forecast(tmp_path, broken):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    value = payload(snapshot)
    fact = partial(snapshot)["load_facts"][0]
    if broken == "date":
        fact["starts_at"] = "bad"
    elif broken == "operation":
        fact["operation"] = "invalid"
    else:
        fact = None
    value["load_facts"] = [fact]
    result = apply(bundle, value, bundle.load_replacement_basis)
    status = result.controlled_load_summary["hc_day_ahead"]
    assert status["applied"]
    assert status["rejected_timing_facts"] == 1
    assert result.snapshot.household_load_forecast != snapshot.household_load_forecast


def test_one_bad_partial_row_keeps_other_independent_facts(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    value = partial(snapshot)
    value["load_facts"][0]["starts_at"] = "bad"
    result = apply(bundle, value, bundle.load_replacement_basis)
    assert result.controlled_load_summary["hc_day_ahead"]["applied"]
    assert result.controlled_load_summary["hc_day_ahead"]["rejected_timing_facts"] == 1
    assert len(result.snapshot.external_load_facts) == 3


def test_overlap_quarantines_both_rows_but_preserves_unrelated_facts(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    value = partial(snapshot)
    value["load_facts"][0]["ends_at"] = value["load_facts"][1]["ends_at"]
    result = apply(bundle, value, bundle.load_replacement_basis)
    status = result.controlled_load_summary["hc_day_ahead"]
    assert status["applied"]
    assert status["rejected_timing_facts"] == 2
    assert len(result.snapshot.external_load_facts) == 2
    assert all(f.energy_wh != 0 for f in result.snapshot.external_load_facts)
    # Conflicting zero advice must not reduce household energy in that interval.
    left = snapshot.captured_at + timedelta(hours=2)
    right = left + timedelta(hours=1)
    assert integral(result.snapshot.household_load_forecast, left, right) == pytest.approx(
        integral(snapshot.household_load_forecast, left, right))


@pytest.mark.parametrize("change", [dict(contract="wrong"), dict(scope="wrong"),
                                    dict(execution_authorized=True)])
def test_invalid_envelope_never_admits_partial_facts(tmp_path, change):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    bundle = bundle_for(snapshot)
    result = apply(bundle, dict(partial(snapshot), **change), bundle.load_replacement_basis)
    assert not result.snapshot.external_load_facts
    assert result.snapshot.household_load_forecast == snapshot.household_load_forecast
