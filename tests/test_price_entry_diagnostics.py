from __future__ import annotations

from picot.addon.diagnostics_dashboard import diagnostics_dashboard_states


def test_price_entry_observation_is_visible_but_never_control_input() -> None:
    event: dict[str, object] = {
        "telemetry_updated_at": "2026-08-11T10:40:00+02:00",
        "price_entry_observation_status": "better_later_price_exists",
        "price_entry_opportunity_rank": 1,
        "price_entry_opportunity_starts_at": "2026-08-11T10:45:00+02:00",
        "price_entry_opportunity_ends_at": "2026-08-11T16:30:00+02:00",
        "price_entry_reference_starts_at": "2026-08-11T10:45:00+02:00",
        "price_entry_reference_price_eur_per_kwh": 0.158,
        "price_entry_better_later_price_exists": True,
        "price_entry_best_later_starts_at": "2026-08-11T13:00:00+02:00",
        "price_entry_best_later_price_eur_per_kwh": 0.127,
        "price_entry_best_later_saving_eur_per_kwh": 0.031,
        "price_entry_alternatives": [
            {
                "delay_minutes": 30,
                "status": "available",
                "starts_at": "2026-08-11T11:15:00+02:00",
                "price_eur_per_kwh": 0.143,
                "cheaper_than_entry": True,
            }
        ],
        "price_entry_limitation": "price-only counterfactual",
    }

    state = diagnostics_dashboard_states(event)["sensor.picot_price_entry_observation"]

    assert state["state"] == "better_later_price_exists"
    attributes = state["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["observation_only"] is True
    assert attributes["replan_input"] is False
    assert attributes["better_later_price_exists"] is True
    assert attributes["best_later_saving_eur_per_kwh"] == 0.031
