from __future__ import annotations

from picot.addon.diagnostics_dashboard import diagnostics_dashboard_states


def _event() -> dict[str, object]:
    return {
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


def test_price_entry_observation_is_visible_but_never_control_input() -> None:
    state = diagnostics_dashboard_states(_event())["sensor.picot_price_entry_observation"]

    assert state["state"] == "better_later_price_exists"
    attributes = state["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["observation_only"] is True
    assert attributes["replan_input"] is False
    assert attributes["better_later_price_exists"] is True
    assert attributes["best_later_saving_eur_per_kwh"] == 0.031


def test_price_window_visual_entities_are_numeric_and_observation_only() -> None:
    states = diagnostics_dashboard_states(_event())

    overlay = states["sensor.picot_price_opportunity_overlay"]
    assert overlay["state"] == 1
    overlay_attributes = overlay["attributes"]
    assert isinstance(overlay_attributes, dict)
    assert overlay_attributes["starts_at"] == "2026-08-11T10:45:00+02:00"
    assert overlay_attributes["ends_at"] == "2026-08-11T16:30:00+02:00"
    assert overlay_attributes["observation_only"] is True
    assert overlay_attributes["replan_input"] is False

    best = states["sensor.picot_best_later_price"]
    assert best["state"] == 0.127
    best_attributes = best["attributes"]
    assert isinstance(best_attributes, dict)
    assert best_attributes["starts_at"] == "2026-08-11T13:00:00+02:00"
    assert best_attributes["saving_eur_per_kwh"] == 0.031
    assert best_attributes["observation_only"] is True
    assert best_attributes["replan_input"] is False


def test_price_window_visual_entities_are_unknown_without_observation() -> None:
    states = diagnostics_dashboard_states({})

    assert states["sensor.picot_price_opportunity_overlay"]["state"] == "unknown"
    assert states["sensor.picot_best_later_price"]["state"] == "unknown"
