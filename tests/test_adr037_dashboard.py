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
        "adr037_requirement_energy_wh": 2400.0,
        "adr037_candidate_count": 3,
        "adr037_evaluation_status": "selected",
        "adr037_winning_candidate_id": "candidate-2",
        "adr037_winning_candidate_family": "grid_charge",
        "observer_only": True,
        "control_change_allowed": False,
    }

    state = adr037_dashboard_states(event)["sensor.picot_adr037_observer"]

    assert state["state"] == "ready"
    attributes = state["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["requirement_energy_wh"] == 2400.0
    assert attributes["candidate_count"] == 3
    assert attributes["winning_candidate_id"] == "candidate-2"
    assert attributes["winning_candidate_family"] == "grid_charge"
