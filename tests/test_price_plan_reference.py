import json

from picot.v2.price_plan_reference import PricePlanReference


def record(revision=1):
    return {
        "assignment": {"revision": revision, "revision_reason": "initial_main_route",
                       "route_plan_id": "first", "execution_scope_id": "battery",
                       "revision_evidence_id": "eval-first", "delivery_date": "2026-09-11",
                       "timezone": "Europe/Amsterdam"},
        "plan": {"plan_id": "first", "execution_scope_id": "battery",
                 "evaluation_id": "eval-first", "segments": [{
                     "starts_at": "2026-09-10T20:00:00+00:00",
                     "ends_at": "2026-09-12T02:00:00+00:00",
                     "primitive": "charge_at_power", "requested_power_w": 2400,
                     "charge_source_policy": "grid_allowed"}]},
    }


def test_original_survives_revisions_and_restart_without_writes(tmp_path):
    path = tmp_path / "commitment.json"
    old, current = record(), record(4)
    current["plan"]["plan_id"] = "new"
    payload = {"daily_main_history": {"first": old},
               "daily_assignments": {"day": current["assignment"]},
               "daily_execution_plans": {"day": current["plan"]}}
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    view = PricePlanReference(path).read()
    assert view["status"] == "available"
    assert [p["plan_id"] for p in view["plans"]] == ["first"]
    segment = view["plans"][0]["segments"][0]
    assert segment["starts_at"] == "2026-09-11T00:00:00+02:00"
    assert segment["ends_at"] == "2026-09-12T00:00:00+02:00"
    assert PricePlanReference(path).read() == view
    assert path.read_bytes() == before


def test_current_first_revision_and_unavailable_reference(tmp_path):
    path = tmp_path / "commitment.json"
    reader = PricePlanReference(path)
    assert reader.read()["status"] == "unavailable"
    first = record()
    path.write_text(json.dumps({"daily_assignments": {"day": first["assignment"]},
                               "daily_execution_plans": {"day": first["plan"]}}))
    assert reader.read()["plans"][0]["plan_id"] == "first"
    assert reader.read()["status"] == "available"
    first["plan"]["evaluation_id"] = "wrong"
    path.write_text(json.dumps({"daily_main_history": {"first": first}}))
    assert reader.read() == {"status": "unavailable", "plans": []}
    path.write_text("invalid")
    assert reader.read()["status"] == "unavailable"


def test_web_projection_keeps_current_plan_and_soc_unchanged(tmp_path):
    from picot.v2.web_ui import WebViewStore

    path = tmp_path / "commitment.json"
    path.write_text(json.dumps({"daily_main_history": {"first": record()}}))
    status = {"execution_plans": [{"plan_id": "current", "segments": []}],
              "soc_timeline": [{"at": "2026-09-11T12:00:00Z", "soc_percent": 50}]}
    before = json.dumps(status)
    web = WebViewStore(price_reference=PricePlanReference(path))
    web.publish({"planning_status": status})
    view = json.loads(web.latest_json())
    assert view["original_price_plan"]["plans"][0]["plan_id"] == "first"
    assert view["planning_status"] == status
    assert json.dumps(status) == before
