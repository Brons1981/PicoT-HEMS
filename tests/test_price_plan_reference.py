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


def market_payload(*, retained=False):
    first = record()
    first["plan"]["segments"][0].update(
        primitive="balance_discharge_only", requested_power_w=None, charge_source_policy=None
    )
    trade = {"segment_id": "trade-first", "purpose": "market-day", "main_assignment_id": None,
             "starts_at": "2026-09-11T17:45:00+00:00", "ends_at": "2026-09-11T18:45:00+00:00",
             "primitive": "discharge_at_power", "requested_power_w": 2400,
             "charge_source_policy": None}
    shared = {"plan_id": "shared-first", "execution_scope_id": "battery",
              "segments": [trade]}
    binding = {"assignment_id": "market-day", "execution_scope_id": "battery",
               "plan_id": "shared-first", "segment_ids": ["trade-first"],
               "original_plan_id": None, "original_segment_ids": []}
    if retained:
        binding.update(plan_id="shared-later", segment_ids=["trade-later"],
                       original_plan_id="shared-first", original_segment_ids=["trade-first"])
    return {"daily_main_history": {"first": first},
            "market_daily_assignments": {"market-day": {
                "delivery_date": "2026-09-11", "execution_scope_id": "battery"}},
            "market_plan_bindings": {"market-day": binding},
            "execution_plans": {"shared-first": shared}}


def test_original_reference_includes_market_and_replaces_household_support(tmp_path):
    path = tmp_path / "commitment.json"
    payload = market_payload(retained=True)
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    reference = PricePlanReference(path).read()
    segments = reference["plans"][0]["segments"]
    assert [s["primitive"] for s in segments] == [
        "balance_discharge_only", "discharge_at_power", "balance_discharge_only"
    ]
    assert segments[1]["starts_at"] == "2026-09-11T17:45:00+00:00"
    assert segments[1]["ends_at"] == "2026-09-11T18:45:00+00:00"
    assert reference["plans"][0]["market_plan_ids"] == ["shared-first"]
    assert PricePlanReference(path).read() == reference
    assert path.read_bytes() == before


def test_initial_market_binding_is_already_part_of_original_reference(tmp_path):
    path = tmp_path / "commitment.json"
    path.write_text(json.dumps(market_payload()))
    segments = PricePlanReference(path).read()["plans"][0]["segments"]
    assert segments[1]["primitive"] == "discharge_at_power"


def test_missing_market_origin_is_unknown_not_a_false_optimisation(tmp_path):
    path = tmp_path / "commitment.json"
    payload = market_payload(retained=True)
    payload["execution_plans"] = {}
    path.write_text(json.dumps(payload))
    assert PricePlanReference(path).read() == {"status": "unavailable", "plans": []}


def test_chart_marks_later_changes_but_not_original_trade(tmp_path):
    import subprocess

    from picot.v2.web_ui import DASHBOARD_HTML

    path = tmp_path / "commitment.json"
    payload = market_payload(retained=True)
    # The first shared market plan can also contain a changed charging route.
    # Only its bound trading instructions belong in the original reference.
    payload["execution_plans"]["shared-first"]["segments"].append({
        "segment_id": "later-charge", "starts_at": "2026-09-11T13:00:00Z",
        "ends_at": "2026-09-11T14:00:00Z", "primitive": "charge_at_power",
        "requested_power_w": 2400,
    })
    path.write_text(json.dumps(payload))
    view = {"original_price_plan": PricePlanReference(path).read()}
    trade = payload["execution_plans"]["shared-first"]["segments"][0]
    original = {"execution_scope_id": "battery", "segments": [trade]}
    altered = {"execution_scope_id": "battery", "segments": [
        {**trade, "ends_at": "2026-09-11T18:00:00Z"},
        {**trade, "starts_at": "2026-09-11T18:00:00Z", "primitive": "balance_discharge_only",
         "requested_power_w": None},
        payload["execution_plans"]["shared-first"]["segments"][1],
    ]}
    start = DASHBOARD_HTML.index("    function primitivePlanKind(")
    end = DASHBOARD_HTML.index("    function movePanelContent(", start)
    script = DASHBOARD_HTML[start:end] + "\nconst view=" + json.dumps(view) + ";\n"
    script += "view.planning_status={execution_plans:[" + json.dumps(original) + "]};\n"
    script += "const initial=selectedExecutionPlanWindows(view);\n"
    script += "view.planning_status={execution_plans:[" + json.dumps(altered) + "]};\n"
    script += "console.log(JSON.stringify([initial,selectedExecutionPlanWindows(view)]));"
    initial, changed = json.loads(subprocess.run(
        ["node"], input=script, text=True, capture_output=True, check=True
    ).stdout)
    assert [w["optimized"] for w in initial] == [False]
    assert [w["optimized"] for w in changed] == [False, True, True]
    assert "aangepast" not in initial[0]["label"]
    assert changed[1]["starts_at"] == "2026-09-11T18:00:00.000Z"


def test_reference_reads_real_shared_plan_store(tmp_path, monkeypatch):
    from test_market_plan_binding import prepared

    store, _, original, args = prepared(tmp_path, monkeypatch)
    store.bind_market_plan(**args)
    path = tmp_path / "plans.json"
    before = path.read_bytes()
    reference = PricePlanReference(path).read()
    assert reference["status"] == "available"
    day = next(p for p in reference["plans"] if args["plan"].plan_id in p["market_plan_ids"])
    original_trade = next(s for s in args["plan"].segments
                          if s.segment_id in args["binding"].segment_ids)
    trade = next(s for s in day["segments"] if s["primitive"] == "discharge_at_power")
    assert trade["starts_at"] == original_trade.starts_at.isoformat()
    assert trade["ends_at"] == original_trade.ends_at.isoformat()
    assert day["plan_id"] == original.plan_id
    assert PricePlanReference(path).read() == reference
    assert path.read_bytes() == before
