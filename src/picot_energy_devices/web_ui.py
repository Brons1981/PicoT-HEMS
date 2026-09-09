"""Small non-technical registry UI for the independent producer."""

# ruff: noqa: E501 -- embedded HTML and JavaScript remain readable as browser source.

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

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

      <label class="wide"><button type="submit">Apparaat toevoegen</button></label>
    </form>
    <p id="message" class="muted" aria-live="polite"></p>
  </section>
  <section class="panel">
    <div class="row"><h2>Apparaatkaarten</h2><span id="metrics" class="muted"></span></div>
    <div id="cards" class="cards">Nog geen apparaten toegevoegd.</div>
  </section>
  <dialog id="detail"><button onclick="document.getElementById('detail').close()">Sluiten</button><h2 id="detail-title"></h2><p id="detail-summary"></p><canvas id="shape" width="800" height="240" style="max-width:100%"></canvas><p>Vermogen (W) over de opname. Onderbrekingen tonen ontbrekende metingen.</p><div style="max-height:300px;overflow:auto"><table><thead><tr><th>Tijd</th><th>Vermogen (W)</th><th>Energiemeter (Wh)</th><th>Meetstatus</th></tr></thead><tbody id="sample-rows"></tbody></table></div></dialog>
  <script>
    const el = (id) => document.getElementById(id);
    const number = (value, suffix) => value !== null && value !== undefined && Number.isFinite(Number(value))
      ? `${Number(value).toLocaleString("nl-NL", {maximumFractionDigits: 1})} ${suffix}` : "Nog leren";
    async function load() {
      const response = await fetch("api/view", {cache:"no-store"});
      const view = await response.json();
      const cards = el("cards"); cards.replaceChildren();
      for (const card of view.catalog.cards ?? []) {
        const article = document.createElement("article"); article.className = "card";
        const title = document.createElement("h3"); title.textContent = card.name;
        const state = document.createElement("p"); state.className = "muted";
        state.textContent = card.recording ? "Opname loopt — inclusief rustige fases" : "Klaar voor handmatig inleren";
        const facts = document.createElement("p");
        facts.textContent = `${number(card.expected_power_w,"W")} · ${number(card.expected_energy_wh,"Wh")} · ${card.completed_session_count} sessies`;
        const source = document.createElement("p"); source.className = "muted"; source.textContent = card.power_entity_id;
        const remove = document.createElement("button"); remove.className = "danger"; remove.textContent = "Niet meer volgen";
        remove.addEventListener("click", () => change({action:"remove",device_id:card.device_id}).catch(error=>{el("message").textContent=error.message;}));
        article.append(title,state,facts,source);
        const button = (label, action) => { const b=document.createElement("button"); b.textContent=label; b.onclick=async()=>{try {await action();} catch(error) {el("message").textContent=error.message;}}; return b; };
        article.append(button(card.recording ? "Programma klaar" : "Start inleren", async()=>{
          if(card.recording) { await change({action:"finish",device_id:card.device_id}); }
          else {const name=prompt("Naam van het programma, bijvoorbeeld Eco 50°"); if(name?.trim()) await change({action:"start",device_id:card.device_id,name});}
        }));
        if(card.legacy_session_count) article.append(button(`${card.legacy_session_count} oude automatische sessies wissen`, async()=>{
          if(confirm("Alle oude automatische sessies van dit apparaat wissen? Handmatige opnames blijven bewaard.")) await change({action:"clear_legacy",device_id:card.device_id});
        }));
        const list=document.createElement("div");
        for(const rec of view.recordings[card.device_id] ?? []) {
          const block=document.createElement("section"); block.className="panel";
          const label=document.createElement("p"); label.textContent=`${rec.name} — ${new Date(rec.starts_at).toLocaleString("nl-NL")}`;
          const info=document.createElement("p"); info.textContent=rec.ends_at ? `${number(rec.duration_seconds/60,"min")} · ${number(rec.observed_energy_wh,"Wh gemeten (schatting)")} · ${rec.missing_seconds > 0 ? number(rec.missing_seconds,"s meetuitval — energie onvolledig") : "Geen meetgaten"}` : "Opname loopt";
          block.append(label,info,button("Bekijken",()=>showRecording(rec.recording_id)),button("Naam wijzigen",async()=>{const name=prompt("Programmanaam",rec.name);if(name?.trim())await change({action:"rename",recording_id:rec.recording_id,name});}),button("Verwijderen",async()=>{if(confirm("Deze opname en het bijbehorende vermogensverloop verwijderen?"))await change({action:"delete_recording",recording_id:rec.recording_id});}));
          list.append(block);
        }
        article.append(list,remove); cards.append(article);
      }
      if (!(view.catalog.cards ?? []).length) cards.textContent = "Nog geen apparaten toegevoegd.";
      el("metrics").textContent = `${view.catalog.cards?.length ?? 0} kaarten · ${(view.database_size_bytes/1024).toLocaleString("nl-NL",{maximumFractionDigits:0})} kB`;
    }
    async function showRecording(id) {
      const response=await fetch(`api/recording?id=${id}`,{cache:"no-store"});
      const rec=await response.json(); if(!response.ok)throw new Error(rec.error);
      el("detail-title").textContent=rec.name;
      el("detail-summary").textContent=rec.ends_at ? `${number(rec.duration_seconds/60,"min")} · ${number(rec.observed_energy_wh,"Wh gemeten (schatting)")} · ${number(rec.missing_seconds,"s meetuitval")}` : "Opname loopt; sluit dit venster en open opnieuw voor de nieuwste metingen.";
      const body=el("sample-rows");body.replaceChildren();
      for(const sample of rec.samples){const tr=document.createElement("tr");for(const value of [new Date(sample.observed_at).toLocaleTimeString("nl-NL"),sample.power_w ?? "—",sample.energy_meter_wh ?? "—",sample.power_w===null ? "Niet beschikbaar" : sample.error==="start_boundary_held_last_reading" ? "Startwaarde uit laatste meting" : "Gemeten"]){const td=document.createElement("td");td.textContent=String(value);tr.append(td);}body.append(tr);}
      const c=el("shape"),ctx=c.getContext("2d");ctx.clearRect(0,0,c.width,c.height);
      const start=Date.parse(rec.starts_at),end=Date.parse(rec.ends_at ?? rec.samples.at(-1)?.observed_at ?? rec.starts_at),span=Math.max(1,end-start);
      const peak=rec.samples.reduce((max,s)=>Math.max(max,s.power_w ?? 0),1);
      ctx.strokeStyle="#7bbaeb";ctx.fillStyle="#9eb0c3";ctx.fillText(`${peak.toFixed(0)} W`,2,12);ctx.fillText("0 W",2,230);ctx.beginPath();
      for(let i=0;i<rec.samples.length;i++){const a=rec.samples[i],b=rec.samples[i+1];const t=Date.parse(a.observed_at),next=b?Date.parse(b.observed_at):end;if(a.power_w===null || next-t>rec.maximum_sample_gap_seconds*1000)continue;const x=45+(t-start)/span*745,y=220-a.power_w/peak*195;ctx.moveTo(x,y);ctx.lineTo(45+(next-start)/span*745,y);if(b?.power_w!==null && b?.power_w!==undefined)ctx.lineTo(45+(next-start)/span*745,220-b.power_w/peak*195);}
      ctx.stroke();el("detail").showModal();
    }
    async function change(payload) {
      const response = await fetch("api/devices", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      if (!response.ok) { const body=await response.json(); throw new Error(body.error ?? `HTTP ${response.status}`); }
      await load();
    }
    el("device-form").addEventListener("submit", async (event) => {
      event.preventDefault(); el("message").textContent = "Opslaan…";
      try {
        await change({action:"add",name:el("name").value,power_entity_id:el("power").value,energy_entity_id:el("energy").value});
        el("message").textContent = "Apparaat toegevoegd. De eerste kaart is direct beschikbaar.";
        el("device-form").reset();
      } catch (error) { el("message").textContent = `Opslaan mislukt: ${error.message}`; }
    });
    const refresh=()=>load().catch(error=>{el("message").textContent=`Ophalen mislukt: ${error.message}`;}); refresh(); setInterval(refresh, 10000);
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
                        "recordings": {d.device_id: store.recording_list(d.device_id)
                                       for d in store.devices()},
                    },
                )
                return
            if path == "/api/recording":
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    self._json(HTTPStatus.OK, store.recording_detail(int(query.get("id", [""])[0])))
                except ValueError as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
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
                elif action == "start":
                    store.start_recording(str(payload.get("device_id", "")), str(payload.get("name", "")))
                    result = {"status": "recording"}
                elif action == "finish":
                    store.finish_recording(str(payload.get("device_id", "")))
                    result = {"status": "finished"}
                elif action == "rename":
                    store.rename_recording(int(payload.get("recording_id", 0)), str(payload.get("name", "")))
                    result = {"status": "renamed"}
                elif action == "delete_recording":
                    store.delete_recording(int(payload.get("recording_id", 0)))
                    result = {"status": "deleted"}
                elif action == "clear_legacy":
                    store.clear_legacy_sessions(str(payload.get("device_id", "")))
                    result = {"status": "cleared"}
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
