"""Pure read-only data projection for the PicoT v2 web UI."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.projection import Projection


class WebViewStore:
    """Thread-safe in-memory store for the latest serialized web view."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._latest_json: str | None = None

    def publish(self, view: dict[str, object]) -> None:
        """Serialize completely before atomically replacing the snapshot."""
        serialized = json.dumps(view, separators=(",", ":"))
        with self._lock:
            self._latest_json = serialized

    def latest_json(self) -> str | None:
        """Return the latest immutable JSON snapshot, when available."""
        with self._lock:
            return self._latest_json


def create_web_server(
    store: WebViewStore,
    *,
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    """Create, but do not start, the read-only observer HTTP server."""

    class Handler(BaseHTTPRequestHandler):
        def _send_json(
            self,
            status: HTTPStatus,
            body: str,
            *,
            allow_get: bool = False,
        ) -> None:
            encoded = body.encode("utf-8")
            self.send_response(int(status))
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            if allow_get:
                self.send_header("Allow", "GET")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if urlsplit(self.path).path != "/api/view":
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    '{"status":"not_found"}',
                )
                return

            latest = store.latest_json()
            if latest is None:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    '{"status":"waiting_for_first_run"}',
                )
                return

            self._send_json(HTTPStatus.OK, latest)

        def _reject_write(self) -> None:
            self._send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                '{"status":"method_not_allowed"}',
                allow_get=True,
            )

        def do_POST(self) -> None:
            self._reject_write()

        def do_PUT(self) -> None:
            self._reject_write()

        def do_PATCH(self) -> None:
            self._reject_write()

        def do_DELETE(self) -> None:
            self._reject_write()

        def log_message(
            self,
            format: str,
            *args: object,
        ) -> None:
            """Avoid access-log noise from frequent dashboard polling."""

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def build_web_view(
    run: CanonicalPipelineRun,
    projection: Projection,
) -> dict[str, object]:
    """Build one JSON-serializable observer view without side effects."""
    planning_input = run.planning_input
    timeline = planning_input.pv_energy_timeline
    intervals = (
        timeline.intervals
        if timeline is not None
        else ()
    )

    pipeline = [
        {
            "stage": stage,
            "entity_id": card.entity_id,
            "state": card.state,
            "attributes": dict(card.attributes),
        }
        for stage, card in enumerate(projection.cards, start=1)
    ]
    pv_energy_timeline: dict[str, object] = {
        "available": timeline is not None,
        "timeline_id": (
            timeline.timeline_id
            if timeline is not None
            else None
        ),
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "interval_count": len(intervals),
        "total_wh": sum(
            interval.pv_energy_wh
            for interval in intervals
        ),
        "starts_at": (
            intervals[0].starts_at.isoformat()
            if intervals
            else None
        ),
        "ends_at": (
            intervals[-1].ends_at.isoformat()
            if intervals
            else None
        ),
        "intervals": [
            {
                "interval_id": interval.interval_id,
                "starts_at": interval.starts_at.isoformat(),
                "ends_at": interval.ends_at.isoformat(),
                "pv_energy_wh": interval.pv_energy_wh,
                "evidence_type": interval.evidence_type,
                "confidence": interval.confidence,
                "actual_evidence_ids": list(
                    interval.actual_evidence_ids
                ),
                "forecast_evidence_ids": list(
                    interval.forecast_evidence_ids
                ),
                "conversion_method_version": (
                    interval.conversion_method_version
                ),
            }
            for interval in intervals
        ],
    }

    return {
        "schema_version": 1,
        "observer_only": True,
        "picot_version": planning_input.picot_version,
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "captured_at": planning_input.captured_at.isoformat(),
        "pipeline": pipeline,
        "pv_energy_timeline": pv_energy_timeline,
    }
