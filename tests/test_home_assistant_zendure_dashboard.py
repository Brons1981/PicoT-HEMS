from __future__ import annotations

import json
from typing import Any

import pytest

from picot.addon.zendure_dashboard import (
    publish_zendure_dashboard_states,
    zendure_dashboard_states,
)


def _event() -> dict[str, object]:
    return {
        "zendure_status": "available",
        "zendure_source": "Home Assistant Zendure HA ZenSDK",
        "zendure_error": None,
        "zendure_observed_at": "2026-08-02T20:00:00+02:00",
        "zendure_soc_percent": 82.0,
        "zendure_actual_mode": "Ontladen",
        "zendure_requested_mode": "Alleen slim ontladen",
        "zendure_signed_power_w": -86.0,
        "zendure_charge_power_w": 0.0,
        "zendure_discharge_power_w": 86.0,
        "zendure_power_to_house_w": 86.0,
        "zendure_power_from_house_w": 0.0,
        "zendure_soc_limit_status": "Binnen limiet",
        "zendure_error_status": "Geen fout",
        "zendure_power_consistent": True,
    }


def test_zendure_dashboard_states_publish_semantic_entities() -> None:
    states = zendure_dashboard_states(_event())

    assert states["sensor.picot_zendure_status"]["state"] == "available"
    assert states["sensor.picot_zendure_soc"]["state"] == 82.0
    assert states["sensor.picot_zendure_actual_mode"]["state"] == "Ontladen"
    assert states["sensor.picot_zendure_power"]["state"] == -86.0
    assert states["sensor.picot_zendure_charge_power"]["state"] == 0.0
    assert states["sensor.picot_zendure_discharge_power"]["state"] == 86.0
    power_attributes = states["sensor.picot_zendure_power"]["attributes"]
    assert isinstance(power_attributes, dict)
    assert power_attributes["unit_of_measurement"] == "W"
    assert power_attributes["device_class"] == "power"
    assert power_attributes["power_consistent"] is True


def test_zendure_dashboard_states_keep_unavailable_source_isolated() -> None:
    event = _event()
    event.update(
        {
            "zendure_status": "unavailable",
            "zendure_error": "source failed",
            "zendure_soc_percent": None,
            "zendure_signed_power_w": None,
        }
    )

    states = zendure_dashboard_states(event)

    assert states["sensor.picot_zendure_status"]["state"] == "unavailable"
    assert states["sensor.picot_zendure_soc"]["state"] is None
    attributes = states["sensor.picot_zendure_soc"]["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["source_error"] == "source failed"


def test_publish_zendure_dashboard_states_posts_every_entity() -> None:
    requests: list[Any] = []

    class Response:
        status = 201

    def opener(request: Any, *, timeout: float) -> Response:
        assert timeout == 10.0
        requests.append(request)
        return Response()

    publish_zendure_dashboard_states(_event(), "token", opener=opener)

    expected = zendure_dashboard_states(_event())
    assert len(requests) == len(expected)
    for request in requests:
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer token"
        payload = json.loads(request.data.decode("utf-8"))
        assert "state" in payload
        assert "attributes" in payload


def test_publish_zendure_dashboard_states_rejects_failed_post() -> None:
    class Response:
        status = 500

    def opener(request: Any, *, timeout: float) -> Response:
        return Response()

    with pytest.raises(RuntimeError, match="rejected Zendure dashboard state"):
        publish_zendure_dashboard_states(_event(), "token", opener=opener)
