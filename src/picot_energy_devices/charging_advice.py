"""Slow advisory exchange, isolated from the one-second physical EV loop."""

from __future__ import annotations

import json
import sqlite3
import time

from picot_energy_devices.diagnostics import DiagnosticsRecorder
from picot_energy_devices.ev_sessions import EVSessionManager
from picot_energy_devices.home_assistant import HomeAssistantClient

REQUEST_ENTITY = "sensor.picot_ev_charging_request"
ADVICE_ENTITY = "sensor.picot_ev_charging_advice"


def exchange_once(manager: EVSessionManager, client: HomeAssistantClient,
                  diagnostics: DiagnosticsRecorder | None = None) -> None:
    envelope = manager.advice_exchange()
    client.publish_catalog(REQUEST_ENTITY, envelope)
    if not envelope.get("request"):
        if diagnostics is not None:
            diagnostics.record("ev_advice", {"request": None, "advice": None})
        return
    payload = client.state(ADVICE_ENTITY)
    advice = payload.get("attributes")
    if isinstance(advice, dict):
        accepted = manager.receive_advice(advice)
    else:
        accepted = False
    if diagnostics is not None:
        diagnostics.record("ev_advice", {"request": envelope.get("request"),
                                        "advice": advice, "accepted": accepted})


def exchange_loop(manager: EVSessionManager, client: HomeAssistantClient,
                  diagnostics: DiagnosticsRecorder | None = None) -> None:
    while True:
        try:
            exchange_once(manager, client, diagnostics)
        except (OSError, ValueError, sqlite3.Error) as error:
            print(json.dumps({"event": "ev_advice_exchange_failed", "error": str(error)}),
                  flush=True)
        time.sleep(15)
