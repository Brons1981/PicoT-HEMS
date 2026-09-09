from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from picot_energy_devices.contracts import DeviceObservation
from picot_energy_devices.store import EnergyDeviceStore
from picot_energy_devices.web_ui import create_web_server


def _request(url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    request = Request(
        url,
        data=(json.dumps(payload).encode() if payload is not None else None),
        headers=(
            {"Content-Type": "application/json"}
            if payload is not None
            else {}
        ),
        method="POST" if payload is not None else "GET",
    )
    with urlopen(request, timeout=5) as response:
        result = json.loads(response.read())
    assert isinstance(result, dict)
    return result


def test_registry_ui_adds_and_removes_a_discoverable_card(tmp_path: Path) -> None:
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3")
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        added = _request(
            f"{base_url}/api/devices",
            {
                "action": "add",
                "name": "Droger",
                "power_entity_id": "sensor.droger_vermogen",
                "energy_entity_id": "sensor.droger_energie",
                "active_threshold_w": 25,
            },
        )
        view = _request(f"{base_url}/api/view")
        catalog = view["catalog"]
        assert isinstance(catalog, dict)
        cards = catalog["cards"]
        assert isinstance(cards, list)
        assert cards[0]["name"] == "Droger"
        assert cards[0]["profile_status"] == "learning"

        _request(
            f"{base_url}/api/devices",
            {"action": "remove", "device_id": added["device_id"]},
        )
        removed_view = _request(f"{base_url}/api/view")
        removed_catalog = removed_view["catalog"]
        assert isinstance(removed_catalog, dict)
        assert removed_catalog["cards"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_recording_controls_and_detail_api(tmp_path: Path) -> None:
    now = datetime(2026, 9, 9, 16, 0, tzinfo=UTC)
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3", now=lambda: now)
    device = store.add_device(name="Vaatwasser", power_entity_id="sensor.vaatwasser")
    store.record_observation(device.device_id, DeviceObservation(now, 1000))
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    endpoint = base + "/api/devices"
    try:
        _request(endpoint, {"action": "start", "device_id": device.device_id, "name": "Eco"})
        now += timedelta(seconds=30)
        store.record_observation(device.device_id, DeviceObservation(now, 4))
        now += timedelta(seconds=30)
        _request(endpoint, {"action": "finish", "device_id": device.device_id})
        rec = _request(base + "/api/view")["recordings"][device.device_id][0]
        rid = rec["recording_id"]
        detail = _request(base + f"/api/recording?id={rid}")
        assert len(detail["samples"]) == 2
        assert detail["duration_seconds"] == 60
        _request(endpoint, {"action": "rename", "recording_id": rid, "name": "Eco 50"})
        assert _request(base + f"/api/recording?id={rid}")["name"] == "Eco 50"
        _request(endpoint, {"action": "delete_recording", "recording_id": rid})
        assert _request(base + "/api/view")["recordings"][device.device_id] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
