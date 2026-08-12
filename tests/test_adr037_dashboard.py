from __future__ import annotations

from picot.addon.adr037_dashboard import adr037_dashboard_states


def test_adr037_dashboard_reports_blockers() -> None:
    event: dict[str, object] = {
        "adr037_live_ready": False,
        "adr037_pipeline_stage_reached": "projected_household_energy_balance",
        "adr037_live_blockers": [
            "live_storage_capability_snapshot_unavailable",
            "canonical_price_opportunity_set_unwired_to_live_snapshot",
        ],
        "adr037_candidate_count": 0,
        "observer_only": True,
        "control_change_allowed": False,
    }

    state = adr037_dashboard_states(event)["sensor.picot_adr037_observer"]

    assert state["state"] == "blocked"
    attributes = state["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["pipeline_stage"] == "projected_household_energy_balance"
    assert attributes["candidate_count"] == 0
    assert attributes["observer_only"] is True
    assert attributes["control_change_allowed"] is False


def test_adr037_dashboard_reports_winner_when_ready() -> None:
    event: dict[str, object] = {
        "adr037_live_ready": True,
        "adr037_pipeline_stage_reached": "evaluation",
        "adr037_live_blockers": [],
        "current_storage_soc": 1.0,
        "current_storage_energy_wh": 8160.0,
        "live_storage_min_soc_percent": 10.0,
        "live_storage_max_soc_percent": 100.0,
        "live_storage_operating_window_wh": 7344.0,
        "effective_storage_max_soc": 1.0,
        "effective_storage_max_energy_wh": 8160.0,
        "adr037_requirement_energy_wh": 8160.0,
        "adr037_remaining_charge_energy_wh": 0.0,
        "adr037_charge_needed_now": False,
        "price_window_context": "next",
        "price_window_starts_at": "2026-08-12T12:00:00+02:00",
        "price_window_ends_at": "2026-08-12T15:00:00+02:00",
        "adr037_candidate_count": 1,
        "adr037_evaluation_status": "winner_selected",
        "adr037_winning_candidate_id": "candidate-2",
        "adr037_winning_candidate_family": "reserve_first",
        "observer_only": True,
        "control_change_allowed": False,
    }

    state = adr037_dashboard_states(event)["sensor.picot_adr037_observer"]

    assert state["state"] == "ready"
    attributes = state["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["current_storage_soc"] == 1.0
    assert attributes["live_storage_min_soc_percent"] == 10.0
    assert attributes["live_storage_max_soc_percent"] == 100.0
    assert attributes["live_storage_operating_window_wh"] == 7344.0
    assert attributes["remaining_charge_energy_wh"] == 0.0
    assert attributes["charge_needed_now"] is False
    assert attributes["price_window_starts_at"] == "2026-08-12T12:00:00+02:00"
    assert attributes["requirement_energy_wh"] == 8160.0
    assert attributes["candidate_count"] == 1
    assert attributes["winning_candidate_id"] == "candidate-2"
    assert attributes["winning_candidate_family"] == "reserve_first"
