"""Live presentation must not wait for planning or assert command success."""
import json
from datetime import UTC, datetime, timedelta
from threading import Thread
from urllib.request import urlopen

from picot.v2.web_ui import WebViewStore, create_web_server

NOW = datetime(2026, 10, 24, 18, tzinfo=UTC)


def observation(mode="Standby", at=NOW, availability="available"):
    return dict(active_mode=mode, observed_at=at.isoformat(),
                mode_changed_at=(at-timedelta(minutes=5)).isoformat(),
                availability=availability, source_entity_id="input_select.mode", error=None)


def old_view():
    return {"run_id": "unchanged-plan", "pipeline": [],
            "zendure_now": dict(active_mode="Nul op de meter", origin="picot",
                                observed_at=(NOW-timedelta(minutes=2)).isoformat(),
                                planned_mode="Snel opladen", set_at="old",
                                last_result_nl="Old command accepted")}


def test_live_status_available_before_first_planning_run():
    store = WebViewStore()
    store.publish_storage_status(observation())
    assert store.storage_status()["active_mode"] == "Standby"
    assert store.latest_json() is None


def test_new_observation_survives_later_publication_of_older_plan():
    store = WebViewStore()
    store.publish(old_view())
    before = store.latest_json()
    store.publish_storage_status(observation())
    # Lightweight updates must not serialize/notify the entire planning view.
    assert store.latest_json() == before
    assert store.storage_status()["active_mode"] == "Standby"
    store.publish(old_view())
    latest = json.loads(store.latest_json())
    assert latest["run_id"] == "unchanged-plan"
    assert latest["zendure_now"]["active_mode"] == "Standby"
    assert latest["zendure_now"]["planned_mode"] == "Snel opladen"
    assert latest["zendure_now"]["origin"] == "unknown"
    assert latest["zendure_now"]["set_at"] is None


def test_out_of_order_observation_does_not_roll_back_mode():
    store = WebViewStore()
    store.publish_storage_status(observation())
    store.publish_storage_status(observation("Nul op de meter", NOW-timedelta(seconds=10)))
    assert store.storage_status()["active_mode"] == "Standby"


def test_unavailable_is_not_an_active_or_confirmed_mode():
    store = WebViewStore()
    store.publish_storage_status(observation())
    store.publish_storage_status(observation(None, NOW+timedelta(seconds=10), "unavailable"))
    assert store.storage_status()["active_mode"] is None
    assert store.storage_status()["availability"] == "unavailable"


def test_lightweight_status_http_is_uncached_and_available_before_plan():
    store = WebViewStore()
    store.publish_storage_status(observation())
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/storage-status", timeout=2) as r:
            assert r.headers["Cache-Control"] == "no-store"
            assert json.load(r)["active_mode"] == "Standby"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_observer_uses_received_time_not_last_change_and_never_claims_execution():
    from picot.v2.storage_status_observation import observe_storage_status
    from picot.v2.zendure_mode_capabilities import derive_zendure_mode_capability_evidence
    evidence = derive_zendure_mode_capability_evidence(
        {"state": "Standby", "last_changed": (NOW-timedelta(hours=3)).isoformat(),
         "attributes": {"options": ["Standby", "Nul op de meter"]}},
        captured_at=NOW, source_entity_id="input_select.mode",
        capability_id="battery", execution_scope_id="home",
    )
    rows = []
    observe_storage_status(read=lambda: evidence, publish=rows.append,
                           source_entity_id="input_select.mode")
    assert rows[0]["observed_at"] == NOW.isoformat()
    assert rows[0]["mode_changed_at"] == (NOW-timedelta(hours=3)).isoformat()
    assert rows[0]["active_mode"] == "Standby"
    assert "planned_mode" not in rows[0]
    assert "last_result_nl" not in rows[0]


def test_observer_reports_failure_and_recovers():
    from picot.v2.storage_status_observation import observe_storage_status
    from picot.v2.zendure_mode_capabilities import derive_zendure_mode_capability_evidence
    rows = []
    def broken():
        raise ValueError("Do not expose response contents")
    observe_storage_status(read=broken, publish=rows.append, source_entity_id="input_select.mode")
    assert rows[0]["availability"] == "unavailable"
    assert rows[0]["active_mode"] is None
    assert rows[0]["error"] == "ValueError"
    evidence = derive_zendure_mode_capability_evidence(
        {"state": "Snel opladen", "attributes": {"options": ["Snel opladen"]}},
        captured_at=NOW, source_entity_id="input_select.mode",
        capability_id="battery", execution_scope_id="home",
    )
    observe_storage_status(read=lambda: evidence, publish=rows.append,
                           source_entity_id="input_select.mode")
    assert rows[1]["availability"] == "available"
    assert rows[1]["active_mode"] == "Snel opladen"


def test_newer_pipeline_observation_is_not_overwritten_by_older_poll():
    store = WebViewStore()
    store.publish_storage_status(observation("Nul op de meter"))
    view = old_view()
    view["zendure_now"].update(active_mode="Standby",
                               observed_at=(NOW+timedelta(seconds=5)).isoformat())
    store.publish(view)
    latest = json.loads(store.latest_json())
    assert latest["zendure_now"]["active_mode"] == "Standby"
    assert latest["zendure_now"]["observed_at"] == (NOW+timedelta(seconds=5)).isoformat()
