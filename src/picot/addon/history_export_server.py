"""Small Home Assistant add-on web UI for exporting PicoT history."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

from picot.addon.history_store import HistoryStore

DEFAULT_EXPORT_PORT = 8099


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _default_window() -> tuple[str, str]:
    now = datetime.now().astimezone()
    start = now - timedelta(hours=14)
    return start.strftime("%Y-%m-%dT%H:%M"), now.strftime("%Y-%m-%dT%H:%M")


def _page(start_value: str, end_value: str, *, error: str | None = None) -> bytes:
    message = ""
    if error:
        message = f'<p class="error">{escape(error)}</p>'
    html = f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PicoT historische data</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;background:#111;color:#eee}}
.card{{background:#1d1d1d;border-radius:12px;padding:24px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
label{{display:flex;flex-direction:column;gap:6px;font-weight:600}}
input,button{{font:inherit;padding:10px;border-radius:8px;border:1px solid #555}}
button{{margin-top:18px;cursor:pointer;font-weight:700}}
small{{color:#aaa}} .error{{color:#ff8a80}}
@media(max-width:600px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="card">
<h1>PicoT historische data</h1>
<p>Kies een periode. PicoT exporteert de persistente runtime-evidence uit <code>/data/picot_history.jsonl</code>.</p>
{message}
<form id="export-form" action="download" method="get">
<div class="grid">
<label>Van<input id="from-local" type="datetime-local" value="{escape(start_value)}" required></label>
<label>Tot<input id="to-local" type="datetime-local" value="{escape(end_value)}" required></label>
</div>
<input id="from" name="from" type="hidden">
<input id="to" name="to" type="hidden">
<button type="submit">Download historische data</button>
</form>
<p><small>Ruwe telemetry wordt 7 dagen bewaard. Price decisions en PV-deviation evaluator evidence 90 dagen.</small></p>
</div>
<script>
const form=document.getElementById('export-form');
form.addEventListener('submit',()=>{{
 document.getElementById('from').value=new Date(document.getElementById('from-local').value).toISOString();
 document.getElementById('to').value=new Date(document.getElementById('to-local').value).toISOString();
}});
</script>
</body></html>"""
    return html.encode("utf-8")


def make_handler(history: HistoryStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/", ""}:
                start, end = _default_window()
                payload = _page(start, end)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if parsed.path.rstrip("/") == "/download":
                params = parse_qs(parsed.query)
                try:
                    start = _parse_datetime(params["from"][0])
                    end = _parse_datetime(params["to"][0])
                    if end < start:
                        raise ValueError("'Tot' moet na 'Van' liggen.")
                except (KeyError, IndexError, ValueError) as exc:
                    start_value, end_value = _default_window()
                    payload = _page(start_value, end_value, error=str(exc))
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                records = list(history.iter_range(start, end))
                body = b"".join(
                    (json.dumps(record, separators=(",", ":"), default=str) + "\n").encode("utf-8")
                    for record in records
                )
                filename = (
                    "picot_history_"
                    f"{start.astimezone(timezone.utc):%Y%m%dT%H%MZ}_"
                    f"{end.astimezone(timezone.utc):%Y%m%dT%H%MZ}.jsonl"
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def start_history_export_server(
    history: HistoryStore,
    *,
    host: str = "0.0.0.0",
    port: int = DEFAULT_EXPORT_PORT,
) -> ThreadingHTTPServer:
    """Start the history export web UI in a daemon thread."""

    server = ThreadingHTTPServer((host, port), make_handler(history))
    thread = Thread(target=server.serve_forever, name="picot-history-export", daemon=True)
    thread.start()
    return server


def main() -> int:
    history = HistoryStore()
    server = ThreadingHTTPServer(("0.0.0.0", DEFAULT_EXPORT_PORT), make_handler(history))
    print(f"PicoT history export UI listening on port {DEFAULT_EXPORT_PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
