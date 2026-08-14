"""Pure read-only data projection for the PicoT v2 web UI."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.projection import Projection

DASHBOARD_HTML = """<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PicoT v2 — Canonical Pipeline</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Inter, system-ui, sans-serif;
      background: #0b0f14;
      color: #eef4fb;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: #0b0f14; }
    main { width: min(1500px, 100%); margin: auto; padding: 24px; }
    header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 20px;
    }
    h1, h2, h3, p { margin-top: 0; }
    h1 { margin-bottom: 6px; font-size: 1.55rem; }
    h2 { margin: 28px 0 12px; font-size: 1.15rem; }
    h3 { margin-bottom: 10px; font-size: 1rem; }
    .muted { color: #96a6b8; }
    .observer {
      padding: 8px 12px;
      border: 1px solid #386f96;
      border-radius: 999px;
      background: #10283a;
      color: #8ed1ff;
      white-space: nowrap;
    }
    .metadata {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .metric, .source-card, .stage-card, .timeline-panel {
      border: 1px solid #27313d;
      border-radius: 12px;
      background: #151b23;
    }
    .metric { padding: 12px; }
    .metric span { display: block; }
    .metric .value {
      margin-top: 5px;
      color: #ffffff;
      overflow-wrap: anywhere;
    }
    .status {
      margin: 16px 0;
      padding: 10px 12px;
      border-radius: 8px;
      background: #152231;
      color: #9fcdf0;
    }
    .status[data-state="error"] {
      background: #351b20;
      color: #ffadb8;
    }
    .source-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }
    .source-card { padding: 14px; min-width: 0; }
    .source-status {
      display: inline-block;
      margin-bottom: 10px;
      padding: 4px 8px;
      border-radius: 6px;
      background: #193226;
      color: #8de5ae;
    }
    .source-status[data-state="unavailable"] {
      background: #351b20;
      color: #ffadb8;
    }
    .source-status[data-state="unconfigured"] {
      background: #3a3018;
      color: #ffd77a;
    }
    .pipeline {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .stage-card { padding: 14px; min-width: 0; }
    .stage-state {
      display: inline-block;
      margin-bottom: 12px;
      padding: 4px 8px;
      border-radius: 6px;
      background: #193226;
      color: #8de5ae;
    }
    dl { margin: 0; }
    .attribute {
      display: grid;
      grid-template-columns: minmax(110px, 0.8fr) minmax(0, 1.2fr);
      gap: 8px;
      padding: 6px 0;
      border-top: 1px solid #27313d;
    }
    dt { color: #96a6b8; overflow-wrap: anywhere; }
    dd { margin: 0; overflow-wrap: anywhere; }
    .technical-details {
      margin-top: 12px;
      border-top: 1px solid #27313d;
      padding-top: 10px;
      color: #96a6b8;
    }
    .technical-details summary { cursor: pointer; }
    .technical-details pre {
      max-height: 320px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: #d9e4ef;
      font-size: 0.78rem;
    }
    .timeline-panel { padding: 14px; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid #27313d;
      text-align: left;
      white-space: nowrap;
    }
    th { color: #96a6b8; font-weight: 600; }
    @media (max-width: 1000px) {
      .pipeline { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 680px) {
      main { padding: 14px; }
      header { display: block; }
      .observer { display: inline-block; margin-bottom: 14px; }
      .metadata, .pipeline { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body data-observer-only="true">
  <main>
    <header>
      <div>
        <h1>PicoT v2 — Canonical Pipeline</h1>
        <p class="muted">Live read-only observatie van de volledige pipeline.</p>
      </div>
      <div class="observer">Observer only</div>
    </header>

    <section class="metadata" aria-label="Runinformatie">
      <div class="metric">
        <span class="muted">Versie</span><span id="version" class="value">—</span>
      </div>
      <div class="metric">
        <span class="muted">Run</span><span id="run-id" class="value">—</span>
      </div>
      <div class="metric">
        <span class="muted">Vastgelegd</span><span id="captured-at" class="value">—</span>
      </div>
    </section>

    <p id="status" class="status">Wachten op de eerste pipeline-run…</p>

    <h2>Brongegevens</h2>
    <section
      id="sources"
      class="source-grid"
      aria-label="Brongegevens"
      aria-live="polite"
    >
      Nog geen brongegevens beschikbaar.
    </section>

    <h2>Pipeline ①→⑨</h2>
    <section id="pipeline" class="pipeline" aria-live="polite"></section>

    <h2>PV Energy Timeline</h2>
    <section id="pv-energy-timeline" class="timeline-panel" aria-live="polite">
      Nog geen PV-tijdlijn beschikbaar.
    </section>
  </main>

  <script>
    const stageNames = [
      "Planning Input",
      "Opportunity Engine",
      "Candidate Engine",
      "Evaluation Engine",
      "Execution Plan Builder",
      "Execution Engine",
      "Execution Primitive",
      "Device Adapter",
      "Vendor / Result"
    ];

    const sourceNames = {
      "p1": "P1 netmeting",
      "pv": "Zonnepanelen",
      "zendure": "Zendure batterij",
      "solcast": "Solcast voorspelling",
      "nordpool": "Nord Pool prijzen"
    };

    const sourceStates = {
      "available": "Beschikbaar",
      "unavailable": "Niet beschikbaar",
      "unconfigured": "Niet ingesteld"
    };

    const element = (id) => document.getElementById(id);

    function displayValue(value) {
      if (value === null || value === undefined) return "—";
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
    }

    function compactReference(key, value) {
      const displayed = displayValue(value);
      if (
        typeof value !== "string" ||
        !/(?:_id|_reference)$/.test(key) ||
        value.length <= 28
      ) {
        return displayed;
      }
      return value.slice(0, 14) + "…" + value.slice(-8);
    }

    function formatTimestamp(value) {
      if (!value) return "—";
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime())
        ? displayValue(value)
        : parsed.toLocaleString("nl-NL");
    }

    function appendAttribute(list, label, value, fullValue = value) {
      const row = document.createElement("div");
      row.className = "attribute";
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = displayValue(value);
      if (displayValue(fullValue) !== displayValue(value)) {
        description.title = displayValue(fullValue);
      }
      row.append(term, description);
      list.appendChild(row);
    }

    function appendTechnicalDetails(container, value) {
      const details = document.createElement("details");
      details.className = "technical-details";
      const summary = document.createElement("summary");
      const raw = document.createElement("pre");
      summary.textContent = "Technische details";
      raw.textContent = JSON.stringify(value, null, 2);
      details.append(summary, raw);
      container.appendChild(details);
    }

    function renderSources(sources) {
      const container = element("sources");
      container.replaceChildren();

      if (sources.length === 0) {
        container.textContent = "Nog geen brongegevens beschikbaar.";
        return;
      }

      const fragment = document.createDocumentFragment();
      for (const source of sources) {
        const card = document.createElement("article");
        card.className = "source-card";

        const heading = document.createElement("h3");
        heading.textContent =
          sourceNames[source.category] ?? displayValue(source.category);

        const state = document.createElement("span");
        state.className = "source-status";
        state.dataset.state = displayValue(source.availability);
        state.textContent =
          sourceStates[source.availability] ??
          displayValue(source.availability);

        const attributes = document.createElement("dl");
        appendAttribute(
          attributes,
          "Entiteit",
          compactReference("entity_id", source.entity_id),
          source.entity_id
        );
        appendAttribute(
          attributes,
          "Waarde",
          source.raw_state === null || source.raw_state === undefined
            ? "—"
            : String(source.raw_state) +
              (source.raw_unit ? " " + source.raw_unit : "")
        );
        appendAttribute(
          attributes,
          "Bijgewerkt",
          formatTimestamp(source.observed_at)
        );
        appendAttribute(
          attributes,
          "Fout",
          source.error
        );

        card.append(heading, state, attributes);
        appendTechnicalDetails(card, source);
        fragment.appendChild(card);
      }
      container.replaceChildren(fragment);
    }

    function renderPipeline(items) {
      const container = element("pipeline");
      const fragment = document.createDocumentFragment();

      for (const item of items) {
        const card = document.createElement("article");
        card.className = "stage-card";

        const heading = document.createElement("h3");
        heading.textContent = `${item.stage}. ${stageNames[item.stage - 1] ?? "Pipeline stage"}`;
        card.appendChild(heading);

        const state = document.createElement("span");
        state.className = "stage-state";
        state.textContent = displayValue(item.state);
        card.appendChild(state);

        const attributes = document.createElement("dl");
        const entries = Object.entries(item.attributes ?? {})
          .sort(([left], [right]) => left.localeCompare(right));
        const visibleEntries = entries.filter(
          ([, value]) => value === null || typeof value !== "object"
        );
        const technicalEntries = entries.filter(
          ([, value]) => value !== null && typeof value === "object"
        );

        for (const [key, value] of visibleEntries) {
          appendAttribute(
            attributes,
            key,
            compactReference(key, value),
            value
          );
        }

        card.appendChild(attributes);
        if (technicalEntries.length > 0) {
          appendTechnicalDetails(
            card,
            Object.fromEntries(technicalEntries)
          );
        }
        fragment.appendChild(card);
      }

      container.replaceChildren(fragment);
    }

    function renderTimeline(timeline) {
      const container = element("pv-energy-timeline");
      container.replaceChildren();

      const summary = document.createElement("p");
      summary.textContent = timeline.available
        ? `${timeline.interval_count} intervallen · ${timeline.total_wh} Wh`
        : "Nog geen PV-tijdlijn beschikbaar.";
      container.appendChild(summary);

      if (!timeline.available || timeline.intervals.length === 0) return;

      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headerRow = document.createElement("tr");
      for (const label of ["Start", "Einde", "Energie", "Confidence"]) {
        const cell = document.createElement("th");
        cell.textContent = label;
        headerRow.appendChild(cell);
      }
      head.appendChild(headerRow);
      table.appendChild(head);

      const body = document.createElement("tbody");
      for (const interval of timeline.intervals) {
        const row = document.createElement("tr");
        const values = [
          interval.starts_at,
          interval.ends_at,
          `${interval.pv_energy_wh} Wh`,
          interval.confidence
        ];
        for (const value of values) {
          const cell = document.createElement("td");
          cell.textContent = displayValue(value);
          row.appendChild(cell);
        }
        body.appendChild(row);
      }
      table.appendChild(body);
      container.appendChild(table);
    }

    async function loadView() {
      const status = element("status");
      try {
        const response = await fetch("api/view", { cache: "no-store" });
        if (response.status === 503) {
          status.dataset.state = "waiting";
          status.textContent = "Wachten op de eerste pipeline-run…";
          return;
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const view = await response.json();
        element("version").textContent = displayValue(view.picot_version);
        element("run-id").textContent = displayValue(view.run_id);
        element("captured-at").textContent = displayValue(view.captured_at);
        const pipeline = Array.isArray(view.pipeline) ? view.pipeline : [];
        const planningInput = pipeline.find((item) => item.stage === 1);
        const sources = planningInput?.attributes?.sources;
        renderSources(Array.isArray(sources) ? sources : []);
        renderPipeline(pipeline);
        renderTimeline(view.pv_energy_timeline ?? {
          available: false,
          interval_count: 0,
          total_wh: 0,
          intervals: []
        });
        status.dataset.state = "ready";
        status.textContent = "Live · automatisch ververst iedere 5 seconden";
      } catch (error) {
        status.dataset.state = "error";
        status.textContent = `Dashboarddata niet beschikbaar: ${error.message}`;
      }
    }

    loadView();
    setInterval(loadView, 5000);
  </script>
</body>
</html>
"""


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
        def _send_html(
            self,
            status: HTTPStatus,
            body: str,
        ) -> None:
            encoded = body.encode("utf-8")
            self.send_response(int(status))
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

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
            path = urlsplit(self.path).path
            if path == "/":
                self._send_html(HTTPStatus.OK, DASHBOARD_HTML)
                return

            if path != "/api/view":
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
