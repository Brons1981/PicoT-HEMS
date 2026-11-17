"""Slow advisory exchange, isolated from the one-second physical EV loop."""

from __future__ import annotations

import json
import sqlite3

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
    # Publish automatic acceptance immediately instead of waiting for the next poll.
    updated = manager.advice_exchange()
    if (updated.get("request") != envelope.get("request")
            or updated.get("selected_advice") != envelope.get("selected_advice")):
        client.publish_catalog(REQUEST_ENTITY, updated)
    if diagnostics is not None:
        diagnostics.record("ev_advice", {"request": envelope.get("request"),
                                        "advice": advice, "accepted": accepted})


def exchange_loop(manager: EVSessionManager, client: HomeAssistantClient,
                  diagnostics: DiagnosticsRecorder | None = None) -> None:
    while True:
        try:
            if manager.soc_entity:
                try:
                    soc = client.state(manager.soc_entity)
                    manager.observe_soc(soc.get("state"),
                                        soc.get("last_reported") or soc.get("last_updated"))
                except (OSError, ValueError):
                    manager.observe_soc(None, None)
            if manager.plug_entity:
                try:
                    plug = client.state(manager.plug_entity)
                    manager.observe_plug(str(plug.get("state", "unavailable")),
                                         plug.get("last_changed"))
                except (OSError, ValueError):
                    manager.observe_plug("unavailable", None)
            manager.refresh_automatic_request()
            exchange_once(manager, client, diagnostics)
        except (OSError, ValueError, sqlite3.Error) as error:
            print(json.dumps({"event": "ev_advice_exchange_failed", "error": str(error)}),
                  flush=True)
        manager.exchange_wake.wait(2)
        manager.exchange_wake.clear()
