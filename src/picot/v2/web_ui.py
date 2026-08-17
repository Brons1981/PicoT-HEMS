"""Pure read-only data projection for the PicoT v2 web UI."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Condition, Lock
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from picot.domain.energy_path import PathSegment
from picot.v2.contracts import CanonicalPipelineRun, PriceForecastPoint
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
    .dashboard-tabs {
      display: flex;
      gap: 8px;
      margin: 0 0 18px;
      overflow-x: auto;
      scrollbar-width: thin;
    }
    .tab-button {
      border: 1px solid #386f96;
      border-radius: 8px;
      padding: 9px 13px;
      background: #10283a;
      color: #b9dcf5;
      cursor: pointer;
      white-space: nowrap;
    }
    .tab-button[aria-selected="true"] {
      border-color: #5db9f3;
      background: #17466a;
      color: #ffffff;
    }
    .tab-panel[hidden] { display: none; }
    .empty-panel {
      padding: 14px;
      border: 1px solid #27313d;
      border-radius: 12px;
      background: #151b23;
      color: #96a6b8;
    }
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
    .metric, .source-card, .stage-card, .timeline-panel, .price-panel,
    .zendure-now {
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
    .stage-card { padding: 0; min-width: 0; }
    .stage-card > summary { cursor: pointer; list-style-position: inside; }
    .stage-summary {
      padding: 10px 12px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 4px;
    }
    .stage-summary h3 { display: inline; margin: 0; }
    .stage-result {
      margin: 0;
      margin-left: 8px;
      color: #b7c6d6;
      font-size: 0.88rem;
    }
    .stage-health {
      width: 13px;
      height: 13px;
      margin-left: auto;
      flex: 0 0 13px;
      border-radius: 50%;
      background: #35a862;
      box-shadow: 0 0 0 3px rgba(53, 168, 98, 0.16);
    }
    .stage-health[data-health="fault"] {
      background: #df4f5f;
      box-shadow: 0 0 0 3px rgba(223, 79, 95, 0.18);
    }
    .pipeline-health[data-health="healthy"] {
      background: #193226;
      color: #8de5ae;
    }
    .pipeline-health[data-health="fault"] {
      background: #351b20;
      color: #ffadb8;
    }
    .zendure-now { padding: 14px; }
    .zendure-now-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
    }
    .stage-card > .stage-state,
    .stage-card > dl,
    .stage-card > .technical-details { margin-left: 12px; margin-right: 12px; }
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
    .energy-chart-panel { padding: 14px; overflow: hidden; }
    .energy-chart-scroll { overflow-x: auto; }
    .energy-chart {
      display: block;
      width: 100%;
      min-width: 760px;
      height: auto;
    }
    .energy-chart .grid-line { stroke: #27313d; stroke-width: 1; }
    .energy-chart .axis-label { fill: #96a6b8; font-size: 12px; }
    .energy-chart .forecast-range {
      fill: #f2b84b;
      opacity: 0.16;
    }
    .energy-chart .forecast-line {
      fill: none;
      stroke: #f2b84b;
      stroke-width: 3;
      opacity: 0.48;
    }
    .energy-chart .actual-line {
      fill: none;
      stroke: #ffd400;
      stroke-width: 3;
    }
    .energy-chart-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-bottom: 10px;
      color: #96a6b8;
    }
    .energy-chart-key {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .energy-chart-swatch {
      width: 18px;
      height: 4px;
      border-radius: 2px;
      background: #ffd400;
    }
    .energy-chart-swatch.forecast {
      background: #f2b84b;
      opacity: 0.48;
    }
    .price-panel { padding: 14px; overflow: hidden; }
    .price-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-bottom: 10px;
      color: #96a6b8;
    }
    .price-legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .price-swatch {
      width: 12px;
      height: 12px;
      border-radius: 3px;
      background: #477fa8;
    }
    .price-swatch.low { background: #35a862; }
    .price-swatch.high { background: #df6b57; }
    .price-swatch.missing { background: #2b3541; }
    .price-chart-scroll { overflow-x: auto; }
    .price-chart {
      display: block;
      width: 100%;
      min-width: 760px;
      height: auto;
    }
    .price-chart .grid-line {
      stroke: #27313d;
      stroke-width: 1;
    }
    .price-chart .zero-line {
      stroke: #96a6b8;
      stroke-width: 1.5;
    }
    .price-chart .axis-label {
      fill: #96a6b8;
      font-size: 12px;
    }
    .price-chart .missing-area { fill: #232c36; }
    .price-chart .price-bar {
      fill: #477fa8;
      opacity: 0.85;
    }
    .price-chart .price-bar.low { fill: #35a862; }
    .price-chart .price-bar.high { fill: #df6b57; }
    .price-chart .price-bar.past { opacity: 0.30; }
    .price-chart .now-line {
      stroke: #eef4fb;
      stroke-width: 1.5;
      stroke-dasharray: 3 4;
    }
    .price-chart .now-label {
      fill: #eef4fb;
      font-size: 12px;
    }
    .price-chart .horizon-line {
      stroke: #ffd77a;
      stroke-width: 2;
      stroke-dasharray: 6 5;
    }
    .price-chart .horizon-label {
      fill: #ffd77a;
      font-size: 12px;
    }
    .price-detail {
      min-height: 22px;
      margin: 8px 0 0;
      color: #96a6b8;
    }
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
        <p class="muted">Live status van de volledige PicoT-pipeline.</p>
      </div>
      <div id="execution-mode" class="observer">Status wordt geladen</div>
    </header>

    <nav class="dashboard-tabs" aria-label="Dashboardweergave">
      <button
        class="tab-button" type="button" data-tab="overview"
        aria-selected="true"
      >Overzicht</button>
      <button
        class="tab-button" type="button" data-tab="planning"
        aria-selected="false"
      >Dagplanning</button>
      <button
        class="tab-button" type="button" data-tab="history"
        aria-selected="false"
      >Historie</button>
      <button
        class="tab-button" type="button" data-tab="strategy"
        aria-selected="false"
      >Strategie</button>
      <button
        class="tab-button" type="button" data-tab="technical"
        aria-selected="false"
      >Techniek</button>
    </nav>
    <section
      id="tab-overview" class="tab-panel" data-tab-panel="overview"
    ></section>
    <section
      id="tab-planning" class="tab-panel" data-tab-panel="planning" hidden
    ></section>
    <section
      id="tab-history" class="tab-panel" data-tab-panel="history" hidden
    >
      <h2>Zon: forecast en werkelijkheid</h2>
      <section
        id="pv-forecast-actual-chart"
        class="timeline-panel energy-chart-panel"
        aria-live="polite"
      >
        Nog geen gesloten PV-intervallen beschikbaar.
      </section>
      <p class="empty-panel">
        P1, huisverbruik, batterij, netimport en netexport volgen zodra hun
        canonieke dagtijdreeksen beschikbaar zijn.
      </p>
    </section>
    <section
      id="tab-strategy" class="tab-panel" data-tab-panel="strategy" hidden
    >
      <p class="empty-panel">
        Plannerstrategie en gebruikerskeuzes worden hier zichtbaar zodra de
        bijbehorende canonieke contracten beschikbaar zijn.
      </p>
    </section>
    <section
      id="tab-technical" class="tab-panel" data-tab-panel="technical" hidden
    ></section>

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

    <section
      id="storage-mode-override"
      class="status"
      aria-live="polite"
    >
      <span id="storage-mode-override-result">
        Nog geen informatie over handmatige batterijbediening.
      </span>
      <button id="reset-storage-mode-override" type="button" hidden>
        Handmatige instelling vrijgeven
      </button>
    </section>

    <h2>Zendure nu</h2>
    <section id="zendure-now" class="zendure-now" aria-live="polite">
      Nog geen actuele Zendure-status beschikbaar.
    </section>

    <h2>Brongegevens</h2>
    <section
      id="sources"
      class="source-grid"
      aria-label="Brongegevens"
      aria-live="polite"
    >
      Nog geen brongegevens beschikbaar.
    </section>

    <h2>Prijsverloop vandaag en morgen</h2>
    <section id="price-timeline" class="price-panel" aria-live="polite">
      Nog geen prijsgegevens beschikbaar.
    </section>

    <h2>Pipeline ①→⑨ + Live-canary</h2>
    <p id="pipeline-health" class="status pipeline-health" aria-live="polite">
      Wachten op de eerste pipeline-run…
    </p>
    <section id="pipeline" class="pipeline" aria-live="polite"></section>

    <h2>Wat PicoT overweegt</h2>
    <section
      id="plan-explanation"
      class="timeline-panel"
      aria-live="polite"
    >
      Nog geen planuitleg beschikbaar.
    </section>

    <h2>Energieplan batterij</h2>
    <section
      id="storage-energy-source-needs"
      class="timeline-panel"
      aria-live="polite"
    >
      Nog geen energieplan voor de batterij beschikbaar.
    </section>

    <h2>PV Energy Timeline</h2>
    <section id="pv-energy-timeline" class="timeline-panel" aria-live="polite">
      Nog geen PV-tijdlijn beschikbaar.
    </section>

    <h2>Verwacht huishoudverbruik</h2>
    <section id="household-load-forecast" class="timeline-panel" aria-live="polite">
      Nog geen prognose voor huishoudverbruik beschikbaar.
    </section>
  </main>

  <script>
    const stageNames = [
      "Planningsinvoer",
      "Energiekansen",
      "Mogelijke plannen",
      "Planbeoordeling",
      "Uitvoeringsplan",
      "Uitvoering",
      "Uitvoerbare opdracht",
      "Apparaatkoppeling",
      "Zendure-resultaat"
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
    const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
    const PRICE_DISPLAY_HOURS = 48;
    let pendingView = null;
    let viewRevision = 0;
    let updateWatcherStopped = false;
    const ACTIVE_TAB_KEY = "picot-active-dashboard-tab";

    function createSvgElement(name, attributes = {}) {
      const node = document.createElementNS(SVG_NAMESPACE, name);
      for (const [key, value] of Object.entries(attributes)) {
        node.setAttribute(key, String(value));
      }
      return node;
    }

    function appendSvgText(parent, text, attributes, className) {
      const node = createSvgElement("text", attributes);
      node.classList.add(className);
      node.textContent = text;
      parent.appendChild(node);
      return node;
    }

    function formatPrice(value) {
      const numeric = Number(value);
      return Number.isFinite(numeric)
        ? `${numeric.toFixed(3).replace(".", ",")} €/kWh`
        : "—";
    }

    function formatChartTime(value, timezone) {
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) return "—";
      return parsed.toLocaleString("nl-NL", {
        timeZone: timezone,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit"
      });
    }

    function priceWindowKind(point, opportunities) {
      const startsAt = new Date(point.starts_at).getTime();
      const endsAt = new Date(point.ends_at).getTime();
      const matching = opportunities.filter((opportunity) => {
        const windowStart = new Date(opportunity.starts_at).getTime();
        const windowEnd = new Date(opportunity.ends_at).getTime();
        return startsAt < windowEnd && endsAt > windowStart;
      });

      if (
        matching.some(
          (opportunity) =>
            opportunity.kind === "NEGATIVE_PRICE_WINDOW" ||
            opportunity.kind === "LOWEST_PRICE_WINDOW"
        )
      ) {
        return "low";
      }
      if (
        matching.some(
          (opportunity) =>
            opportunity.kind === "HIGH_EXPORT_VALUE_WINDOW"
        )
      ) {
        return "high";
      }
      return "normal";
    }

    function priceWindowLabel(kind) {
      if (kind === "low") return "Laagste-prijsvenster";
      if (kind === "high") return "Hoogste-teruglevervenster";
      return "Geen prijsvenster";
    }

    function renderPriceTimeline(timeline, capturedAt) {
      const container = element("price-timeline");
      container.replaceChildren();

      const start = new Date(timeline.display_starts_at);
      const end = new Date(timeline.display_ends_at);
      const captured = new Date(capturedAt);
      if (
        Number.isNaN(start.getTime()) ||
        Number.isNaN(end.getTime()) ||
        Number.isNaN(captured.getTime()) ||
        end <= start
      ) {
        container.textContent = "Geen geldige kalenderperiode beschikbaar.";
        return;
      }

      const points = Array.isArray(timeline.points)
        ? timeline.points
        : [];
      const opportunities = Array.isArray(timeline.opportunities)
        ? timeline.opportunities
        : [];
      const timezone =
        timeline.market_timezone ?? "Europe/Amsterdam";
      const startsAtMs = start.getTime();
      const endsAtMs = end.getTime();
      const capturedAtMs = captured.getTime();
      const displayHours =
        (endsAtMs - startsAtMs) / (60 * 60 * 1000);
      const visiblePoints = points.filter((point) => {
        const pointStart = new Date(point.starts_at).getTime();
        const pointEnd = new Date(point.ends_at).getTime();
        return pointStart < endsAtMs && pointEnd > startsAtMs;
      });

      const legend = document.createElement("div");
      legend.className = "price-legend";
      for (const [kind, label] of [
        ["normal", "Overige prijzen"],
        ["low", "Laagste-prijsvenster"],
        ["high", "Hoogste-teruglevervenster"],
        ["missing", "Nog niet gepubliceerd"]
      ]) {
        const item = document.createElement("span");
        item.className = "price-legend-item";
        const swatch = document.createElement("span");
        swatch.className = `price-swatch ${kind}`;
        item.append(swatch, label);
        legend.appendChild(item);
      }
      container.appendChild(legend);

      const width = 1200;
      const height = 350;
      const margin = {
        top: 24,
        right: 20,
        bottom: 52,
        left: 76
      };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const values = visiblePoints
        .map((point) => Number(point.value_eur_per_kwh))
        .filter((value) => Number.isFinite(value));
      let minimum = Math.min(0, ...values);
      let maximum = Math.max(0, ...values);
      const initialRange = maximum - minimum || 0.1;
      minimum -= initialRange * 0.1;
      maximum += initialRange * 0.1;

      const xPosition = (timestamp) =>
        margin.left +
        ((timestamp - startsAtMs) / (endsAtMs - startsAtMs)) *
          plotWidth;
      const yPosition = (value) =>
        margin.top +
        ((maximum - value) / (maximum - minimum)) *
          plotHeight;

      const scroll = document.createElement("div");
      scroll.className = "price-chart-scroll";
      const svg = createSvgElement("svg", {
        class: "price-chart",
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": (
          "Prijsverloop voor 48 uur met gemarkeerde PicoT-prijsvensters"
        )
      });

      svg.appendChild(
        createSvgElement("rect", {
          class: "missing-area",
          x: margin.left,
          y: margin.top,
          width: plotWidth,
          height: plotHeight
        })
      );

      for (let index = 0; index <= 4; index += 1) {
        const value =
          maximum - ((maximum - minimum) * index) / 4;
        const y = yPosition(value);
        svg.appendChild(
          createSvgElement("line", {
            class: Math.abs(value) < 0.000001
              ? "zero-line"
              : "grid-line",
            x1: margin.left,
            x2: width - margin.right,
            y1: y,
            y2: y
          })
        );
        appendSvgText(
          svg,
          formatPrice(value),
          {
            x: margin.left - 8,
            y: y + 4,
            "text-anchor": "end"
          },
          "axis-label"
        );
      }

      for (let hour = 0; hour <= displayHours; hour += 6) {
        const timestamp =
          startsAtMs + hour * 60 * 60 * 1000;
        const x = xPosition(timestamp);
        svg.appendChild(
          createSvgElement("line", {
            class: "grid-line",
            x1: x,
            x2: x,
            y1: margin.top,
            y2: height - margin.bottom
          })
        );
        appendSvgText(
          svg,
          formatChartTime(timestamp, timezone),
          {
            x,
            y: height - 20,
            "text-anchor": hour === 0 ? "start" : "middle"
          },
          "axis-label"
        );
      }

      const detail = document.createElement("p");
      detail.className = "price-detail";
      detail.textContent =
        "Selecteer een staaf voor tijdstip, prijs en vensterstatus.";

      const zeroY = yPosition(0);
      for (const point of visiblePoints) {
        const pointStart = Math.max(
          startsAtMs,
          new Date(point.starts_at).getTime()
        );
        const pointEnd = Math.min(
          endsAtMs,
          new Date(point.ends_at).getTime()
        );
        const value = Number(point.value_eur_per_kwh);
        if (
          !Number.isFinite(pointStart) ||
          !Number.isFinite(pointEnd) ||
          !Number.isFinite(value) ||
          pointEnd <= pointStart
        ) {
          continue;
        }

        const kind = priceWindowKind(point, opportunities);
        const isPast = pointEnd <= capturedAtMs;
        const valueY = yPosition(value);
        const bar = createSvgElement("rect", {
          class: `price-bar ${kind}${isPast ? " past" : ""}`,
          x: xPosition(pointStart) + 0.5,
          y: Math.min(valueY, zeroY),
          width: Math.max(
            1,
            xPosition(pointEnd) - xPosition(pointStart) - 1
          ),
          height: Math.max(1, Math.abs(zeroY - valueY)),
          rx: 2,
          tabindex: 0
        });
        const showDetail = () => {
          detail.textContent = [
            `${formatTimestamp(point.starts_at)} – ` +
              formatTimestamp(point.ends_at),
            formatPrice(value),
            priceWindowLabel(kind),
            `Confidence ${formatConfidence(point.confidence)}`
          ].join(" · ");
        };
        bar.addEventListener("mouseenter", showDetail);
        bar.addEventListener("focus", showDetail);
        bar.addEventListener("click", showDetail);
        svg.appendChild(bar);
      }

      if (
        capturedAtMs > startsAtMs &&
        capturedAtMs < endsAtMs
      ) {
        const x = xPosition(capturedAtMs);
        svg.appendChild(
          createSvgElement("line", {
            class: "now-line",
            x1: x,
            x2: x,
            y1: margin.top,
            y2: height - margin.bottom
          })
        );
        appendSvgText(
          svg,
          "Nu",
          {
            x: x + 6,
            y: margin.top + 16,
            "text-anchor": "start"
          },
          "now-label"
        );
      }

      const horizonEnd = new Date(
        timeline.planning_horizon_ends_at
      ).getTime();
      if (
        Number.isFinite(horizonEnd) &&
        horizonEnd > startsAtMs &&
        horizonEnd < endsAtMs
      ) {
        const x = xPosition(horizonEnd);
        svg.appendChild(
          createSvgElement("line", {
            class: "horizon-line",
            x1: x,
            x2: x,
            y1: margin.top,
            y2: height - margin.bottom
          })
        );
        appendSvgText(
          svg,
          "Einde planning 36 uur",
          {
            x: x - 6,
            y: margin.top + 16,
            "text-anchor": "end"
          },
          "horizon-label"
        );
      }

      scroll.appendChild(svg);
      container.append(scroll, detail);
    }

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

    function formatConfidence(value) {
      const numeric = Number(value);
      return Number.isFinite(numeric)
        ? `${Math.round(numeric * 100)}%`
        : "—";
    }

    function formatDutchNumber(value) {
      return new Intl.NumberFormat("nl-NL", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(value);
    }

    function formatMeasurement(value, unit) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return "—";
      if (unit === "W") {
        return Math.abs(numeric) >= 1000
          ? formatDutchNumber(numeric / 1000) + " kW"
          : formatDutchNumber(numeric) + " W";
      }
      if (unit === "Wh") {
        return Math.abs(numeric) >= 1000
          ? formatDutchNumber(numeric / 1000) + " kWh"
          : formatDutchNumber(numeric) + " Wh";
      }
      return formatDutchNumber(numeric) + (unit ? " " + unit : "");
    }

    function formatAttributeValue(key, value) {
      if (typeof value !== "number") return compactReference(key, value);
      if (/_w$/.test(key)) return formatMeasurement(value, "W");
      if (/_wh$/.test(key)) return formatMeasurement(value, "Wh");
      return compactReference(key, value);
    }

    function formatEnergyKwh(valueWh) {
      const numeric = Number(valueWh);
      return Number.isFinite(numeric)
        ? formatDutchNumber(numeric / 1000) + " kWh"
        : "—";
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

    function renderPvForecastActualChart(intervals) {
      const container = element("pv-forecast-actual-chart");
      container.replaceChildren();
      const points = (Array.isArray(intervals) ? intervals : [])
        .filter((item) =>
          Number.isFinite(Number(item.forecast_central_energy_wh)) &&
          Number.isFinite(Number(item.actual_energy_wh))
        )
        .sort((left, right) =>
          new Date(left.starts_at).getTime() -
          new Date(right.starts_at).getTime()
        );
      if (points.length === 0) {
        container.textContent =
          "Nog geen gesloten PV-intervallen met forecast en werkelijkheid.";
        return;
      }

      const legend = document.createElement("div");
      legend.className = "energy-chart-legend";
      for (const [kind, label] of [
        ["forecast", "Solcast forecast en bereik"],
        ["actual", "Werkelijke PV"],
      ]) {
        const item = document.createElement("span");
        item.className = "energy-chart-key";
        const swatch = document.createElement("span");
        swatch.className = `energy-chart-swatch ${kind}`;
        item.append(swatch, document.createTextNode(label));
        legend.appendChild(item);
      }
      container.appendChild(legend);

      const width = Math.max(760, points.length * 42 + 100);
      const height = 340;
      const plot = { left: 64, right: 24, top: 20, bottom: 48 };
      const plotWidth = width - plot.left - plot.right;
      const plotHeight = height - plot.top - plot.bottom;
      const values = points.flatMap((item) => [
        Number(item.actual_energy_wh),
        Number(item.forecast_upper_energy_wh ?? item.forecast_central_energy_wh),
      ]);
      const maximum = Math.max(1, ...values);
      const x = (index) =>
        plot.left + (points.length === 1
          ? plotWidth / 2
          : index * plotWidth / (points.length - 1));
      const y = (value) =>
        plot.top + plotHeight -
        Math.max(0, Number(value)) / maximum * plotHeight;

      const scroll = document.createElement("div");
      scroll.className = "energy-chart-scroll";
      const svg = createSvgElement("svg", {
        class: "energy-chart",
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": "PV forecast versus werkelijke PV per gesloten interval",
      });
      for (let step = 0; step <= 4; step += 1) {
        const value = maximum * step / 4;
        const lineY = y(value);
        svg.appendChild(createSvgElement("line", {
          x1: plot.left,
          x2: width - plot.right,
          y1: lineY,
          y2: lineY,
          class: "grid-line",
        }));
        appendSvgText(
          svg,
          `${Math.round(value)} Wh`,
          { x: plot.left - 8, y: lineY + 4, "text-anchor": "end" },
          "axis-label",
        );
      }

      const upper = points.map((item, index) =>
        `${x(index)},${y(
          item.forecast_upper_energy_wh ?? item.forecast_central_energy_wh
        )}`
      );
      const lower = points.map((item, index) =>
        `${x(index)},${y(
          item.forecast_lower_energy_wh ?? item.forecast_central_energy_wh
        )}`
      ).reverse();
      svg.appendChild(createSvgElement("polygon", {
        points: [...upper, ...lower].join(" "),
        class: "forecast-range",
      }));
      svg.appendChild(createSvgElement("polyline", {
        points: points.map((item, index) =>
          `${x(index)},${y(item.forecast_central_energy_wh)}`
        ).join(" "),
        class: "forecast-line",
      }));
      svg.appendChild(createSvgElement("polyline", {
        points: points.map((item, index) =>
          `${x(index)},${y(item.actual_energy_wh)}`
        ).join(" "),
        class: "actual-line",
      }));
      points.forEach((item, index) => {
        if (index % 2 !== 0 && points.length > 18) return;
        appendSvgText(
          svg,
          new Date(item.starts_at).toLocaleTimeString("nl-NL", {
            hour: "2-digit",
            minute: "2-digit",
          }),
          { x: x(index), y: height - 18, "text-anchor": "middle" },
          "axis-label",
        );
      });
      scroll.appendChild(svg);
      container.appendChild(scroll);
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
            : ["W", "Wh"].includes(source.raw_unit)
              ? formatMeasurement(source.raw_state, source.raw_unit)
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
        const details = document.createElement("details");
        details.className = "stage-card";

        const summary = document.createElement("summary");
        summary.className = "stage-summary";

        const heading = document.createElement("h3");
        heading.textContent = `${item.stage}. ${stageNames[item.stage - 1] ?? "Pipeline stage"}`;

        const result = document.createElement("span");
        result.className = "stage-result";
        result.textContent = item.result_nl;
        const health = document.createElement("span");
        health.className = "stage-health";
        health.dataset.health = item.health;
        health.title = item.health === "healthy"
          ? "Deze pipelinestap werkt correct"
          : "Deze pipelinestap heeft een fout";
        health.setAttribute("aria-label", health.title);
        summary.append(heading, result, health);
        details.appendChild(summary);

        const state = document.createElement("span");
        state.className = "stage-state";
        state.textContent = displayValue(item.state);
        details.appendChild(state);

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
            formatAttributeValue(key, value),
            value
          );
        }

        details.appendChild(attributes);
        if (technicalEntries.length > 0) {
          appendTechnicalDetails(
            details,
            Object.fromEntries(technicalEntries)
          );
        }
        fragment.appendChild(details);
      }

      container.replaceChildren(fragment);
    }

    function renderPipelineHealth(health) {
      const container = element("pipeline-health");
      const healthy = health?.healthy === true;
      container.dataset.health = healthy ? "healthy" : "fault";
      container.textContent = health?.summary_nl ??
        "De gezondheid van de pipeline is nog niet bekend.";
    }

    function renderZendureNow(status) {
      const container = element("zendure-now");
      const grid = document.createElement("dl");
      grid.className = "zendure-now-grid";
      const originLabels = {
        picot: "PicoT",
        manual: "Handmatig vastgesteld",
        unknown: "Nog onbekend"
      };
      appendAttribute(grid, "Actieve modus", status?.active_mode);
      appendAttribute(
        grid,
        "Ingesteld door",
        originLabels[status?.origin] ?? displayValue(status?.origin)
      );
      appendAttribute(grid, "Ingesteld / vastgesteld", formatTimestamp(status?.set_at));
      appendAttribute(grid, "Laatst waargenomen", formatTimestamp(status?.observed_at));
      appendAttribute(grid, "Geplande modus", status?.planned_mode);
      appendAttribute(grid, "Laatste resultaat", status?.last_result_nl);
      container.replaceChildren(grid);
    }

    function renderPlanExplanation(explanation) {
      const container = element("plan-explanation");
      if (!explanation) {
        container.textContent = "Nog geen planuitleg beschikbaar.";
        return;
      }

      const fragment = document.createDocumentFragment();
      const opportunityHeading = document.createElement("h3");
      opportunityHeading.textContent = `Energiekansen (${explanation.opportunity_count ?? 0})`;
      fragment.appendChild(opportunityHeading);

      const groups = Array.isArray(explanation.opportunity_groups)
        ? explanation.opportunity_groups
        : [];
      if (groups.length === 0) {
        const empty = document.createElement("p");
        empty.textContent = "Er zijn nu geen prijsgerelateerde energiekansen.";
        fragment.appendChild(empty);
      }
      for (const group of groups) {
        const details = document.createElement("details");
        details.className = "plan-explanation-detail";
        details.dataset.explanationKey = `opportunity:${group.label_nl}`;
        const summary = document.createElement("summary");
        summary.textContent = group.summary_nl;
        details.appendChild(summary);
        const list = document.createElement("ul");
        for (const item of group.items ?? []) {
          const row = document.createElement("li");
          row.textContent = item.summary_nl;
          list.appendChild(row);
        }
        details.appendChild(list);
        fragment.appendChild(details);
      }

      const planHeading = document.createElement("h3");
      planHeading.textContent = "Mogelijke plannen";
      fragment.appendChild(planHeading);
      for (const plan of explanation.plans ?? []) {
        const details = document.createElement("details");
        details.className = "plan-explanation-detail";
        details.dataset.explanationKey = `plan:${plan.key}`;
        const summary = document.createElement("summary");
        summary.textContent = `${plan.selected ? "Gekozen: " : "Alternatief: "}${plan.label_nl}`;
        details.appendChild(summary);
        const description = document.createElement("p");
        const phases = (plan.phases ?? []).map(
          (phase) => phase.summary_nl
        );
        description.textContent = [
          plan.period_nl,
          ...phases,
          plan.energy_nl,
          plan.grid_energy_nl,
          plan.reason_nl
        ].join(" · ");
        details.appendChild(description);
        fragment.appendChild(details);
      }

      const decision = document.createElement("p");
      decision.textContent = [
        explanation.decision?.summary_nl,
        explanation.decision?.reason_nl
      ].filter(Boolean).join(" ");
      fragment.appendChild(decision);

      if (explanation.readiness?.warning_nl) {
        const warning = document.createElement("p");
        warning.className = "warning";
        warning.textContent = explanation.readiness.warning_nl;
        fragment.appendChild(warning);
      }
      container.replaceChildren(fragment);
    }

    function renderStorageModeOverride(item) {
      const result = element("storage-mode-override-result");
      const resetButton = element("reset-storage-mode-override");
      const manualOverrideActive =
        item?.attributes?.manual_override_active === true;
      resetButton.hidden = !manualOverrideActive;
      result.textContent = manualOverrideActive
        ? "Een handmatige batterij-instelling blokkeert PicoT."
        : "Geen actieve handmatige blokkade.";
    }

    function storageModeResetId() {
      if (
        globalThis.crypto &&
        typeof globalThis.crypto.randomUUID === "function"
      ) {
        return globalThis.crypto.randomUUID();
      }
      const randomValues = new Uint32Array(2);
      if (
        globalThis.crypto &&
        typeof globalThis.crypto.getRandomValues === "function"
      ) {
        globalThis.crypto.getRandomValues(randomValues);
      } else {
        randomValues[0] = Math.floor(Math.random() * 0x100000000);
        randomValues[1] = Math.floor(Math.random() * 0x100000000);
      }
      return [
        "reset",
        Date.now().toString(36),
        randomValues[0].toString(36),
        randomValues[1].toString(36)
      ].join("-");
    }

    async function resetStorageModeOverride() {
      const resetButton = element("reset-storage-mode-override");
      resetButton.disabled = true;
      try {
        const response = await fetch("api/storage-mode-override/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reset_id: storageModeResetId() })
        });
        if (!response.ok) {
          throw new Error(`Reset geweigerd (${response.status})`);
        }
        element("storage-mode-override-result").textContent =
          "De handmatige blokkade is vrijgegeven.";
        resetButton.hidden = true;
        await loadView();
      } catch (error) {
        element("storage-mode-override-result").textContent =
          error instanceof Error ? error.message : "Reset mislukt.";
      } finally {
        resetButton.disabled = false;
      }
    }

    function renderStorageEnergySourceNeeds(needs) {
      const container = element("storage-energy-source-needs");
      container.replaceChildren();

      if (!Array.isArray(needs) || needs.length === 0) {
        container.textContent =
          "Nog geen energieplan voor de batterij beschikbaar.";
        return;
      }

      for (const need of needs) {
        const article = document.createElement("article");
        const summary = document.createElement("p");
        const deadline = formatTimestamp(need.required_by);

        if (need.status === "target_already_met") {
          summary.textContent =
            "Zendure batterij heeft het geplande doel van " +
            formatEnergyKwh(need.target_energy_wh) +
            " al bereikt; aanvullende laadenergie is niet nodig.";
        } else if (need.status === "pv_only_feasible") {
          summary.textContent =
            "Zendure batterij mist " +
            formatEnergyKwh(need.energy_to_target_wh) +
            " om het geplande doel van " +
            formatEnergyKwh(need.target_energy_wh) +
            " te bereiken. De verwachte PV kan dit vóór " +
            deadline +
            " zonder netladen bereiken.";
        } else {
          summary.textContent =
            "Zendure batterij mist " +
            formatEnergyKwh(need.energy_to_target_wh) +
            " om het geplande doel van " +
            formatEnergyKwh(need.target_energy_wh) +
            " te bereiken. Van de verwachte " +
            formatEnergyKwh(need.expected_usable_pv_energy_wh) +
            " PV blijft na " +
            formatEnergyKwh(need.household_load_forecast_energy_wh) +
            " huishoudverbruik " +
            formatEnergyKwh(need.pv_storage_contribution_wh) +
            " beschikbaar voor opslag. Daardoor resteert " +
            formatEnergyKwh(need.grid_energy_required_wh) +
            " mogelijke netlaadbehoefte vóór " +
            deadline +
            ".";
        }

        const attributes = document.createElement("dl");
        appendAttribute(
          attributes,
          "PV-only haalbaar",
          need.pv_only_feasible ? "Ja" : "Nee"
        );
        appendAttribute(
          attributes,
          "Confidence",
          formatConfidence(need.confidence)
        );
        article.append(summary, attributes);
        appendTechnicalDetails(article, need);
        container.appendChild(article);
      }
    }

    function renderHouseholdLoadForecast(forecast) {
      const container = element("household-load-forecast");
      const quarterDetailsOpen =
        container.querySelector("details")?.open ?? false;
      container.replaceChildren();

      if (!forecast.available) {
        container.textContent =
          "Nog geen prognose voor huishoudverbruik beschikbaar.";
        return;
      }

      const intervals = Array.isArray(forecast.intervals)
        ? forecast.intervals
        : [];
      const attributes = document.createElement("dl");
      appendAttribute(
        attributes,
        "Periode",
        `${formatTimestamp(forecast.starts_at)} – ${formatTimestamp(forecast.ends_at)}`
      );
      appendAttribute(
        attributes,
        "Verwachte energie",
        `${forecast.total_wh} Wh`
      );
      appendAttribute(
        attributes,
        "Kwartieren",
        forecast.interval_count
      );
      appendAttribute(
        attributes,
        "Gemiddelde confidence",
        formatConfidence(forecast.average_confidence)
      );
      appendAttribute(
        attributes,
        "Fallback",
        forecast.fallback_active ? "Actief" : "Niet actief"
      );
      appendAttribute(
        attributes,
        "Reden fallback",
        forecast.fallback_reason === "insufficient_history"
          ? "Onvoldoende historische gegevens"
          : forecast.fallback_reason
      );
      container.appendChild(attributes);

      if (intervals.length === 0) return;

      const details = document.createElement("details");
      details.className = "technical-details";
      details.open = quarterDetailsOpen;
      const summary = document.createElement("summary");
      summary.textContent = `Kwartierdetails (${intervals.length})`;
      details.appendChild(summary);

      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headerRow = document.createElement("tr");
      for (const label of [
        "Start",
        "Einde",
        "Verwacht verbruik",
        "Confidence"
      ]) {
        const cell = document.createElement("th");
        cell.textContent = label;
        headerRow.appendChild(cell);
      }
      head.appendChild(headerRow);
      table.appendChild(head);

      const body = document.createElement("tbody");
      for (const interval of intervals) {
        const row = document.createElement("tr");
        const values = [
          formatTimestamp(interval.starts_at),
          formatTimestamp(interval.ends_at),
          `${interval.expected_energy_wh} Wh`,
          formatConfidence(interval.confidence)
        ];
        for (const value of values) {
          const cell = document.createElement("td");
          cell.textContent = displayValue(value);
          row.appendChild(cell);
        }
        body.appendChild(row);
      }
      table.appendChild(body);
      details.appendChild(table);
      container.appendChild(details);
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

    function movePanelContent(elementId, panelName, includeHeading = true) {
      const node = element(elementId);
      const panel = element("tab-" + panelName);
      if (!node || !panel) return;
      if (includeHeading && node.previousElementSibling?.tagName === "H2") {
        panel.appendChild(node.previousElementSibling);
      }
      panel.appendChild(node);
    }

    function activateTab(tabName) {
      const available = Array.from(
        document.querySelectorAll("[data-tab-panel]")
      ).map((panel) => panel.dataset.tabPanel);
      const selected = available.includes(tabName) ? tabName : "overview";
      document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.tabPanel !== selected;
      });
      document.querySelectorAll(".tab-button").forEach((button) => {
        button.setAttribute(
          "aria-selected",
          String(button.dataset.tab === selected)
        );
      });
      localStorage.setItem(ACTIVE_TAB_KEY, selected);
    }

    function initializeTabs() {
      const overview = element("tab-overview");
      overview.append(
        document.querySelector(".metadata"),
        element("status"),
        element("storage-mode-override")
      );
      movePanelContent("zendure-now", "overview");
      movePanelContent("price-timeline", "planning");
      movePanelContent("plan-explanation", "planning");
      movePanelContent("storage-energy-source-needs", "planning");
      movePanelContent("pv-energy-timeline", "planning");
      movePanelContent("household-load-forecast", "planning");
      movePanelContent("sources", "technical");
      movePanelContent("pipeline-health", "technical");
      movePanelContent("pipeline", "technical", false);
      document.querySelectorAll(".tab-button").forEach((button) => {
        button.addEventListener("click", () => activateTab(button.dataset.tab));
      });
      activateTab(localStorage.getItem(ACTIVE_TAB_KEY) ?? "overview");
    }

    function captureDashboardState() {
      const openStageCards = Array.from(
        document.querySelectorAll("details.stage-card")
      ).map((details) => details.open);
      const openTechnicalDetails = Array.from(
        document.querySelectorAll("details.technical-details")
      ).map((details) => details.open);
      const openPlanExplanationDetails = Object.fromEntries(
        Array.from(
          document.querySelectorAll("details.plan-explanation-detail")
        ).map((details) => [
          details.dataset.explanationKey,
          details.open
        ])
      );
      const scrollPositions = Array.from(
        document.querySelectorAll(
          ".timeline-panel, .price-chart-scroll, .energy-chart-scroll, " +
          ".technical-details pre"
        )
      ).map((node) => ({
        left: node.scrollLeft,
        top: node.scrollTop
      }));
      return {
        openStageCards,
        openTechnicalDetails,
        openPlanExplanationDetails,
        scrollPositions,
        windowScrollX: window.scrollX,
        windowScrollY: window.scrollY,
        selectedPriceDetail:
          document.querySelector(".price-detail")?.textContent ?? null,
        activeTab:
          document.querySelector(\'.tab-button[aria-selected="true"]\')
            ?.dataset.tab ?? "overview"
      };
    }

    function restoreDashboardState(state) {
      Array.from(
        document.querySelectorAll("details.stage-card")
      ).forEach((details, index) => {
        details.open = state.openStageCards[index] ?? false;
      });
      Array.from(
        document.querySelectorAll("details.technical-details")
      ).forEach((details, index) => {
        details.open = state.openTechnicalDetails[index] ?? false;
      });
      Array.from(
        document.querySelectorAll("details.plan-explanation-detail")
      ).forEach((details) => {
        details.open = Boolean(
          state.openPlanExplanationDetails?.[
            details.dataset.explanationKey
          ]
        );
      });
      Array.from(
        document.querySelectorAll(
          ".timeline-panel, .price-chart-scroll, .energy-chart-scroll, " +
          ".technical-details pre"
        )
      ).forEach((node, index) => {
        const position = state.scrollPositions[index];
        if (position) {
          node.scrollLeft = position.left;
          node.scrollTop = position.top;
        }
      });
      const priceDetail = document.querySelector(".price-detail");
      if (priceDetail && state.selectedPriceDetail) {
        priceDetail.textContent = state.selectedPriceDetail;
      }
      activateTab(state.activeTab ?? "overview");
      window.scrollTo(state.windowScrollX, state.windowScrollY);
    }

    function shouldDeferRenderForSelection() {
      const selection = window.getSelection();
      return Boolean(
        selection && !selection.isCollapsed && selection.toString()
      );
    }

    function renderView(view) {
      const dashboardState = captureDashboardState();
      element("version").textContent = displayValue(view.picot_version);
      element("run-id").textContent = displayValue(view.run_id);
      element("captured-at").textContent = displayValue(view.captured_at);
      const pipeline = Array.isArray(view.pipeline) ? view.pipeline : [];
      const planningInput = pipeline.find((item) => item.stage === 1);
      const candidateEngine = pipeline.find((item) => item.stage === 3);
      const primitiveBoundary = pipeline.find((item) => item.stage === 7);
      const execution = pipeline.find((item) => item.stage === 6);
      const observerOnly = execution?.attributes?.observer_only !== false;
      document.body.dataset.observerOnly = String(observerOnly);
      element("execution-mode").textContent = observerOnly
        ? "Alleen meekijken"
        : "Live uitvoering";
      const sources = planningInput?.attributes?.sources;
      renderSources(Array.isArray(sources) ? sources : []);
      renderPvForecastActualChart(
        planningInput?.attributes?.pv_interval_deviations ?? []
      );
      renderPriceTimeline(
        view.price_timeline ?? {
          available: false,
          display_hours: PRICE_DISPLAY_HOURS,
          display_starts_at: null,
          display_ends_at: null,
          market_timezone: "Europe/Amsterdam",
          planning_horizon_ends_at: null,
          points: [],
          opportunities: []
        },
        view.captured_at
      );
      renderPipeline(pipeline);
      renderPipelineHealth(view.pipeline_health);
      renderZendureNow(view.zendure_now);
      renderPlanExplanation(view.plan_explanation);
      renderStorageModeOverride(primitiveBoundary);
      renderStorageEnergySourceNeeds(
        candidateEngine?.attributes?.storage_source_needs ?? []
      );
      renderTimeline(view.pv_energy_timeline ?? {
        available: false,
        interval_count: 0,
        total_wh: 0,
        intervals: []
      });
      renderHouseholdLoadForecast(view.household_load_forecast ?? {
        available: false,
        forecast_id: null,
        interval_count: 0,
        total_wh: 0,
        average_confidence: 0,
        starts_at: null,
        ends_at: null,
        fallback_active: false,
        fallback_reason: null,
        intervals: []
      });
      restoreDashboardState(dashboardState);
    }

    function applyView(view) {
      const status = element("status");
      if (shouldDeferRenderForSelection()) {
        pendingView = view;
        status.dataset.state = "ready";
        status.textContent =
          "Realtime · nieuwe data wacht tot de selectie is afgerond";
        return;
      }
      pendingView = null;
      renderView(view);
      status.dataset.state = "ready";
      status.textContent = "Realtime verbonden";
    }

    async function loadView() {
      const status = element("status");
      try {
        const response = await fetch("api/view", { cache: "no-store" });
        if (response.status === 503) {
          status.dataset.state = "waiting";
          status.textContent = "Wachten op de eerste pipeline-run…";
          return false;
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        applyView(await response.json());
        return true;
      } catch (error) {
        status.dataset.state = "error";
        status.textContent = `Dashboarddata niet beschikbaar: ${error.message}`;
        return false;
      }
    }

    async function watchViewUpdates() {
      const status = element("status");
      while (!updateWatcherStopped) {
        try {
          const response = await fetch(
            `api/view/updates?revision=${viewRevision}`,
            { cache: "no-store" }
          );
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const update = await response.json();
          if (update.revision > viewRevision) {
            viewRevision = update.revision;
            applyView(update.view);
          }
        } catch (error) {
          status.dataset.state = "error";
          status.textContent =
            `Realtime verbinding verbroken: ${error.message}; opnieuw verbinden…`;
          await new Promise((resolve) => setTimeout(resolve, 5000));
        }
      }
    }

    document.addEventListener("selectionchange", () => {
      if (!shouldDeferRenderForSelection() && pendingView !== null) {
        const newestView = pendingView;
        pendingView = null;
        renderView(newestView);
      }
    });

    element("reset-storage-mode-override").addEventListener(
      "click",
      resetStorageModeOverride
    );
    initializeTabs();
    loadView().finally(watchViewUpdates);
    setInterval(loadView, 60000);
  </script>
</body>
</html>
"""


