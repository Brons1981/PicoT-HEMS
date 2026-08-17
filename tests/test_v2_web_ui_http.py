import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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
    assert "formatMeasurement" in html
    assert 'formatMeasurement(source.raw_state, source.raw_unit)' in html


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
