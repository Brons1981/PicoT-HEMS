"""Unavailable advisory forecasts explain their cause without entering planning."""

import io
import json
from unittest.mock import patch

import pytest
from test_v2_dashboard_redesign import _js_function

from picot.v2.planning_input import HomeAssistantStateReader, SourceBinding


@pytest.mark.parametrize("reasons,expected", [
    (["daily_cold_side_scenario", "no_warmup_measurements",
      "provisional_recent_heat_loss_scaling"], "onvoldoende bruikbare opwarmhistorie"),
    (["fresh_thermal_context_required"], "actuele temperatuur- en regelgegevens ontbreken"),
    (["no_energy_measurements"], "onvoldoende bruikbare energiehistorie"),
    (["no_comparable_energy_measurements"], "geen vergelijkbare energiemetingen"),
    (["forecast_generation_failed"], "aanmaken van de prognose mislukt"),
    (["future_reason"], "oorzaak niet aangeleverd of niet herkend"),
    (None, "oorzaak niet aangeleverd of niet herkend"),
])
def test_unavailable_forecast_explanation_reaches_dashboard(reasons, expected):
    payload = dict(state="unavailable", attributes={
        "contract": "hc-day-ahead:v1", "status": "unavailable", "reasons": reasons,
    })
    with patch("picot.v2.planning_input.urlopen",
               return_value=io.BytesIO(json.dumps(payload).encode())):
        source = HomeAssistantStateReader("test").read(SourceBinding(
            "energy_devices", "hc_day_ahead_forecast", "sensor.picot_hc_day_ahead"))
    assert source.availability == "unavailable"
    assert source.external_load_payload is None
    assert expected in source.error
    view = {"pipeline": [{"stage": 1, "attributes": {"sources": [{
        "semantic_role": source.semantic_role, "category": source.category,
        "availability": source.availability, "error": source.error,
        "entity_id": source.entity_id,
    }]}}]}
    messages = _js_function("dashboardFaults", "renderDashboardFaults",
                            "dashboardFaults(" + json.dumps(view) + ")")
    assert messages == [f"HC-dagprognose: {source.error} (sensor.picot_hc_day_ahead)"]
    assert "Huishoudprognose wordt gebruikt." in messages[0]
    assert "geen bruikbare meting" not in messages[0]
