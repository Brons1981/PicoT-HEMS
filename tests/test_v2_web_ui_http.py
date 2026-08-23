import json
from io import BytesIO
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

import pytest

from picot.v2.web_ui import WebViewStore, create_web_server


def test_read_only_web_server_exposes_latest_view_and_rejects_writes() -> None:
    store = WebViewStore()
    server = create_web_server(
        store,
        host="127.0.0.1",
        port=0,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/view"

    try:
        with pytest.raises(HTTPError) as waiting:
            urlopen(url, timeout=2)

        assert waiting.value.code == 503
        assert waiting.value.headers.get_content_type() == "application/json"
        assert json.loads(waiting.value.read()) == {
            "status": "waiting_for_first_run"
        }
        waiting.value.close()

        store.publish(
            {
                "schema_version": 1,
                "observer_only": True,
                "run_id": "run-live-1",
                "pipeline": [],
            }
        )

        with urlopen(url, timeout=2) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "application/json"
            assert response.headers["Cache-Control"] == "no-store"
            assert json.loads(response.read()) == {
                "schema_version": 1,
                "observer_only": True,
                "run_id": "run-live-1",
                "pipeline": [],
            }

        for method in ("POST", "PUT", "PATCH", "DELETE"):
            request = Request(
                url,
                data=b"{}",
                method=method,
            )
            with pytest.raises(HTTPError) as rejected:
                urlopen(request, timeout=2)

            assert rejected.value.code == 405
            assert rejected.value.headers["Allow"] == "GET"
            rejected.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert not thread.is_alive()


def test_web_server_exposes_auto_refreshing_read_only_dashboard() -> None:
    store = WebViewStore()
    server = create_web_server(
        store,
        host="127.0.0.1",
        port=0,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"

    try:
        with urlopen(url, timeout=2) as response:
            html = response.read().decode("utf-8")

            assert response.status == 200
            assert response.headers.get_content_type() == "text/html"
            assert response.headers.get_content_charset() == "utf-8"
            assert response.headers["Cache-Control"] == "no-store"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert "<title>PicoT v2 — Canonical Pipeline</title>" in html
    assert 'data-observer-only="true"' in html
    assert 'id="sources"' in html
    assert 'aria-label="Brongegevens"' in html
    assert 'id="pipeline"' in html
    assert 'id="pv-energy-timeline"' in html
    assert "renderSources" in html
    assert '"p1": "P1 netmeting"' in html
    assert '"pv": "Zonnepanelen"' in html
    assert '"zendure": "Zendure batterij"' in html
    assert '"solcast": "Solcast voorspelling"' in html
    assert '"nordpool": "Nord Pool prijzen"' in html
    assert "Technische details" in html
    assert "compactReference" in html
    assert 'fetch("api/view"' in html
    assert "watchViewUpdates" in html
    assert "api/view/updates?revision=" in html
    assert "setInterval(loadView, 5000)" not in html
    assert "setInterval(loadView, 60000)" in html
    assert 'data-tab="overview"' in html
    assert 'data-tab="planning"' in html
    assert 'data-tab="history"' in html
    assert 'data-tab="strategy"' in html
    assert 'data-tab="technical"' in html
    assert 'id="planning-incident-history"' in html
    assert 'href="downloads/planning-incidents.jsonl"' in html
    assert 'href="downloads/picot-diagnostics.zip"' in html
    assert "formatMeasurement" in html
    assert 'formatMeasurement(source.raw_state, source.raw_unit)' in html


def test_web_server_exposes_incident_overview_and_downloads(tmp_path) -> None:
    incident = tmp_path / "picot_v2_planning_incident_history.jsonl"
    provenance = tmp_path / "picot_v2_storage_mode_provenance.json"
    incident.write_text(
        '{"event":"fallback_started","poll":{"run_id":"run-1"}}\n',
        encoding="utf-8",
    )
    provenance.write_text("{}", encoding="utf-8")
    store = WebViewStore()
    store.set_diagnostic_paths(
        (incident, provenance),
        incident_history_path=incident,
    )
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    try:
        with urlopen(f"{base}/api/diagnostics/incidents", timeout=2) as response:
            overview = json.loads(response.read())
        assert overview[0]["event"] == "fallback_started"

        with urlopen(
            f"{base}/downloads/planning-incidents.jsonl", timeout=2
        ) as response:
            assert response.headers.get_content_type() == "application/x-ndjson"
            assert "attachment" in response.headers["Content-Disposition"]
            assert response.read() == incident.read_bytes()

        with urlopen(f"{base}/downloads/picot-diagnostics.zip", timeout=2) as response:
            payload = response.read()
            assert response.headers.get_content_type() == "application/zip"
        with ZipFile(BytesIO(payload)) as archive:
            assert archive.namelist() == [incident.name, provenance.name]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_realtime_update_endpoint_returns_published_revision_and_view() -> None:
    store = WebViewStore()
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever)
    thread.start()
    store.publish(
        {
            "schema_version": 1,
            "run_id": "run-realtime-1",
            "pipeline": [],
        }
    )
    url = (
        f"http://127.0.0.1:{server.server_port}"
        "/api/view/updates?revision=0"
    )

    try:
        with urlopen(url, timeout=2) as response:
            payload = json.loads(response.read())

        assert response.status == 200
        assert response.headers.get_content_type() == "application/json"
        assert payload == {
            "revision": 1,
            "view": {
                "schema_version": 1,
                "run_id": "run-realtime-1",
                "pipeline": [],
            },
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert not thread.is_alive()


def test_dashboard_accepts_only_explicit_passive_stress_marker() -> None:
    captured = []
    store = WebViewStore()
    store.set_planner_stress_marker(
        lambda marker_id, note: captured.append((marker_id, note))
        or {"status": "recorded", "observer_only": True}
    )
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever)
    thread.start()
    request = Request(
        f"http://127.0.0.1:{server.server_port}/api/planner-comparison/stress",
        data=json.dumps(
            {"marker_id": "stress-1", "note": "handmatig"}
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read())
        assert payload == {"status": "recorded", "observer_only": True}
        assert captured == [("stress-1", "handmatig")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
