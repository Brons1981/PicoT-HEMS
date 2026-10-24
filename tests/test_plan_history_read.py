"""History is bounded, survives reset/restart, and cannot alter committed plans."""
import json
from datetime import UTC, datetime, timedelta

from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def plan(name, at):
    return {"plan_id": name, "created_at": at.isoformat(), "execution_scope_id": "battery",
            "winning_energy_path_id": "path-" + name, "segments": [{
                "starts_at": "2026-10-25T02:15:00+02:00",
                "ends_at": "2026-10-25T02:15:00+01:00", "primitive": "standby",
                "purpose": "bridge:tomorrow", "requested_power_w": None,
                "evidence_ids": ["private-heavy-evidence"],
            }]}


def test_history_keeps_pre_reset_plan_and_is_detached_read_only(tmp_path):
    at = datetime(2026, 10, 24, 19, tzinfo=UTC)
    old, new = plan("old", at), plan("new", at + timedelta(minutes=2))
    path = tmp_path / "plans.json"
    payload = {"schema_version": 1, "commitments": {},
               "execution_plans": {"old": old, "new": new},
               "active_execution_plan_ids": {"battery": "new"},
               "daily_main_history": {"old": {"plan": old, "assignment": {
                   "route_plan_id": "old", "revision_reason": "projected_reserve_shortfall"}}},
               "daily_assignments": {"tomorrow": {"route_plan_id": "new",
                   "revision_reason": "initial_main_route"}},
               "route_choices": {"secret": "not part of history"}}
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    store = ActivePlanCommitmentStore(path)
    result = store.load_plan_history()
    assert result["status"] == "available"
    assert [p["plan_id"] for p in result["plans"]] == ["new", "old"]
    assert [p["active"] for p in result["plans"]] == [True, False]
    assert result["plans"][1]["revision_reason"] == "projected_reserve_shortfall"
    segment = result["plans"][1]["segments"][0]
    assert segment["starts_at"].endswith("+02:00")
    assert segment["ends_at"].endswith("+01:00")
    assert "evidence_ids" not in segment
    assert "secret" not in json.dumps(result)
    result["plans"][0]["segments"][0]["primitive"] = "charge_at_power"
    assert store.load_plan_history()["plans"][0]["segments"][0]["primitive"] == "standby"
    assert path.read_bytes() == before
    assert ActivePlanCommitmentStore(path).load_plan_history() == store.load_plan_history()


def test_history_limits_rows_and_orders_instants_not_offset_strings(tmp_path):
    at = datetime(2026, 10, 24, 19, tzinfo=UTC)
    plans = {str(n): plan(str(n), at + timedelta(minutes=n)) for n in range(25)}
    plans["24"]["created_at"] = "2026-10-24T21:24:00+02:00"
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({"schema_version": 1, "commitments": {},
                               "execution_plans": plans,
                               "active_execution_plan_ids": {"battery": "24"}}))
    result = ActivePlanCommitmentStore(path).load_plan_history()
    assert len(result["plans"]) == 20
    assert [p["plan_id"] for p in result["plans"]] == [str(n) for n in range(24, 4, -1)]
    assert result["truncated"] is True


def test_missing_history_is_empty_and_does_not_create_file(tmp_path):
    path = tmp_path / "missing.json"
    assert ActivePlanCommitmentStore(path).load_plan_history()["plans"] == []
    assert not path.exists()


def test_history_reader_does_not_hold_publication_lock():
    from picot.v2.web_ui import WebViewStore
    store = WebViewStore()
    def read():
        store.publish({"run_id": "new", "pipeline": []})
        return {"status": "available", "plans": []}
    store.set_plan_history_reader(read)
    assert store.plan_history()["status"] == "available"
    assert json.loads(store.latest_json())["run_id"] == "new"


def test_history_endpoint_is_read_only_uncached_and_isolates_failure(monkeypatch):
    from io import BytesIO

    import picot.v2.web_ui as ui

    store = ui.WebViewStore()
    store.set_plan_history_reader(lambda: {"status": "available", "plans": [{"plan_id": "old"}]})
    monkeypatch.setattr(ui, "ThreadingHTTPServer", lambda address, handler: handler)
    handler = ui.create_web_server(store, host="127.0.0.1", port=0)

    class Connection:
        def __init__(self, method):
            self.request = BytesIO(f"{method} /api/plan-history HTTP/1.0\r\n\r\n".encode())
            self.response = bytearray()

        def makefile(self, *args):
            return self.request

        def sendall(self, data):
            self.response.extend(data)

    connection = Connection("GET")
    handler(connection, ("127.0.0.1", 12345), object())
    headers, body = bytes(connection.response).split(b"\r\n\r\n", 1)
    assert b"200 OK" in headers and b"Cache-Control: no-store" in headers
    assert json.loads(body)["plans"][0]["plan_id"] == "old"
    connection = Connection("POST")
    handler(connection, ("127.0.0.1", 12345), object())
    assert b"405 Method Not Allowed" in connection.response
    def failed():
        raise ValueError("bad source")
    store.set_plan_history_reader(failed)
    assert store.plan_history() == {"status": "unavailable", "plans": []}


def test_invalid_historical_record_does_not_hide_healthy_active_plan(tmp_path):
    at = datetime(2026, 10, 24, 19, tzinfo=UTC)
    current, broken = plan("current", at), plan("broken", at - timedelta(minutes=1))
    broken["segments"] = [None]
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({"schema_version": 1, "commitments": {},
        "execution_plans": {"current": current, "broken": broken},
        "active_execution_plan_ids": {"battery": "current"}}))
    result = ActivePlanCommitmentStore(path).load_plan_history()
    assert [p["plan_id"] for p in result["plans"]] == ["current"]
    assert result["omitted_invalid_records"] == 1
