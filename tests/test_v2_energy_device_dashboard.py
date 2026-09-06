import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from picot.v2.web_ui import DASHBOARD_HTML, WebViewStore, create_web_server


def _catalog() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "available",
        "source_entity_id": "sensor.picot_energy_devices_catalog",
        "revision": 1,
        "generated_at": "2026-09-06T10:00:00+00:00",
        "observer_only": True,
        "planning_authority": False,
        "card_count": 1,
        "cards": [
            {
                "card_id": "energy-device-card:dryer",
                "name": "Droger",
                "profile_status": "learning",
            }
        ],
        "error": None,
    }


def _placements() -> dict[str, object]:
    return {
        "schema_version": 1,
        "observer_only": True,
        "planning_authority": False,
        "placements": [],
    }


def test_optional_catalog_overlays_dashboard_without_replacing_plan() -> None:
    store = WebViewStore()
    store.publish({"run_id": "unchanged-plan", "pipeline": []})
    before = json.loads(store.latest_json() or "{}")

    store.publish_energy_device_catalog(_catalog())
    store.publish_energy_device_placements(_placements())
    after = json.loads(store.latest_json() or "{}")

    assert before["run_id"] == after["run_id"] == "unchanged-plan"
    assert after["energy_device_catalog"]["card_count"] == 1
    assert after["energy_device_placements"]["planning_authority"] is False


def test_energy_device_timeline_update_endpoint_remains_observer_only() -> None:
    store = WebViewStore()
    store.publish({"run_id": "run-1", "pipeline": []})

    def update(payload: dict[str, object]) -> dict[str, object]:
        assert payload["action"] == "add"
        return {
            "status": "energy_device_timeline_updated",
            "energy_device_catalog": _catalog(),
            "energy_device_placements": _placements(),
            "planner_unchanged": True,
        }

    store.set_energy_device_placement_update(update)
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/energy-device-placements",
            data=json.dumps({"action": "add"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["planner_unchanged"] is True


def test_dashboard_exposes_selectable_cards_and_timeline_placements() -> None:
    assert 'data-tab="devices"' in DASHBOARD_HTML
    assert 'id="energy-device-card-select"' in DASHBOARD_HTML
    assert 'id="energy-device-start"' in DASHBOARD_HTML
    assert 'fetch("api/energy-device-placements"' in DASHBOARD_HTML
    assert 'kind: "energy-device-placement"' in DASHBOARD_HTML
    assert "het actieve MEP-plan is ongewijzigd" in DASHBOARD_HTML


def test_catalog_is_not_part_of_canonical_planning_snapshot() -> None:
    root = Path(__file__).parents[1] / "src" / "picot" / "v2"
    planning_input = (root / "planning_input.py").read_text(encoding="utf-8")
    contracts = (root / "contracts.py").read_text(encoding="utf-8")

    assert "energy_device_catalog" not in planning_input
    assert "energy_device_catalog" not in contracts
