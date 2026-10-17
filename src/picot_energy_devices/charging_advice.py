"""Slow advisory exchange, isolated from the one-second physical EV loop."""

from __future__ import annotations

import json
import sqlite3
import time

from picot_energy_devices.ev_sessions import EVSessionManager
from picot_energy_devices.home_assistant import HomeAssistantClient

REQUEST_ENTITY = "sensor.picot_ev_charging_request"
ADVICE_ENTITY = "sensor.picot_ev_charging_advice"


def exchange_once(manager: EVSessionManager, client: HomeAssistantClient) -> None:
    envelope = manager.advice_exchange()
    client.publish_catalog(REQUEST_ENTITY, envelope)
    if not envelope.get("request"):
        return
    payload = client.state(ADVICE_ENTITY)
    advice = payload.get("attributes")
    if isinstance(advice, dict):
        manager.receive_advice(advice)


def exchange_loop(manager: EVSessionManager, client: HomeAssistantClient) -> None:
    while True:
        try:
            exchange_once(manager, client)
        except (OSError, ValueError, sqlite3.Error) as error:
            print(json.dumps({"event": "ev_advice_exchange_failed", "error": str(error)}),
                  flush=True)
        time.sleep(15)
