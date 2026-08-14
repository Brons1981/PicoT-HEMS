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
