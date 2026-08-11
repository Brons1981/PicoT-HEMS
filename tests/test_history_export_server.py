from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

from picot.addon.history_export_server import make_handler
from picot.addon.history_store import HistoryStore


def _serve(store: HistoryStore) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_history_export_page_is_available(tmp_path):
    store = HistoryStore(tmp_path / "history.jsonl")
    server = _serve(store)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert "Download historische data" in body
    finally:
        server.shutdown()
        server.server_close()


def test_history_export_download_filters_selected_range(tmp_path):
    store = HistoryStore(tmp_path / "history.jsonl")
    store.append(
        {
            "event": "picot_goodwe_snapshot",
            "observed_at": datetime(2026, 8, 10, 21, 0, tzinfo=timezone.utc).isoformat(),
            "marker": "inside",
        }
    )
    store.append(
        {
            "event": "picot_goodwe_snapshot",
            "observed_at": datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc).isoformat(),
            "marker": "outside",
        }
    )
    server = _serve(store)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request(
            "GET",
            "/download?from=2026-08-10T20%3A00%3A00%2B00%3A00"
            "&to=2026-08-11T06%3A00%3A00%2B00%3A00",
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert '"marker":"inside"' in body
        assert '"marker":"outside"' not in body
        disposition = response.getheader("Content-Disposition")
        assert disposition is not None
        assert disposition.startswith("attachment;")
    finally:
        server.shutdown()
        server.server_close()
