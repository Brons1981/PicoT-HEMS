"""Runtime composition for the independent Energy Devices add-on."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread

from picot_energy_devices.contracts import DeviceObservation
from picot_energy_devices.ev_sessions import EVSessionManager, instant
from picot_energy_devices.home_assistant import HomeAssistantClient
from picot_energy_devices.regulation import (
    PowerReport,
    RegulationObserver,
    RegulationSnapshotStore,
    create_regulation_api,
)
from picot_energy_devices.shelly_ev import ShellyEVSource
from picot_energy_devices.store import EnergyDeviceStore
from picot_energy_devices.web_ui import create_web_server

DATA_PATH = Path("/data/picot_energy_devices.sqlite3")
OPTIONS_PATH = Path("/data/options.json")


def load_options(path: Path = OPTIONS_PATH) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("add-on options must be an object")
    return payload


def poll_once(
    *,
    store: EnergyDeviceStore,
    client: HomeAssistantClient,
    catalog_entity_id: str,
    observed_at: datetime,
) -> None:
    for device in store.devices():
        try:
            power = client.measurement(client.state(device.power_entity_id), quantity="power")
            energy = (
                client.measurement(client.state(device.energy_entity_id), quantity="energy")
                if device.energy_entity_id is not None
                else None
            )
            store.record_observation(
                device.device_id,
                DeviceObservation(
                    observed_at=observed_at,
                    power_w=max(0.0, power),
                    energy_meter_wh=energy,
                ),
            )
        except (OSError, ValueError) as error:
            store.record_unavailable(device.device_id, str(error), observed_at=observed_at)
    client.publish_catalog(catalog_entity_id, store.catalog())


def regulation_poll_once(
    *,
    client: HomeAssistantClient,
    raw_entity: str,
    battery_entity: str,
    ev_entity: str,
    observer: RegulationObserver | None = None,
    snapshots: RegulationSnapshotStore | None = None,
    ev_source: ShellyEVSource | None = None,
) -> None:
    raw = None
    try:
        raw = PowerReport.from_state(client.state(raw_entity))
        battery = PowerReport.from_state(client.state(battery_entity))
        ev = (ev_source.read().power if ev_source is not None
              else PowerReport.from_state(client.state(ev_entity)))
        result = (observer or RegulationObserver()).evaluate(
            raw,
            battery,
            ev,
            now=datetime.now(UTC),
        )
    except (OSError, ValueError) as error:
        if observer is not None:
            observer.reset()
        result = {
            "observer_only": True,
            "actuation_authority": False,
            "status": "blocked",
            "candidate_w": None,
            "reason": str(error),
            "fallback": "no_control_value",
            "evaluated_at": datetime.now(UTC).isoformat(),
        }
    result["ev_measurement_source"] = "local_rpc" if ev_source is not None else "home_assistant"
    client.publish_regulation_shadow(result)
    if snapshots is not None:
        api_result = result
        if not snapshots.control_enabled and raw is not None:
            now = datetime.now(UTC)
            age = (now - raw.reported_at).total_seconds()
            if 0 <= age <= 3:
                api_result = dict(
                    result,
                    status="ready",
                    reason=None,
                    raw_grid_w=raw.watts,
                    evaluated_at=now.isoformat(),
                    source_measured_at=raw.reported_at.isoformat(),
                    source_ages_seconds=[age],
                )
        client.publish_regulation_policy(snapshots.update(api_result))


def _regulation_loop(
    client: HomeAssistantClient,
    options: dict[str, object],
    snapshots: RegulationSnapshotStore | None = None,
    ev_source: ShellyEVSource | None = None,
) -> None:
    entities = {
        "raw_entity": str(
            options.get(
                "regulation_raw_entity",
                "sensor.ct_shelly_pro_3em_api_raw_2",
            )
        ),
        "battery_entity": str(
            options.get(
                "regulation_battery_entity",
                "sensor.zendure_2400_ac_vermogen_aansturing",
            )
        ),
        "ev_entity": str(
            options.get(
                "regulation_ev_entity",
                "sensor.shellyplugsg3_d885ac1e8c94_vermogen",
            )
        ),
    }
    if any(not value.startswith("sensor.") for value in entities.values()):
        raise ValueError("regulation source entities must be sensors")
    observer = RegulationObserver()
    while True:
        started = time.perf_counter()
        try:
            regulation_poll_once(client=client, observer=observer, snapshots=snapshots,
                                 ev_source=ev_source, **entities)
        except (OSError, ValueError) as error:
            print(
                json.dumps({"event": "regulation_shadow_failed", "error": str(error)}),
                flush=True,
            )
        time.sleep(max(0.0, 1.0 - (time.perf_counter() - started)))


def ev_poll_once(
    manager: EVSessionManager, client: HomeAssistantClient,
    ev_source: ShellyEVSource | None = None,
) -> None:
    power = None
    measured = None
    switch_state = "unavailable"
    switch_changed_at = None
    if ev_source is not None:
        try:
            local = ev_source.read()
            power, measured = local.power.watts, local.power.reported_at
            switch_state = "on" if local.output else "off"
            switch_changed_at = local.switch_changed_at
        except (OSError, ValueError):
            pass
    else:
        try:
            report = PowerReport.from_state(client.state(manager.power_entity))
            power, measured = report.watts, report.reported_at
        except (OSError, ValueError):
            pass
        try:
            switch_payload = client.state(manager.switch_entity)
            switch_state = str(switch_payload.get("state", "unavailable"))
            if switch_payload.get("last_changed") is not None:
                switch_changed_at = instant(switch_payload["last_changed"])
        except (OSError, ValueError):
            pass
    manager.tick(
        measured_at=measured,
        power_w=power,
        switch_state=switch_state,
        switch_changed_at=switch_changed_at,
        set_switch=lambda enabled: client.set_ev_switch(manager.switch_entity, enabled),
    )
    snapshot = manager.snapshot()
    snapshot["ev_measurement_source"] = (
        "local_rpc" if ev_source is not None else "home_assistant"
    )
    client.publish_ev_session(snapshot)


def _ev_loop(
    manager: EVSessionManager, client: HomeAssistantClient,
    ev_source: ShellyEVSource | None = None,
) -> None:
    while True:
        started = time.perf_counter()
        try:
            ev_poll_once(manager, client, ev_source)
        except (OSError, ValueError, sqlite3.Error) as error:
            print(json.dumps({"event": "ev_session_poll_failed", "error": str(error)}), flush=True)
        time.sleep(max(0.0, 1.0 - (time.perf_counter() - started)))


def main() -> None:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("Supervisor token is required")
    options = load_options()
    raw_interval = options.get("poll_interval_seconds", 10)
    if isinstance(raw_interval, bool) or not isinstance(raw_interval, (int, float, str)):
        raise ValueError("poll interval must be numeric")
    interval = max(5.0, float(raw_interval))
    catalog_entity_id = str(
        options.get("catalog_entity_id", "sensor.picot_energy_devices_catalog")
    ).strip()
    if not catalog_entity_id.startswith("sensor."):
        raise ValueError("catalog entity ID must be a sensor")
    store = EnergyDeviceStore(DATA_PATH, maximum_sample_gap_seconds=max(60.0, interval * 5))
    client = HomeAssistantClient(token)
    local_url = str(options.get("ev_local_rpc_url", "")).strip()
    ev_source = ShellyEVSource(local_url) if local_url else None
    if ev_source is not None:
        Thread(target=ev_source.run, name="ev-local-rpc", daemon=True).start()
    api_enabled = options.get("regulation_api_enabled", False) is True
    snapshots = (
        RegulationSnapshotStore(
            control_enabled=api_enabled
            and options.get("regulation_control_enabled", False) is True,
        )
        if api_enabled
        else None
    )
    if snapshots is None:
        try:
            client.publish_regulation_policy({"control_enabled": False, "status": "disabled"})
        except (OSError, ValueError) as error:
            print(
                json.dumps({"event": "regulation_policy_disable_failed", "error": str(error)}),
                flush=True,
            )
    if snapshots is not None:
        api = create_regulation_api(snapshots, host="0.0.0.0", port=8101)
        Thread(target=api.serve_forever, name="ev-regulation-api", daemon=True).start()
    if api_enabled or options.get("regulation_shadow_enabled", False) is True:
        Thread(
            target=_regulation_loop,
            args=(HomeAssistantClient(token), options, snapshots, ev_source),
            name="ev-regulation-shadow",
            daemon=True,
        ).start()
    ev_sessions = None
    if options.get("ev_sessions_enabled", False) is True:
        ev_sessions = EVSessionManager(
            DATA_PATH,
            power_entity=str(
                options.get("ev_power_entity", "sensor.shellyplugsg3_d885ac1e8c94_vermogen")
            ),
            switch_entity=str(options.get("ev_switch_entity", "switch.shellyplugsg3_d885ac1e8c94")),
        )
        Thread(
            target=_ev_loop,
            args=(ev_sessions, HomeAssistantClient(token), ev_source),
            name="ev-sessions",
            daemon=True,
        ).start()
    server = create_web_server(store, host="0.0.0.0", port=8100, ev_sessions=ev_sessions)
    Thread(target=server.serve_forever, name="energy-devices-web", daemon=True).start()
    while True:
        started = time.perf_counter()
        try:
            poll_once(
                store=store,
                client=client,
                catalog_entity_id=catalog_entity_id,
                observed_at=datetime.now(UTC),
            )
            print(
                json.dumps(
                    {
                        "event": "energy_device_poll",
                        "device_count": len(store.devices()),
                        "database_size_bytes": store.database_size_bytes(),
                        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
        except OSError as error:
            print(json.dumps({"event": "catalog_publish_failed", "error": str(error)}), flush=True)
        time.sleep(max(0.0, interval - (time.perf_counter() - started)))


if __name__ == "__main__":
    main()
