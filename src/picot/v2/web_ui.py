"""Pure read-only data projection for the PicoT v2 web UI."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

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
    .metric, .source-card, .stage-card, .timeline-panel, .price-panel {
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
    .stage-card > summary { cursor: pointer; list-style-position: inside; }
    .stage-summary h3 { display: inline; margin-right: 10px; }
    .stage-result { margin: 12px 0; color: #d9e4ef; }
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

    <h2>Pipeline ①→⑨</h2>
    <section id="pipeline" class="pipeline" aria-live="polite"></section>

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
    const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
    const PRICE_DISPLAY_HOURS = 48;
    let pendingView = null;

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

    function formatEnergyKwh(valueWh) {
      const numeric = Number(valueWh);
      return Number.isFinite(numeric)
        ? new Intl.NumberFormat(
            "nl-NL",
            { minimumFractionDigits: 2, maximumFractionDigits: 2 }
          ).format(numeric / 1000) + " kWh"
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
        const details = document.createElement("details");
        details.className = "stage-card";

        const summary = document.createElement("summary");
        summary.className = "stage-summary";

        const heading = document.createElement("h3");
        heading.textContent = `${item.stage}. ${stageNames[item.stage - 1] ?? "Pipeline stage"}`;

        const state = document.createElement("span");
        state.className = "stage-state";
        state.textContent = displayValue(item.state);
        summary.append(heading, state);
        details.appendChild(summary);

        const result = document.createElement("p");
        result.className = "stage-result";
        result.textContent = item.result_nl;
        details.appendChild(result);

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

    async function resetStorageModeOverride() {
      const resetButton = element("reset-storage-mode-override");
      resetButton.disabled = true;
      try {
        const response = await fetch("api/storage-mode-override/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reset_id: crypto.randomUUID() })
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

    function captureDashboardState() {
      const openStageCards = Array.from(
        document.querySelectorAll("details.stage-card")
      ).map((details) => details.open);
      const openTechnicalDetails = Array.from(
        document.querySelectorAll("details.technical-details")
      ).map((details) => details.open);
      const scrollPositions = Array.from(
        document.querySelectorAll(
          ".timeline-panel, .price-chart-scroll, .technical-details pre"
        )
      ).map((node) => ({
        left: node.scrollLeft,
        top: node.scrollTop
      }));
      return {
        openStageCards,
        openTechnicalDetails,
        scrollPositions,
        windowScrollX: window.scrollX,
        windowScrollY: window.scrollY,
        selectedPriceDetail:
          document.querySelector(".price-detail")?.textContent ?? null
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
        document.querySelectorAll(
          ".timeline-panel, .price-chart-scroll, .technical-details pre"
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
      const sources = planningInput?.attributes?.sources;
      renderSources(Array.isArray(sources) ? sources : []);
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
        if (shouldDeferRenderForSelection()) {
          pendingView = view;
          status.dataset.state = "ready";
          status.textContent =
            "Live · nieuwe data wacht tot de selectie is afgerond";
          return;
        }
        pendingView = null;
        renderView(view);
        status.dataset.state = "ready";
        status.textContent = "Live · automatisch ververst iedere 5 seconden";
      } catch (error) {
        status.dataset.state = "error";
        status.textContent = `Dashboarddata niet beschikbaar: ${error.message}`;
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
        self._reset_storage_mode_override: (
            Callable[[str], dict[str, object]] | None
        ) = None

    def publish(self, view: dict[str, object]) -> None:
        """Serialize completely before atomically replacing the snapshot."""
        serialized = json.dumps(view, separators=(",", ":"))
        with self._lock:
            self._latest_json = serialized

    def latest_json(self) -> str | None:
        """Return the latest immutable JSON snapshot, when available."""
        with self._lock:
            return self._latest_json

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
        winner = attributes.get("winning_candidate_id")
        if isinstance(winner, str) and winner.strip():
            return f"Het beste plan is {winner}."
        return "Er is nog geen beste plan gekozen."
    if stage == 5:
        count = _result_count(attributes, "execution_plan_count")
        if count == 1:
            return "Er is 1 uitvoeringsplan voorbereid."
        return f"Er zijn {count} uitvoeringsplannen voorbereid."
    if stage == 6:
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
        return "Uitvoering blijft geblokkeerd zolang PicoT alleen meekijkt."
    if stage == 8:
        return "De apparaatkoppeling is niet aangeroepen."
    if stage == 9:
        return "Er is geen opdracht naar Zendure verstuurd."
    return f"Deze stap heeft de status {state.replace('_', ' ')}."


def _result_count(
    attributes: Mapping[str, object],
    key: str,
) -> int:
    value = attributes.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


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
        "observer_only": True,
        "picot_version": planning_input.picot_version,
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "captured_at": planning_input.captured_at.isoformat(),
        "pipeline": pipeline,
        "price_timeline": price_timeline,
        "pv_energy_timeline": pv_energy_timeline,
        "household_load_forecast": household_load_forecast,
    }
