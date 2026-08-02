from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from urllib.request import Request

import pytest

from picot.adapters.home_assistant_http import HomeAssistantHttpTransport
from picot.domain.home_assistant import (
    HomeAssistantDispatchMode,
    HomeAssistantServiceCall,
)

NOW = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)


class _Response:
    status = 200


class _RecordingOpener:
    def __init__(self) -> None:
        self.request: Request | None = None
        self.timeout: float | None = None

    def __call__(self, request: Request, *, timeout: float) -> object:
        self.request = request
        self.timeout = timeout
        return _Response()


def _call() -> HomeAssistantServiceCall:
    return HomeAssistantServiceCall(
        command_id="ha-command-1",
        source_request_id="request-1",
        plan_set_id="plan-set-1",
        plan_id="plan-1",
        segment_id="segment-1",
        execution_scope_id="battery-main",
        capability_id="battery-charge",
        mapping_id="ha-mapping-1",
        mapping_version=1,
        domain="input_number",
        service="set_value",
        target=(("entity_id", "input_number.zendure_2400_ac_handmatig_vermogen"),),
        service_data=(("value", 1200.0),),
        created_at=NOW,
        dispatch_mode=HomeAssistantDispatchMode.LIVE,
        implementation_version="home-assistant-adapter-v1",
    )


def test_transport_posts_exact_home_assistant_service_call() -> None:
    opener = _RecordingOpener()
    transport = HomeAssistantHttpTransport(
        base_url="http://192.168.6.26:8123/",
        access_token="secret-token",
        transport_mode=HomeAssistantDispatchMode.LIVE,
        opener=opener,
    )

    status = transport.send(_call())

    assert status == 200
    assert opener.timeout == 10.0
    assert opener.request is not None
    assert opener.request.full_url == (
        "http://192.168.6.26:8123/api/services/input_number/set_value"
    )
    assert opener.request.method == "POST"
    assert opener.request.get_header("Authorization") == "Bearer secret-token"
    assert opener.request.get_header("Content-type") == "application/json"
    request_data = cast(bytes, opener.request.data)
    assert json.loads(request_data) == {
        "entity_id": "input_number.zendure_2400_ac_handmatig_vermogen",
        "value": 1200.0,
    }


def test_transport_defaults_to_dry_run_and_refuses_network_send() -> None:
    opener = _RecordingOpener()
    transport = HomeAssistantHttpTransport(
        base_url="http://192.168.6.26:8123",
        access_token="secret-token",
        opener=opener,
    )

    with pytest.raises(RuntimeError, match="not enabled"):
        transport.send(_call())

    assert opener.request is None


def test_live_transport_rejects_non_live_service_call() -> None:
    transport = HomeAssistantHttpTransport(
        base_url="http://192.168.6.26:8123",
        access_token="secret-token",
        transport_mode=HomeAssistantDispatchMode.LIVE,
    )
    dry_run_call = replace(_call(), dispatch_mode=HomeAssistantDispatchMode.DRY_RUN)

    with pytest.raises(RuntimeError, match="only LIVE"):
        transport.send(dry_run_call)


def test_transport_rejects_invalid_runtime_configuration() -> None:
    with pytest.raises(ValueError, match="absolute"):
        HomeAssistantHttpTransport(base_url="192.168.6.26:8123", access_token="token")
    with pytest.raises(ValueError, match="token"):
        HomeAssistantHttpTransport(
            base_url="http://192.168.6.26:8123",
            access_token=" ",
        )
