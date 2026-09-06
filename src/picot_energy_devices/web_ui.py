"""Small non-technical registry UI for the independent producer."""

# ruff: noqa: E501 -- embedded HTML and JavaScript remain readable as browser source.

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from picot_energy_devices.store import EnergyDeviceStore

DASHBOARD_HTML = """<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>PicoT Energy Devices</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #0b1117; color: #e7eef6; }
    main { max-width: 1050px; margin: auto; padding: 24px; }
    h1 { margin-bottom: 4px; }
    .muted { color: #9eb0c3; }
    .panel, .card { background: #151e27; border: 1px solid #304050; border-radius: 12px; }
    .panel { padding: 18px; margin: 20px 0; }
    form { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
    label { display: grid; gap: 5px; }
    label.wide { grid-column: 1/-1; }
    input, button { font: inherit; padding: 10px; border-radius: 8px; }
    input { color: inherit; background: #0e151d; border: 1px solid #40546a; }
    button { color: #e7eef6; background: #123b55; border: 1px solid #2c7fb0; cursor: pointer; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap: 12px; }
    .card { padding: 14px; }
    .row { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .danger { background: #4d2020; border-color: #a64b4b; }
    @media(max-width:650px) { form { grid-template-columns: 1fr; } }
  </style>
</head>
<body><main>
  <h1>PicoT Energy Devices</h1>
  <p class="muted">Leert alleen het energieprofiel van jouw meetstekkers. Deze app bedient niets.</p>
  <section class="panel">
    <h2>Apparaat toevoegen</h2>
    <form id="device-form">
      <label>Naam<input id="name" required placeholder="Bijvoorbeeld droger"></label>
      <label>Vermogenssensor<input id="power" required placeholder="sensor.droger_vermogen"></label>
      <label>Energiemeter (optioneel)<input id="energy" placeholder="sensor.droger_energie"></label>
      <label>Actief vanaf<input id="threshold" type="number" min="0" step="1" value="20"> watt</label>
      <label class="wide"><button type="submit">Toevoegen en leren</button></label>
    </form>
    <p id="message" class="muted" aria-live="polite"></p>
  </section>
  <section class="panel">
    <div class="row"><h2>Apparaatkaarten</h2><span id="metrics" class="muted"></span></div>
    <div id="cards" class="cards">Nog geen apparaten toegevoegd.</div>
  </section>
  <script>
    const el = (id) => document.getElementById(id);
    const number = (value, suffix) => Number.isFinite(Number(value))
      ? `${Number(value).toLocaleString("nl-NL", {maximumFractionDigits: 1})} ${suffix}` : "Nog leren";
    async function load() {
      const response = await fetch("api/view", {cache:"no-store"});
      const view = await response.json();
      const cards = el("cards"); cards.replaceChildren();
      for (const card of view.catalog.cards ?? []) {
        const article = document.createElement("article"); article.className = "card";
        const title = document.createElement("h3"); title.textContent = card.name;
        const state = document.createElement("p"); state.className = "muted";
        state.textContent = card.active ? "Nu actief" : card.profile_status === "ready" ? "Profiel beschikbaar" : "Profiel wordt geleerd";
        const facts = document.createElement("p");
        facts.textContent = `${number(card.expected_power_w,"W")} · ${number(card.expected_energy_wh,"Wh")} · ${card.completed_session_count} sessies`;
        const source = document.createElement("p"); source.className = "muted"; source.textContent = card.power_entity_id;
        const remove = document.createElement("button"); remove.className = "danger"; remove.textContent = "Niet meer volgen";
        remove.addEventListener("click", () => change({action:"remove",device_id:card.device_id}));
        article.append(title,state,facts,source,remove); cards.append(article);
      }
      if (!(view.catalog.cards ?? []).length) cards.textContent = "Nog geen apparaten toegevoegd.";
      el("metrics").textContent = `${view.catalog.cards?.length ?? 0} kaarten · ${(view.database_size_bytes/1024).toLocaleString("nl-NL",{maximumFractionDigits:0})} kB`;
    }
    async function change(payload) {
      const response = await fetch("api/devices", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      if (!response.ok) { const body=await response.json(); throw new Error(body.error ?? `HTTP ${response.status}`); }
      await load();
    }
    el("device-form").addEventListener("submit", async (event) => {
      event.preventDefault(); el("message").textContent = "Opslaan…";
      try {
        await change({action:"add",name:el("name").value,power_entity_id:el("power").value,energy_entity_id:el("energy").value,active_threshold_w:Number(el("threshold").value)});
        el("message").textContent = "Apparaat toegevoegd. De eerste kaart is direct beschikbaar.";
        el("device-form").reset(); el("threshold").value = "20";
      } catch (error) { el("message").textContent = `Opslaan mislukt: ${error.message}`; }
    });
    load(); setInterval(load, 10000);
  </script>
</main></body></html>"""


def create_web_server(store: EnergyDeviceStore, *, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: HTTPStatus, payload: object) -> None:
            self._send(
                status,
                json.dumps(payload, separators=(",", ":")).encode(),
                "application/json; charset=utf-8",
            )

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/":
                self._send(HTTPStatus.OK, DASHBOARD_HTML.encode(), "text/html; charset=utf-8")
                return
            if path == "/api/view":
                self._json(
                    HTTPStatus.OK,
                    {
                        "catalog": store.catalog(),
                        "database_size_bytes": store.database_size_bytes(),
                    },
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if urlsplit(self.path).path != "/api/devices":
                self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"status": "method_not_allowed"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 8192:
                    raise ValueError("ongeldige invoer")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("invoer moet een object zijn")
                action = payload.get("action")
                if action == "add":
                    device = store.add_device(
                        name=str(payload.get("name", "")),
                        power_entity_id=str(payload.get("power_entity_id", "")),
                        energy_entity_id=str(payload.get("energy_entity_id") or "") or None,
                        active_threshold_w=float(payload.get("active_threshold_w", 20.0)),
                    )
                    result: object = {"status": "added", "device_id": device.device_id}
                elif action == "remove":
                    store.disable_device(str(payload.get("device_id", "")))
                    result = {"status": "removed"}
                else:
                    raise ValueError("onbekende actie")
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"status": "invalid", "error": str(error)})
                return
            self._json(HTTPStatus.OK, result)

        def log_message(self, format: str, *args: object) -> None:
            """Avoid noisy ingress access logs."""

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