class WebViewStore:
    """Thread-safe in-memory store for the latest serialized web view."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._latest_json: str | None = None
        self._fast_grid_power_source: dict[str, object] | None = None
        self._revision = 0
        self._reset_storage_mode_override: (
            Callable[[str], dict[str, object]] | None
        ) = None

    def _overlay_fast_grid_power_source(
        self,
        view: dict[str, object],
    ) -> None:
        source = self._fast_grid_power_source
        pipeline = view.get("pipeline")
        if source is None or not isinstance(pipeline, list):
            return
        for item in pipeline:
            if not isinstance(item, dict) or item.get("stage") != 1:
                continue
            attributes = item.get("attributes")
            if not isinstance(attributes, dict):
                return
            sources = attributes.get("sources")
            if not isinstance(sources, list):
                return
            for index, candidate in enumerate(sources):
                if (
                    isinstance(candidate, dict)
                    and candidate.get("semantic_role") == "grid_power"
                ):
                    sources[index] = dict(source)
                    return

    def _replace_latest_locked(
        self,
        view: dict[str, object],
    ) -> None:
        self._overlay_fast_grid_power_source(view)
        self._latest_json = json.dumps(view, separators=(",", ":"))
        self._revision += 1
        self._condition.notify_all()

    def publish(self, view: dict[str, object]) -> None:
        """Serialize completely before atomically replacing the snapshot."""
        copied: object = json.loads(json.dumps(view))
        if not isinstance(copied, dict):
            raise TypeError("web view must serialize to an object")
        with self._condition:
            self._replace_latest_locked(copied)

    def publish_fast_grid_power_source(
        self,
        source: dict[str, object],
    ) -> None:
        """Overlay changed source evidence without running the Planner."""
        copied_source: object = json.loads(json.dumps(source))
        if not isinstance(copied_source, dict):
            raise TypeError("fast grid power source must be an object")
        with self._condition:
            self._fast_grid_power_source = copied_source
            if self._latest_json is None:
                return
            latest: object = json.loads(self._latest_json)
            if not isinstance(latest, dict):
                raise TypeError("latest web view must be an object")
            self._replace_latest_locked(latest)

    def latest_json(self) -> str | None:
        """Return the latest immutable JSON snapshot, when available."""
        with self._lock:
            return self._latest_json

    def wait_for_update(
        self,
        after_revision: int,
        *,
        timeout_seconds: float = 30.0,
    ) -> tuple[int, str | None]:
        """Wait until a newer immutable snapshot is published."""
        with self._condition:
            self._condition.wait_for(
                lambda: self._revision > after_revision,
                timeout=timeout_seconds,
            )
            return self._revision, self._latest_json

    def set_storage_mode_override_reset(
        self,
        reset: Callable[[str], dict[str, object]],
    ) -> None:
        """Register the one permitted observer-dashboard mutation."""
        with self._lock:
            self._reset_storage_mode_override = reset

    def storage_mode_override_reset(
        self,
    ) -> Callable[[str], dict[str, object]] | None:
        with self._lock:
            return self._reset_storage_mode_override


def create_web_server(
    store: WebViewStore,
    *,
    host: str,
    port: int,
    reset_storage_mode_override: (
        Callable[[str], dict[str, object]] | None
    ) = None,
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
            parsed_url = urlsplit(self.path)
            path = parsed_url.path
            if path == "/":
                self._send_html(HTTPStatus.OK, DASHBOARD_HTML)
                return

            if path == "/api/view/updates":
                query = parse_qs(parsed_url.query)
                try:
                    revision = int(query.get("revision", ["0"])[0])
                except ValueError:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        '{"status":"invalid_revision"}',
                    )
                    return
                current_revision, latest = store.wait_for_update(revision)
                if latest is None:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        '{"status":"waiting_for_first_run"}',
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    (
                        '{"revision":'
                        + str(current_revision)
                        + ',"view":'
                        + latest
                        + "}"
                    ),
                )
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
            path = urlsplit(self.path).path
            if path != "/api/storage-mode-override/reset":
                self._reject_write()
                return
            reset = (
                reset_storage_mode_override
                or store.storage_mode_override_reset()
            )
            if reset is None:
                self._send_json(
                    HTTPStatus.CONFLICT,
                    '{"status":"reset_rejected"}',
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4096:
                    raise ValueError("invalid body length")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("reset payload must be an object")
                reset_id = payload.get("reset_id")
                if (
                    not isinstance(reset_id, str)
                    or not reset_id.strip()
                ):
                    raise ValueError("reset_id is required")
            except (json.JSONDecodeError, TypeError, ValueError):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    '{"status":"invalid_reset_request"}',
                )
                return
            try:
                result = reset(reset_id)
            except ValueError:
                self._send_json(
                    HTTPStatus.CONFLICT,
                    '{"status":"reset_rejected"}',
                )
                return
            self._send_json(
                HTTPStatus.OK,
                json.dumps(result, separators=(",", ":")),
            )

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


def pipeline_result_nl(
    *,
    stage: int,
    state: str,
    attributes: Mapping[str, object],
) -> str:
    """Translate one technical stage outcome into deterministic Dutch."""
    if stage == 1:
        return "De planningsgegevens zijn compleet en klaar voor beoordeling."
    if stage == 2:
        count = _result_count(attributes, "opportunity_count")
        return f"Er zijn {count} mogelijke energiekansen gevonden."
    if stage == 3:
        count = _result_count(attributes, "candidate_count")
        return f"Er zijn {count} mogelijke plannen opgebouwd."
    if stage == 4:
        family = attributes.get("winning_family")
        if family == "pv_charge_only":
            return "Het beste plan is laden met verwachte zonne-energie."
        if family == "reserve_first":
            return "PicoT houdt de huidige Zendure-modus vast."
        winner = attributes.get("winning_candidate_id")
        if isinstance(winner, str) and winner.strip():
            return f"Het beste plan is {winner}."
        return "Er is nog geen beste plan gekozen."
    if stage == 5:
        count = _result_count(
            attributes,
            "plan_count" if "plan_count" in attributes else "execution_plan_count",
        )
        if count == 1:
            return "Er is 1 uitvoeringsplan voorbereid."
        return f"Er zijn {count} uitvoeringsplannen voorbereid."
    if stage == 6:
        if state == "live_plan_ready" or attributes.get("observer_only") is False:
            return "Het uitvoeringsplan is vrijgegeven voor live uitvoering."
        return "Uitvoering is niet gestart; PicoT kijkt alleen mee."
    if stage == 7:
        blockers = attributes.get("blockers")
        if (
            isinstance(blockers, (list, tuple))
            and "manual_override_active" in blockers
        ):
            return (
                "Uitvoering is geblokkeerd omdat een handmatige "
                "instelling actief is."
            )
        normal_result = attributes.get("normal_result")
        if isinstance(normal_result, str) and normal_result.strip():
            return normal_result
        if state == "request_ready":
            return "De uitvoerbare opdracht is vrijgegeven voor Zendure."
        return "Er is nu geen uitvoerbare opdracht voor Zendure."
    if stage == 8:
        normal_result = attributes.get("normal_result")
        if isinstance(normal_result, str) and normal_result.strip():
            return normal_result
        return "De apparaatkoppeling is niet aangeroepen."
    if stage == 9:
        normal_result = attributes.get("normal_result")
        if isinstance(normal_result, str) and normal_result.strip():
            return normal_result
        return "Er is geen opdracht naar Zendure verstuurd."
    if stage == 10:
        normal_result = attributes.get("normal_result")
        if isinstance(normal_result, str) and normal_result.strip():
            return normal_result
    return f"Deze stap heeft de status {state.replace('_', ' ')}."


def pipeline_stage_health(
    *,
    stage: int,
    state: str,
    attributes: Mapping[str, object],
) -> str:
    """Classify technical health independently from a valid no-op outcome."""
    del stage
    unhealthy_markers = ("error", "failed", "invalid", "unavailable", "rejected")
    normalized_state = state.casefold()
    if any(marker in normalized_state for marker in unhealthy_markers):
        return "fault"
    error = attributes.get("error")
    if error is not None and error != "" and error != "—":
        return "fault"
    blockers = attributes.get("blockers")
    fault_blockers = {
        "primitive_vendor_mapping_unavailable",
        "manual_override_provenance_unverified",
    }
    if isinstance(blockers, (list, tuple)) and fault_blockers.intersection(blockers):
        return "fault"
    sources = attributes.get("sources")
    if isinstance(sources, (list, tuple)):
        for source in sources:
            if not isinstance(source, dict):
                continue
            if source.get("availability") == "unavailable" or source.get("error"):
                return "fault"
    return "healthy"


def _zendure_now(pipeline: list[dict[str, object]]) -> dict[str, object]:
    primitive = next(item for item in pipeline if item["stage"] == 7)
    vendor = next(item for item in pipeline if item["stage"] == 9)
    primitive_attributes = primitive["attributes"]
    vendor_attributes = vendor["attributes"]
    assert isinstance(primitive_attributes, dict)
    assert isinstance(vendor_attributes, dict)
    provenance = primitive_attributes.get("mode_provenance_status")
    manual_override = primitive_attributes.get("manual_override_active") is True
    origin = (
        "manual"
        if manual_override or provenance == "manual_override"
        else "picot"
        if provenance == "planner_owned"
        else "unknown"
    )
    set_at = (
        primitive_attributes.get("mode_observed_at")
        if origin == "manual"
        else primitive_attributes.get("last_planner_applied_at")
    )
    return {
        "active_mode": primitive_attributes.get("current_vendor_mode"),
        "planned_mode": primitive_attributes.get("planned_vendor_mode"),
        "origin": origin,
        "observed_at": primitive_attributes.get("mode_observed_at"),
        "set_at": set_at,
        "last_result_nl": vendor.get("result_nl"),
        "last_result_status": vendor.get("state"),
    }


def _result_count(
    attributes: Mapping[str, object],
    key: str,
) -> int:
    value = attributes.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _number_nl(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _period_nl(starts_at: object, ends_at: object) -> str:
    if not hasattr(starts_at, "astimezone") or not hasattr(ends_at, "astimezone"):
        return "Tijdvak onbekend"
    timezone = ZoneInfo("Europe/Amsterdam")
    start = starts_at.astimezone(timezone)
    end = ends_at.astimezone(timezone)
    return (
        f"{start:%d-%m-%Y %H:%M} tot "
        f"{end:%d-%m-%Y %H:%M}"
    )


def _opportunity_label(kind: str) -> tuple[str, str]:
    labels = {
        "NEGATIVE_PRICE_WINDOW": (
            "Negatieve prijs",
            "stroom afnemen kost in dit tijdvak minder dan niets",
        ),
        "LOWEST_PRICE_WINDOW": (
            "Lage prijs",
            "dit behoort tot de goedkoopste tijdvakken",
        ),
        "HIGH_EXPORT_VALUE_WINDOW": (
            "Hoge terugleverwaarde",
            "terugleveren levert in dit tijdvak relatief veel op",
        ),
    }
    return labels.get(kind, ("Andere energiekans", "dit tijdvak wijkt gunstig af"))


def _build_plan_explanation(run: CanonicalPipelineRun) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = {}
    group_reasons: dict[str, str] = {}
    for opportunity in run.opportunities.opportunities:
        label, reason = _opportunity_label(opportunity.kind)
        group_reasons[label] = reason
        period = _period_nl(opportunity.starts_at, opportunity.ends_at)
        price = _number_nl(opportunity.metrics.average_price_eur_per_kwh, 3)
        confidence = round(opportunity.confidence * 100)
        grouped.setdefault(label, []).append(
            {
                "period_nl": period,
                "price_nl": f"Gemiddelde prijs € {price}/kWh",
                "confidence_nl": f"Zekerheid {confidence}%",
                "reason_nl": reason.capitalize() + ".",
                "summary_nl": (
                    f"{period}: € {price}/kWh, zekerheid {confidence}%. "
                    f"Relevant omdat {reason}."
                ),
            }
        )
    opportunity_groups = [
        {
            "label_nl": label,
            "count": len(items),
            "summary_nl": (
                f"{len(items)}× {label.lower()}: {group_reasons[label]}."
            ),
            "items": items,
        }
        for label, items in sorted(grouped.items())
    ]

    outcomes_by_candidate = {
        outcome.candidate_id: outcome for outcome in run.outcomes.outcomes
    }
    paths_by_id = {
        path.path_id: path for path in run.candidate_set.energy_paths
    }
    pv_candidate_count = sum(
        candidate.family == "pv_charge_only"
        for candidate in run.candidate_set.candidates
    )
    local_capture_date = run.planning_input.captured_at.astimezone(
        ZoneInfo("Europe/Amsterdam")
    ).date()
    plans: list[dict[str, object]] = []
    winning_confidence = 0.0
    for candidate in run.candidate_set.candidates:
        selected = candidate.candidate_id == run.evaluation.winning_candidate_id
        outcome = outcomes_by_candidate.get(candidate.candidate_id)
        path = paths_by_id[candidate.energy_path_id]
        if candidate.family == "pv_charge_only" and outcome is not None:
            local_timezone = ZoneInfo("Europe/Amsterdam")
            segments_by_date: dict[date, list[PathSegment]] = {}
            for segment in path.segments:
                segment_date = segment.starts_at.astimezone(
                    local_timezone
                ).date()
                segments_by_date.setdefault(segment_date, []).append(segment)
            phase_dates = tuple(segments_by_date)
            phases: list[dict[str, object]] = []
            for phase_index, phase_date in enumerate(phase_dates):
                phase_segments = segments_by_date[phase_date]
                phase_start = min(
                    segment.starts_at for segment in phase_segments
                )
                phase_end = max(segment.ends_at for segment in phase_segments)
                if phase_date == local_capture_date:
                    phase_label = (
                        "Nu laden met PV"
                        if phase_start <= run.planning_input.captured_at
                        else "Vandaag laden met PV"
                    )
                elif phase_date == local_capture_date + timedelta(days=1):
                    phase_label = (
                        "Morgen aanvullen met PV"
                        if phase_index > 0
                        else "Morgen laden met PV"
                    )
                else:
                    phase_label = f"{phase_date:%d-%m} laden met PV"
                phase_period = _period_nl(phase_start, phase_end)
                phases.append(
                    {
                        "label_nl": phase_label,
                        "period_nl": phase_period,
                        "summary_nl": f"{phase_label}: {phase_period}",
                        "segment_count": len(phase_segments),
                    }
                )
            window_date = outcome.charge_window_starts_at.astimezone(
                local_timezone
            ).date()
            day_prefix = ""
            if pv_candidate_count > 1:
                if window_date == local_capture_date:
                    day_prefix = "Vandaag "
                elif window_date == local_capture_date + timedelta(days=1):
                    day_prefix = "Morgen "
                else:
                    day_prefix = f"{window_date:%d-%m} "
            label = (
                f"{day_prefix}laden met verwachte zonne-energie"
                if day_prefix
                else "Laden met verwachte zonne-energie"
            )
            if (
                local_capture_date in phase_dates
                and local_capture_date + timedelta(days=1) in phase_dates
            ):
                label = (
                    "Vandaag en morgen laden met verwachte zonne-energie"
                )
            period = _period_nl(
                outcome.charge_window_starts_at,
                outcome.charge_window_ends_at,
            )
            energy = (
                "Verwachte toevoeging aan batterij: "
                f"{_number_nl(outcome.pv_storage_contribution_wh / 1000)} kWh"
            )
            grid_energy = (
                "Verwacht netladen: "
                f"{_number_nl(outcome.grid_storage_contribution_wh / 1000)} kWh"
            )
            remaining_to_target_kwh = max(
                0.0,
                outcome.required_energy_wh
                - outcome.storage_energy_at_requirement_wh,
            ) / 1000
            reason = (
                (
                    "Gekozen omdat het batterijdoel met verwachte PV en zonder "
                    "netladen wordt gehaald."
                    if outcome.requirement_satisfied
                    else (
                        "Gekozen omdat dit plan zoveel mogelijk verwachte PV "
                        "opslaat zonder netladen; het batterijdoel blijft naar "
                        "verwachting "
                        f"{_number_nl(remaining_to_target_kwh)} "
                        "kWh tekort."
                    )
                )
                if selected
                else "Niet gekozen omdat een ander plan beter scoort."
            )
            if selected:
                winning_confidence = outcome.confidence
        else:
            phases = []
            label = "Niets extra doen"
            requirement = (
                run.candidate_set.storage_requirements[0]
                if run.candidate_set.storage_requirements
                else None
            )
            period = _period_nl(
                run.planning_input.captured_at,
                (
                    requirement.required_by
                    if requirement is not None
                    else run.planning_input.horizon_end
                ),
            )
            energy = "Verwachte toevoeging aan batterij: 0,00 kWh"
            grid_energy = "Verwacht netladen: 0,00 kWh"
            reason = (
                "Gekozen omdat extra laden niet nodig is."
                if selected
                else "Niet gekozen omdat dit het geplande batterijdoel niet haalt."
            )
            if selected:
                winning_confidence = min(
                    (state.confidence for state in run.planning_input.current_storage_states),
                    default=0.0,
                )
        plans.append(
            {
                "key": candidate.candidate_id,
                "family": candidate.family,
                "label_nl": label,
                "selected": selected,
                "period_nl": period,
                "energy_nl": energy,
                "grid_energy_nl": grid_energy,
                "reason_nl": reason,
                "phases": phases,
                "segment_count": len(path.segments),
            }
        )

    winning_family = next(
        (
            candidate.family
            for candidate in run.candidate_set.candidates
            if candidate.candidate_id == run.evaluation.winning_candidate_id
        ),
        None,
    )
    if winning_family == "pv_charge_only":
        decision_summary = "PicoT kiest laden met verwachte zonne-energie."
        winning_outcome = (
            outcomes_by_candidate.get(run.evaluation.winning_candidate_id)
            if run.evaluation.winning_candidate_id is not None
            else None
        )
        decision_reason = (
            "Dit plan haalt het batterijdoel met verwachte PV en zonder netladen."
            if winning_outcome is not None
            and winning_outcome.requirement_satisfied
            else (
                "Dit plan slaat zoveel mogelijk verwachte PV op zonder netladen; "
                "het volledige batterijdoel is binnen de deadline niet haalbaar."
            )
        )
    elif winning_family == "reserve_first":
        decision_summary = "PicoT kiest niets extra doen."
        decision_reason = "Het batterijdoel is zonder aanvullende laadactie haalbaar."
    else:
        decision_summary = "PicoT heeft nog geen uitvoerbaar plan gekozen."
        decision_reason = "De benodigde gegevens of mogelijkheden ontbreken nog."

    blockers = list(run.primitive_boundary.blockers)
    confidence_percent = round(winning_confidence * 100)
    if confidence_percent == 0:
        blockers.append("planning_confidence_below_minimum")
    return {
        "title": "Wat PicoT overweegt",
        "opportunity_count": len(run.opportunities.opportunities),
        "opportunity_groups": opportunity_groups,
        "plans": plans,
        "decision": {
            "summary_nl": decision_summary,
            "reason_nl": decision_reason,
        },
        "readiness": {
            "confidence_percent": confidence_percent,
            "status": "blocked" if confidence_percent == 0 else "observer_only",
            "warning_nl": (
                "De planningszekerheid is 0%; PicoT voert dit plan niet uit."
                if confidence_percent == 0
                else None
            ),
            "blockers": list(dict.fromkeys(blockers)),
        },
    }


def build_web_view(
    run: CanonicalPipelineRun,
    projection: Projection,
    *,
    display_price_points: tuple[PriceForecastPoint, ...] | None = None,
) -> dict[str, object]:
    """Build one JSON-serializable observer view without side effects."""
    planning_input = run.planning_input
    timeline = planning_input.pv_energy_timeline
    household_forecast = planning_input.household_load_forecast
    household_intervals = (
        household_forecast.intervals
        if household_forecast is not None
        else ()
    )
    market_timezone = ZoneInfo("Europe/Amsterdam")
    display_starts_at = planning_input.captured_at.astimezone(
        market_timezone
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    display_ends_at = display_starts_at + timedelta(days=2)
    selected_display_price_points = (
        planning_input.price_points
        if display_price_points is None
        else display_price_points
    )
    price_points = tuple(
        sorted(
            selected_display_price_points,
            key=lambda point: (
                point.starts_at,
                point.ends_at,
                point.point_id,
            ),
        )
    )
    price_opportunities = run.opportunities.opportunities
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
            "result_nl": pipeline_result_nl(
                stage=stage,
                state=card.state,
                attributes=card.attributes,
            ),
            "health": pipeline_stage_health(
                stage=stage,
                state=card.state,
                attributes=card.attributes,
            ),
        }
        for stage, card in enumerate(projection.cards, start=1)
    ]
    healthy_count = sum(item["health"] == "healthy" for item in pipeline)
    pipeline_health = {
        "healthy": healthy_count == len(pipeline),
        "healthy_count": healthy_count,
        "total_count": len(pipeline),
        "summary_nl": (
            f"Pipeline werkt correct – {healthy_count}/{len(pipeline)} groen."
            if healthy_count == len(pipeline)
            else (
                "Pipeline heeft een probleem – "
                f"{len(pipeline) - healthy_count} stap(pen) rood."
            )
        ),
    }
    execution_attributes = pipeline[5]["attributes"]
    assert isinstance(execution_attributes, dict)
    observer_only = execution_attributes.get("observer_only", True)
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

    household_load_forecast: dict[str, object] = {
        "available": household_forecast is not None,
        "forecast_id": (
            household_forecast.forecast_id
            if household_forecast is not None
            else None
        ),
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "interval_count": len(household_intervals),
        "total_wh": sum(
            interval.expected_energy_wh
            for interval in household_intervals
        ),
        "average_confidence": (
            sum(
                interval.confidence
                for interval in household_intervals
            )
            / len(household_intervals)
            if household_intervals
            else 0.0
        ),
        "starts_at": (
            household_intervals[0].starts_at.isoformat()
            if household_intervals
            else None
        ),
        "ends_at": (
            household_intervals[-1].ends_at.isoformat()
            if household_intervals
            else None
        ),
        "fallback_active": (
            household_forecast.fallback_active
            if household_forecast is not None
            else False
        ),
        "fallback_reason": (
            household_forecast.fallback_reason
            if household_forecast is not None
            else None
        ),
        "intervals": [
            {
                "interval_id": interval.interval_id,
                "starts_at": interval.starts_at.isoformat(),
                "ends_at": interval.ends_at.isoformat(),
                "expected_energy_wh": interval.expected_energy_wh,
                "confidence": interval.confidence,
                "source_reference": interval.source_reference,
                "method_version": interval.method_version,
            }
            for interval in household_intervals
        ],
    }

    price_timeline: dict[str, object] = {
        "available": bool(price_points),
        "display_hours": 48,
        "display_starts_at": display_starts_at.isoformat(),
        "display_ends_at": display_ends_at.isoformat(),
        "market_timezone": "Europe/Amsterdam",
        "planning_horizon_ends_at": (
            planning_input.horizon_end.isoformat()
            if planning_input.horizon_end is not None
            else None
        ),
        "points": [
            {
                "point_id": point.point_id,
                "starts_at": point.starts_at.isoformat(),
                "ends_at": point.ends_at.isoformat(),
                "value_eur_per_kwh": point.value_eur_per_kwh,
                "confidence": point.confidence,
                "evidence_id": point.evidence_id,
            }
            for point in price_points
        ],
        "opportunities": [
            {
                "opportunity_id": opportunity.opportunity_id,
                "kind": opportunity.kind,
                "starts_at": opportunity.starts_at.isoformat(),
                "ends_at": opportunity.ends_at.isoformat(),
                "confidence": opportunity.confidence,
                "lifecycle_status": opportunity.lifecycle_status,
                "metrics": {
                    "duration_seconds": (
                        opportunity.metrics.duration_seconds
                    ),
                    "average_price_eur_per_kwh": (
                        opportunity.metrics.average_price_eur_per_kwh
                    ),
                    "minimum_price_eur_per_kwh": (
                        opportunity.metrics.minimum_price_eur_per_kwh
                    ),
                    "maximum_price_eur_per_kwh": (
                        opportunity.metrics.maximum_price_eur_per_kwh
                    ),
                    "boundary_eur_per_kwh": (
                        opportunity.metrics.boundary_eur_per_kwh
                    ),
                },
            }
            for opportunity in price_opportunities
        ],
    }

    return {
        "schema_version": 1,
        "observer_only": observer_only,
        "picot_version": planning_input.picot_version,
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "captured_at": planning_input.captured_at.isoformat(),
        "pipeline": pipeline,
        "pipeline_health": pipeline_health,
        "zendure_now": _zendure_now(pipeline),
        "plan_explanation": _build_plan_explanation(run),
        "price_timeline": price_timeline,
        "pv_energy_timeline": pv_energy_timeline,
        "household_load_forecast": household_load_forecast,
    }
