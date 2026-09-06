"""Runtime composition for the independent Energy Devices add-on."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread

from picot_energy_devices.contracts import DeviceObservation
from picot_energy_devices.home_assistant import HomeAssistantClient
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
    server = create_web_server(store, host="0.0.0.0", port=8100)
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
