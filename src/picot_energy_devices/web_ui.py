"""Small non-technical registry UI for the independent producer."""

# ruff: noqa: E501 -- embedded HTML and JavaScript remain readable as browser source.

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from picot_energy_devices.diagnostics import DiagnosticsRecorder
from picot_energy_devices.ev_sessions import EVSessionManager
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
    input, button, .download-button { font: inherit; padding: 10px; border-radius: 8px; }
    input { color: inherit; background: #0e151d; border: 1px solid #40546a; }
    button, .download-button { color: #e7eef6; background: #123b55; border: 1px solid #2c7fb0; cursor: pointer; }
    .download-button { display: inline-block; text-decoration: none; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap: 12px; }
    .card { padding: 14px; }
    .row { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .danger { background: #4d2020; border-color: #a64b4b; }
    @media(max-width:650px) { form { grid-template-columns: 1fr; } }
  </style>
</head>
<body><main>
  <h1>PicoT Energy Devices</h1>
  <p class="muted">Leert energieprofielen en voert door jou bevestigde EV-laadsessies uit.</p>
  <section class="panel">
    <h2>Diagnose</h2>
    <p>Download de laatste 48 uur meetgegevens en de bewaarde gebeurtenissen om EV-correctie en terugvallen te beoordelen.</p>
    <a class="download-button" href="api/diagnostics.zip" download>Diagnose downloaden</a>
  </section>
  <section class="panel" id="ev-panel" hidden>
    <h2>EV-laadtijdlijn</h2>
    <p id="ev-status"></p>
    <p>Sluit de auto aan en druk op Nu laden. Daarmee bevestig je dat de stekker in de auto zit. Energy Devices schakelt de laadplug in en controleert het laadvermogen.</p>
    <button id="ev-now" disabled>Nu laden</button>
    <details><summary>Goedkoop laden voor een eindtijd — laadadvies</summary>
      <p>HEMS vergelijkt aaneengesloten laadblokken met de bekende prijzen, zonverwachting en het batterijplan. Dit advies schakelt de laadplug nog niet in en reserveert de thuisbatterij voor haar bestaande plan. De laadbehoefte is energie aan de stekker, inclusief laadverlies.</p>
      <form id="ev-advice-form">
        <label>Gereed voor (lokale tijd)<input type="datetime-local" id="ev-ready-by" required></label>
        <label>Nog te laden (kWh)<input type="number" id="ev-required-kwh" min="0.01" max="88.32" step="0.01" required></label>
        <button id="ev-advice-submit" type="submit">Laadadvies aanvragen</button>
      </form>
      <button id="ev-advice-cancel" type="button">Aanvraag annuleren</button>
      <p id="ev-advice-status" aria-live="polite"></p>
      <p id="ev-advice-cost"></p>
      <ul id="ev-advice-slots"></ul>
    </details>
    <p id="ev-start-status" aria-live="polite"></p>
    <details><summary>Vast laadprofiel</summary>
      <p>Eenmalig instellen. De laadduur is een schatting en maximale looptijd, geen bewijs dat de accu vol is. Wijzigen geldt voor de volgende sessie.</p>
      <form id="ev-profile">
        <label>Laadvermogen (W)<input type="number" id="ev-profile-power" min="100" max="3680" required></label>
        <label>Laadduur (minuten)<input type="number" id="ev-profile-duration" min="1" max="1440" required></label>
        <button type="submit">Laadprofiel opslaan</button>
      </form>
      <p id="ev-profile-status"></p>
    </details>
    <details><summary>Bestaande sessie op een vaste starttijd plannen</summary>
    <p>Deze handmatige planning gebruikt een al herkende sessie. Test voor uitgesteld hervatten eerst of de auto na uit/aan hervat.</p>
    <button id="ev-verify">Hervatten getest en geslaagd</button>
    <form id="ev-plan">
      <label>Starttijd<input type="datetime-local" id="ev-start" required></label>
      <label>Vermogen (W)<input type="number" id="ev-power" min="100" max="3680" required></label>
      <label>Duur (minuten)<input type="number" id="ev-duration" min="1" max="1440" required></label>
      <button type="submit">Laadsessie bevestigen</button>
    </form>
    </details>
    <button id="ev-resume">Onderbroken sessie hervatten</button>
    <button id="ev-cancel">Sessie annuleren</button>
    <div id="ev-timeline"></div>
    <p id="ev-message" aria-live="polite"></p>
  </section>
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
      renderEV(view.ev);
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
    let evSession=null;
    let evBusy=false;
    function renderEV(ev) {
      el("ev-panel").hidden=!ev;
      if(!ev)return;
      renderChargingAdvice(ev);
      evSession=[...ev.sessions].reverse().find(s=>["recognized","planned","active","interrupted"].includes(s.state));
      const labels={recognized:"Herkend",planned:"Gepland",active:"Actief",interrupted:"Onderbroken",completed:"Voltooid",cancelled:"Geannuleerd"};
      el("ev-status").textContent=evSession ? `${labels[evSession.state]} · ${number(evSession.current_power_w,"W")} · ${number(evSession.delivered_energy_wh,"Wh geleverd")} · ${number(evSession.remaining_energy_wh,"Wh resterend")} · ${number((evSession.remaining_duration_seconds??0)/60,"min resterend (schatting)")}${evSession.error ? " · "+evSession.error : ""}` : `Geen open laadsessie · ${ev.recognition?.reason??"wachten op meting"} · ${number(ev.recognition?.power_w,"W")} · meetleeftijd ${number(ev.recognition?.measurement_age_seconds,"s")}`;
      el("ev-verify").disabled=ev.resume_verified;
      el("ev-now").disabled=evBusy || !!evSession || !ev.profile;
      el("ev-resume").disabled=evBusy || !evSession?.confirmed || !evSession?.manual_pause;
      el("ev-cancel").disabled=evBusy || !evSession;
      const startLabels={waiting_for_switch:"Wachten op inschakelen van de laadplug",waiting_for_charging:"Laadplug aan; wachten op laadvermogen",charging_not_started:"Laden niet gestart. Controleer stekker en auto; de sessie blijft beschikbaar.",measurement_unavailable:"Laadvermogen niet beschikbaar; laadstart niet bevestigd",charging:"Laden gemeten"};
      el("ev-start-status").textContent=evSession?.manual_pause ? "Handmatig onderbroken" : startLabels[evSession?.start_status]??"";
      el("ev-profile-status").textContent=ev.profile ? `${number(ev.profile.expected_power_w,"W")} / ${number(ev.profile.expected_duration_seconds/60,"min")}` : "Sla eerst je vaste laadvermogen en laadduur op.";
      if(ev.profile && !el("ev-profile-power").value)el("ev-profile-power").value=ev.profile.expected_power_w;
      if(ev.profile && !el("ev-profile-duration").value)el("ev-profile-duration").value=ev.profile.expected_duration_seconds/60;
      if(evSession && document.activeElement!==el("ev-power") && !el("ev-power").value)el("ev-power").value=Math.round(evSession.expected_power_w);
      if(evSession?.expected_duration_seconds && !el("ev-duration").value)el("ev-duration").value=Math.round(evSession.expected_duration_seconds/60);
      if(evSession?.planned_start && !el("ev-start").value){const d=new Date(evSession.planned_start);el("ev-start").value=new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
      const timeline=el("ev-timeline");timeline.replaceChildren();
      for(const s of [...ev.sessions].reverse()) {const p=document.createElement("p");p.textContent=`${s.planned_start ? new Date(s.planned_start).toLocaleString("nl-NL") : new Date(s.recognized_at).toLocaleString("nl-NL")} — ${labels[s.state]} · ${number(s.expected_power_w,"W")} · ${number((s.expected_duration_seconds??0)/60,"min")}`;timeline.append(p);}
    }
    function renderChargingAdvice(ev) {
      const request=ev.charging_request, advice=ev.charging_advice;
      const pending=request?.state==="requested";
      el("ev-advice-cancel").disabled=evBusy || !pending;
      el("ev-advice-submit").disabled=evBusy || !ev.profile || ev.sessions.some(s=>["recognized","planned","active","interrupted"].includes(s.state));
      if(!el("ev-required-kwh").value && (pending || ev.profile))el("ev-required-kwh").value=(pending ? request.remaining_energy_wh/1000 : ev.profile.expected_power_w*ev.profile.expected_duration_seconds/3600000).toFixed(2);
      if(pending && !el("ev-ready-by").value){const d=new Date(request.ready_by);el("ev-ready-by").value=new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
      const labels={ready:"Laadadvies beschikbaar",provisional:"Voorlopig advies: nog niet alle prijzen of plangegevens zijn bekend",blocked:"Nog geen bruikbaar laadadvies",infeasible:"Laadbehoefte niet haalbaar voor deze eindtijd"};
      const reasons={deadline_capacity_insufficient:"Er is te weinig tijd voor de gevraagde energie",known_horizon_has_insufficient_capacity:"Er zijn nog onvoldoende uren met bekende prijzen en plangegevens",retained_battery_plan_unavailable:"Wachten op een actueel batterijplan",retained_battery_plan_requires_repair:"HEMS moet eerst het batterijplan bijwerken",no_placement_preserves_battery_commitments:"Geen passend laadblok gevonden dat het batterijplan behoudt",existing_ev_demand_requires_reconciliation:"Er is al een laadsessie actief"};
      const fresh=advice && Date.now()-new Date(advice.generated_at).getTime()<=300000;
      el("ev-advice-status").textContent=!pending ? "Geen open adviesaanvraag" : !advice ? "Wachten op HEMS" : !fresh ? "Advies verlopen; wachten op actuele beoordeling door HEMS" : (labels[advice.status]??"Wachten op HEMS")+(reasons[advice.reason] ? `. ${reasons[advice.reason]}` : "")+". Advies; automatisch laden is nog niet actief.";
      el("ev-advice-cost").textContent=pending && fresh && advice.estimated_incremental_cost_eur!==undefined ? `Geschatte extra kosten: ${number(advice.estimated_incremental_cost_eur,"EUR")}. Beste van de beoordeelde laadblokken; geen garantie dat alle mogelijke starttijden zijn vergeleken.` : "";
      const list=el("ev-advice-slots");list.replaceChildren();
      if(pending && fresh)for(const slot of advice.slots??[]){const li=document.createElement("li");li.textContent=`${new Date(slot.starts_at).toLocaleString("nl-NL")} – ${new Date(slot.ends_at).toLocaleString("nl-NL")}: ${number(slot.energy_wh/1000,"kWh")}`;list.append(li);}
    }
    async function evChange(payload) {
      if(evBusy)return;
      evBusy=true;el("ev-now").disabled=true;
      try {const response=await fetch("api/ev",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(result.error);el("ev-message").textContent="Opgeslagen";} catch(error){el("ev-message").textContent=error.message;}
      evBusy=false;
      try {await load();} catch(error) {el("ev-message").textContent=error.message;}
    }
    el("ev-now").onclick=()=>evChange({action:"start_now"});
    el("ev-advice-form").onsubmit=(event)=>{event.preventDefault();const date=new Date(el("ev-ready-by").value);if(!Number.isFinite(date.getTime()))return;evChange({action:"request_advice",ready_by:date.toISOString(),required_energy_wh:Number(el("ev-required-kwh").value)*1000});};
    el("ev-advice-cancel").onclick=()=>evChange({action:"cancel_advice"});
    el("ev-profile").onsubmit=(event)=>{event.preventDefault();evChange({action:"save_profile",expected_power_w:Number(el("ev-profile-power").value),expected_duration_seconds:Number(el("ev-profile-duration").value)*60});};
    el("ev-verify").onclick=()=>{if(confirm("Heb je met deze auto en plug getest dat laden na uit- en inschakelen werkelijk hervat?"))evChange({action:"verify_resume",confirmed:true});};
    el("ev-plan").onsubmit=(event)=>{event.preventDefault();if(!evSession){el("ev-message").textContent="Herken eerst een sessie";return;}evChange({action:"plan",session_id:evSession.session_id,planned_start:new Date(el("ev-start").value).toISOString(),expected_power_w:Number(el("ev-power").value),expected_duration_seconds:Number(el("ev-duration").value)*60});};
    el("ev-resume").onclick=()=>evChange({action:"resume"});
    el("ev-cancel").onclick=()=>{if(evSession && confirm("Deze sessie annuleren? De laadplug wordt uitgeschakeld."))evChange({action:"cancel",session_id:evSession.session_id});};
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


def create_web_server(store: EnergyDeviceStore, *, host: str, port: int,
                      ev_sessions: EVSessionManager | None = None,
                      diagnostics: DiagnosticsRecorder | None = None) -> ThreadingHTTPServer:
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
            if path == "/api/diagnostics.zip":
                if diagnostics is None:
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Diagnose niet beschikbaar"})
                    return
                try:
                    body = diagnostics.export_zip()
                except (OSError, ValueError, sqlite3.Error):
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Diagnose kon niet worden gelezen"})
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                name = datetime.now(UTC).strftime("energy-devices-diagnostics-%Y%m%dT%H%M%SZ.zip")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/view":
                self._json(
                    HTTPStatus.OK,
                    {
                        "catalog": store.catalog(),
                        "ev": ev_sessions.view() if ev_sessions is not None else None,
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
            if urlsplit(self.path).path == "/api/ev":
                try:
                    if ev_sessions is None:
                        raise ValueError("EV-sessies zijn niet ingeschakeld")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        raise ValueError("Ongeldige invoer")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("Invoer moet een object zijn")
                    self._json(HTTPStatus.OK, ev_sessions.action(payload))
                except (ValueError, TypeError) as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
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
