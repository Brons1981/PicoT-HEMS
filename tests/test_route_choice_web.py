"""The retired route-choice endpoint rejects old dashboard requests."""

import json
from contextlib import contextmanager
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from picot.v2.web_ui import WebViewStore, create_web_server


@contextmanager
def server_for(store):
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def post(base, payload):
    request = Request(
        base + "/api/route-choice",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_retired_route_choice_endpoint_rejects_old_dashboard_requests():
    with server_for(WebViewStore()) as base:
        assert post(base, {"token": "old-offer", "action": "pv"}) == (
            405, {"status": "method_not_allowed"},
        )
