import json

from test_dashboard_attention import dom_run
from test_plan_decision_dashboard import explanation, render


def narrative(**changes):
    return {
        "energy_available": True, "projected_at": "2026-10-31T19:00:00Z",
        "days": [{"date": "2026-11-01", "pv_charge_kwh": 2.4, "pv_other_kwh": 1.1,
                  "grid_charge_kwh": 3.2, "full_at": "2026-11-01T12:15:00Z"}],
        "windows": [
            {"kind": "standby", "starts_at": "2026-10-31T19:00:00Z",
             "ends_at": "2026-10-31T22:00:00Z"},
            {"kind": "grid_charge", "starts_at": "2026-10-31T22:00:00Z",
             "ends_at": "2026-11-01T00:00:00Z"},
        ], **changes,
    }


def narrative_text(value, at="2026-10-31T19:30:00Z"):
    return dom_run(["formatDutchNumber", "renderPlanNarrative"],
        "const lines=[]; renderPlanNarrative(" + json.dumps(value) +
        ", text=>lines.push(text),new Date(" + json.dumps(at) + "));"
        "console.log(JSON.stringify(lines.join('|')));")


def test_practical_summary_shows_real_energy_and_dated_windows_in_dutch_time():
    text = narrative_text(narrative())
    for expected in ("Morgen (1 november)", "2,40 kWh", "1,10 kWh", "3,20 kWh",
                     "13:15 uur 100%", "31 oktober om 23:00", "1 november om 01:00",
                     "stand-by", "vóór laadverliezen"):
        assert expected in text
    assert "voordeliger" not in text


def test_missing_energy_is_not_zero_and_expired_dates_and_windows_disappear():
    text = narrative_text(narrative(energy_available=False, days=[]))
    assert "nog niet vastgelegd" in text and "0,00 kWh" not in text
    text = narrative_text(narrative(), at="2026-11-02T10:00:00Z")
    assert "2,40" not in text and "stand-by" not in text and "100%" not in text


def test_standby_euros_require_explicit_attribution_not_general_route_savings():
    base = explanation(narrative=narrative())
    text = render(base)["text"]
    assert "geen afzonderlijk" in text
    assert "voordeliger dan batterijondersteuning" not in text
    text = render({**base, "standby_comparison": {
        "starts_at": "2026-10-31T19:00:00Z", "ends_at": "2026-10-31T22:00:00Z",
        "benefit_eur": 0.123,
    }})["text"]
    assert "0,123" in text and "voordeliger dan batterijondersteuning" in text
    assert "hele vergelijkingsperiode" in text


def test_assumptions_do_not_have_double_full_stops():
    assert "prognose.." not in render(explanation(
        household_assumption="Verbruik uit de prognose."))["text"]


def test_normal_floor_and_economic_standby_have_distinct_explanations():
    operation = {"minimum_soc_percent": 10, "floor_status": "projected",
                 "floor_at": "2026-10-31T21:00:00Z", "support_until": "2026-10-31T21:00:00Z",
                 "next_charge_at": "2026-10-31T22:00:00Z"}
    text = narrative_text(narrative(operation=operation))
    assert "ondersteunt het huis naar verwachting tot" in text
    assert "ondergrens van 10,00%" in text
    assert "normale werking, geen afzonderlijk besparingsblok" in text
    assert "volgende geplande laadvenster" in text
    assert "voordeliger" not in text
    operation.update(floor_status="reached")
    text = narrative_text(narrative(operation=operation))
    assert "Stand-by bij de ondergrens" in text
    assert "heeft 10,00% bereikt" in text


def test_unknown_floor_timing_is_explicit_even_without_other_narrative():
    text = narrative_text(narrative(days=[], windows=[], operation={
        "minimum_soc_percent": 10, "floor_status": "unknown", "floor_at": None,
        "support_until": None, "next_charge_at": None}))
    assert "nog niet betrouwbaar voorspeld" in text
    assert "voordeliger" not in text


def test_standby_block_energy_and_costs_are_separate_from_route_saving():
    comparison = {"starts_at": "2026-11-06T21:45:00Z",
                  "ends_at": "2026-11-07T08:30:00Z", "benefit_eur": 0.097,
                  "usage": {"household_kwh": 3.09055, "solar_used_kwh": 0.14495,
                            "grid_kwh": 2.94560, "grid_cost_eur": 1.247956}}
    text = render(explanation(standby_comparison=comparison))["text"]
    for expected in ("3,09 kWh", "0,14 kWh", "2,95 kWh", "1,248", "0,097",
                     "afnamekosten binnen het stand-byblok", "later bijladen",
                     "terugleveropbrengsten"):
        assert expected in text
    comparison.pop("usage")
    text = render(explanation(standby_comparison=comparison))["text"]
    assert "nog niet volledig beschikbaar" in text
    assert "0,00 kWh" not in text
