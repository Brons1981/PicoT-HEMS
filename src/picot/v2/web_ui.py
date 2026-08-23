"""Pure read-only data projection for the PicoT v2 web UI."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Condition, Lock
from typing import TypedDict
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from picot.domain.energy_path import PathSegment
from picot.v2.contracts import CanonicalPipelineRun, PriceForecastPoint
from picot.v2.diagnostic_downloads import diagnostic_zip, incident_overview
from picot.v2.power_history import PowerHistorySeries, PowerHistorySnapshot
from picot.v2.projection import Projection
from picot.v2.storage_mode_transition_history import StorageModeTransitionEvent

POWER_HISTORY_DISPLAY_INTERVAL = timedelta(minutes=5)
SELF_CONSUMPTION_DISPLAY_INTERVAL = timedelta(minutes=10)
PV_ACTUAL_DISPLAY_INTERVAL = timedelta(minutes=2)


class _DisplayPowerPoint(TypedDict):
    sampled_at: str
    power_w: float
    coverage_ratio: float
    derived_from_evidence_ids: list[str]


def _power_history_display_points(
    series: PowerHistorySeries,
    *,
    starts_at: datetime,
    ends_at: datetime,
    interval: timedelta = POWER_HISTORY_DISPLAY_INTERVAL,
) -> list[_DisplayPowerPoint]:
    """Derive factual bucket averages in one pass without changing raw evidence."""
    points = tuple(sorted(series.points, key=lambda item: item.sampled_at))
    result: list[_DisplayPowerPoint] = []
    point_index = 0
    held_point = None
    bucket_start = starts_at
    while bucket_start < ends_at:
        bucket_end = min(bucket_start + interval, ends_at)
        evidence_ids: tuple[str, ...]
        covered_seconds: float
        average: float | None
        if series.history_semantics == "state_hold":
            while (
                point_index < len(points)
                and points[point_index].sampled_at <= bucket_start
            ):
                held_point = points[point_index]
                point_index += 1
            current = held_point
            cursor = bucket_start if current is not None else None
            weighted_power_seconds = 0.0
            covered_seconds = 0.0
            used_evidence: list[str] = []
            if current is not None:
                used_evidence.append(current.evidence_id)
            while (
                point_index < len(points)
                and points[point_index].sampled_at < bucket_end
            ):
                transition = points[point_index]
                if current is not None and cursor is not None:
                    duration = (transition.sampled_at - cursor).total_seconds()
                    weighted_power_seconds += current.power_w * duration
                    covered_seconds += duration
                current = transition
                held_point = transition
                cursor = transition.sampled_at
                used_evidence.append(transition.evidence_id)
                point_index += 1
            if current is not None and cursor is not None:
                duration = (bucket_end - cursor).total_seconds()
                weighted_power_seconds += current.power_w * duration
                covered_seconds += duration
            average = (
                weighted_power_seconds / covered_seconds
                if covered_seconds > 0
                else None
            )
            evidence_ids = tuple(dict.fromkeys(used_evidence))
        else:
            while (
                point_index < len(points)
                and points[point_index].sampled_at < bucket_start
            ):
                point_index += 1
            bucket_points = []
            while (
                point_index < len(points)
                and points[point_index].sampled_at < bucket_end
            ):
                bucket_points.append(points[point_index])
                point_index += 1
            covered_seconds = (bucket_end - bucket_start).total_seconds()
            average = (
                sum(point.power_w for point in bucket_points) / len(bucket_points)
                if bucket_points
                else None
            )
            evidence_ids = tuple(point.evidence_id for point in bucket_points)
        if average is not None:
            bucket_seconds = (bucket_end - bucket_start).total_seconds()
            result.append({
                "sampled_at": (
                    bucket_start + (bucket_end - bucket_start) / 2
                ).isoformat(),
                "power_w": average,
                "coverage_ratio": min(1.0, covered_seconds / bucket_seconds),
                "derived_from_evidence_ids": list(evidence_ids),
            })
        bucket_start = bucket_end
    return result


def _self_consumption_history_view(
    power_history: PowerHistorySnapshot | None,
) -> dict[str, object]:
    """Derive the Dutch PV self-consumption view from canonical flows."""
    if power_history is None:
        return {
            "available": False,
            "status": "unavailable",
            "error": None,
            "starts_at": None,
            "ends_at": None,
            "display_interval_seconds": 600,
            "definition": "clamp(pv_generation_w-grid_export_w,0,pv_generation_w)",
            "current_values": {},
            "series": [],
        }

    by_role = {series.role: series for series in power_history.series}
    missing_roles = [
        role
        for role in ("pv_generation", "grid_export", "grid_import")
        if role not in by_role or not by_role[role].points
    ]
    if power_history.status != "available" or missing_roles:
        return {
            "available": False,
            "status": power_history.status,
            "error": (
                "missing_roles:" + ",".join(missing_roles)
                if missing_roles
                else power_history.error
            ),
            "starts_at": power_history.starts_at.isoformat(),
            "ends_at": power_history.ends_at.isoformat(),
            "display_interval_seconds": 600,
            "definition": "clamp(pv_generation_w-grid_export_w,0,pv_generation_w)",
            "current_values": {},
            "series": [],
        }

    display_by_role = {
        role: _power_history_display_points(
            by_role[role],
            starts_at=power_history.starts_at,
            ends_at=power_history.ends_at,
            interval=SELF_CONSUMPTION_DISPLAY_INTERVAL,
        )
        for role in ("pv_generation", "grid_export", "grid_import")
    }
    pv_by_time = {
        point["sampled_at"]: point
        for point in display_by_role["pv_generation"]
    }
    export_by_time = {
        point["sampled_at"]: point
        for point in display_by_role["grid_export"]
    }
    local_pv_points: list[_DisplayPowerPoint] = []
    for sampled_at, pv_point in pv_by_time.items():
        export_point = export_by_time.get(sampled_at)
        if export_point is None:
            continue
        pv_power_w = max(0.0, pv_point["power_w"])
        grid_export_w = max(0.0, export_point["power_w"])
        local_pv_points.append({
            "sampled_at": sampled_at,
            "power_w": min(pv_power_w, max(0.0, pv_power_w - grid_export_w)),
            "coverage_ratio": min(
                pv_point["coverage_ratio"],
                export_point["coverage_ratio"],
            ),
            "derived_from_evidence_ids": list(dict.fromkeys([
                *pv_point["derived_from_evidence_ids"],
                *export_point["derived_from_evidence_ids"],
            ])),
        })

    current_pv_w = max(0.0, by_role["pv_generation"].points[-1].power_w)
    current_export_w = max(0.0, by_role["grid_export"].points[-1].power_w)
    current_import_w = max(0.0, by_role["grid_import"].points[-1].power_w)

    return {
        "available": bool(local_pv_points),
        "status": "available" if local_pv_points else "empty",
        "error": None,
        "starts_at": power_history.starts_at.isoformat(),
        "ends_at": power_history.ends_at.isoformat(),
        "display_interval_seconds": int(
            SELF_CONSUMPTION_DISPLAY_INTERVAL.total_seconds()
        ),
        "definition": "clamp(pv_generation_w-grid_export_w,0,pv_generation_w)",
        "current_values": {
            "pv_generation": current_pv_w,
            "local_pv_use": min(
                current_pv_w,
                max(0.0, current_pv_w - current_export_w),
            ),
            "grid_import": current_import_w,
        },
        "series": [
            {
                "series_id": "pv_generation_total",
                "role": "pv_generation",
                "points": display_by_role["pv_generation"],
            },
            {
                "series_id": "local_pv_use",
                "role": "local_pv_use",
                "points": local_pv_points,
            },
            {
                "series_id": "grid_import_positive",
                "role": "grid_import",
                "points": display_by_role["grid_import"],
            },
        ],
    }


def _power_history_view(
    power_history: PowerHistorySnapshot | None,
) -> dict[str, object]:
    """Serialize canonical power history independently from a Planner Run."""

    starts_at = power_history.starts_at if power_history is not None else None
    ends_at = power_history.ends_at if power_history is not None else None
    return {
        "available": power_history is not None
        and power_history.status == "available",
        "status": power_history.status if power_history is not None else "unavailable",
        "error": power_history.error if power_history is not None else None,
        "starts_at": starts_at.isoformat() if starts_at is not None else None,
        "ends_at": ends_at.isoformat() if ends_at is not None else None,
        "method_version": (
            power_history.method_version if power_history is not None else None
        ),
        "display_aggregation": "five_minute_average",
        "display_interval_seconds": int(
            POWER_HISTORY_DISPLAY_INTERVAL.total_seconds()
        ),
        "display_curve": "linear_between_bucket_averages",
        "pv_actual_display_interval_seconds": int(
            PV_ACTUAL_DISPLAY_INTERVAL.total_seconds()
        ),
        "pv_actual_display_points": next((
            _power_history_display_points(
                series,
                starts_at=starts_at,
                ends_at=ends_at,
                interval=PV_ACTUAL_DISPLAY_INTERVAL,
            )
            for series in power_history.series
            if series.role == "pv_generation"
        ), [])
        if power_history is not None
        and starts_at is not None
        and ends_at is not None
        else [],
        "series": [
            {
                "series_id": series.series_id,
                "role": series.role,
                "source_entity_id": series.source_entity_id,
                "transform": series.transform,
                "history_semantics": series.history_semantics,
                "display_method": (
                    "time_weighted_average"
                    if series.history_semantics == "state_hold"
                    else "sample_average"
                ),
                "display_points": _power_history_display_points(
                    series,
                    starts_at=starts_at,
                    ends_at=ends_at,
                )
                if starts_at is not None and ends_at is not None
                else [],
                "points": [
                    {
                        "sampled_at": point.sampled_at.isoformat(),
                        "power_w": point.power_w,
                        "evidence_id": point.evidence_id,
                    }
                    for point in series.points
                ],
            }
            for series in (power_history.series if power_history is not None else ())
        ],
    }


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
    .daily-comparison-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .daily-comparison-card {
      min-width: 0;
      padding: 14px;
      border: 1px solid #386f96;
      border-radius: 12px;
      background: #10283a;
    }
    .daily-comparison-card.daily-reference {
      border-color: #a855f7;
      background: #251337;
      box-shadow: inset 4px 0 0 #c084fc;
    }
    .daily-reference-label { color: #d8b4fe; }
    .daily-lineage-warning { color: #ffd77a; }
    @media (max-width: 800px) {
      .daily-comparison-grid { grid-template-columns: 1fr; }
    }
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
      fill: #ff9800;
      opacity: 0.24;
    }
    .energy-chart .forecast-line {
      fill: none;
      stroke: #ff9800;
      stroke-width: 0.1;
    }
    .energy-chart .actual-line {
      fill: none;
      stroke: #ffd600;
      stroke-width: 1;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .power-flow-line {
      fill: none;
      stroke-width: 1.2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .power-flow-line.pv_generation { stroke: #ffd400; }
    .power-flow-line.household_load { stroke: #3994e6; }
    .power-flow-line.grid_import { stroke: #ef4444; }
    .power-flow-line.grid_export { stroke: #aab2bd; stroke-width: 0.45; }
    .power-flow-line.battery_charge,
    .power-flow-line.battery_discharge { stroke: #35a862; }
    .power-flow-area { stroke: none; opacity: 0.14; }
    .power-flow-area.grid_export { fill: #aab2bd; opacity: 0.24; }
    .power-flow-area.battery_charge { fill: #35a862; }
    .self-consumption-area.pv_generation { fill: #ffd600; opacity: 0.22; }
    .self-consumption-area.local_pv_use { fill: #2196f3; opacity: 0.80; }
    .self-consumption-area.grid_import { fill: #d32f2f; opacity: 0.38; }
    .self-consumption-line {
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .self-consumption-line.pv_generation { stroke: #ffd600; stroke-width: 2; }
    .self-consumption-line.local_pv_use { stroke: #2196f3; stroke-width: 2; }
    .self-consumption-line.grid_import { stroke: #d32f2f; stroke-width: 1.5; }
    .power-zero-line { stroke: #96a6b8; stroke-width: 1.5; }
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
    button.energy-chart-key {
      border: 1px solid #334155;
      border-radius: 999px;
      background: #111923;
      color: #96a6b8;
      padding: 5px 9px;
      cursor: pointer;
    }
    button.energy-chart-key[aria-pressed="false"] { opacity: 0.42; }
    .energy-chart-selection-action {
      border: 0;
      background: transparent;
      color: #62b8f5;
      cursor: pointer;
      padding: 5px 2px;
    }
    .power-current-values {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 8px;
      margin: 2px 0 10px;
    }
    .power-current-value { color: #96a6b8; font-size: 0.76rem; }
    .power-current-value strong {
      display: block;
      margin-top: 2px;
      font-size: 1rem;
    }
    .power-chart-toolbar {
      display: flex;
      justify-content: flex-end;
      gap: 6px;
      margin-bottom: 4px;
    }
    .power-chart-toolbar button {
      min-width: 30px;
      border: 1px solid #334155;
      border-radius: 6px;
      background: #111923;
      color: #b9c8d8;
      padding: 4px 8px;
      cursor: pointer;
    }
    .power-zoom-hitbox { fill: transparent; cursor: crosshair; }
    .power-zoom-hitbox.pan { cursor: grab; }
    .power-chart-toolbar button[aria-pressed="true"] {
      border-color: #62b8f5;
      color: #62b8f5;
    }
    .power-zoom-selection {
      fill: #62b8f5;
      opacity: 0.18;
      stroke: #62b8f5;
      stroke-width: 1;
      pointer-events: none;
    }
    .energy-chart-swatch {
      width: 18px;
      height: 4px;
      border-radius: 2px;
      background: #ffd400;
    }
    .energy-chart-swatch.forecast {
      background: #ff9800;
      opacity: 0.24;
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
    .planning-facts {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 10px;
    }
    .planning-fact-card {
      padding: 12px;
      border: 1px solid #2a3745;
      border-radius: 10px;
      background: #151d26;
    }
    .planning-fact-card h3 { margin-top: 0; }
    .planning-fact-card.full-width { grid-column: 1 / -1; }
    .planning-attention {
      grid-column: 1 / -1;
      padding: 12px;
      border: 1px solid #ef5350;
      border-radius: 10px;
      background: rgba(239, 83, 80, 0.14);
      color: #ffb4ab;
    }
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
      <h2>Schakelhistorie batterijmodus</h2>
      <section
        id="storage-mode-transition-history"
        class="timeline-panel"
        aria-live="polite"
      >
        Nog geen door PicoT uitgevoerde moduswissels vastgelegd.
      </section>
      <h2>Incidenthistorie</h2>
      <section class="timeline-panel" aria-live="polite">
        <div class="incident-download-actions">
          <a href="downloads/planning-incidents.jsonl" download>
            Download incidenthistorie
          </a>
          <a href="downloads/picot-diagnostics.zip" download>
            Download alle diagnosebestanden
          </a>
        </div>
        <div id="planning-incident-history">
          Nog geen fallbackincidenten vastgelegd.
        </div>
      </section>
      <h2>Energiestromen vandaag</h2>
      <section
        id="power-history-chart"
        class="timeline-panel energy-chart-panel"
        aria-live="polite"
      >
        Nog geen canonieke vermogenshistorie beschikbaar.
      </section>
      <h2>Zelfverbruik ten opzichte van PV</h2>
      <section
        id="self-consumption-history-chart"
        class="timeline-panel energy-chart-panel"
        aria-live="polite"
      >
        Nog geen zelfverbruikshistorie beschikbaar.
      </section>
      <h2>Zon: forecast en werkelijkheid</h2>
      <section
        id="pv-forecast-actual-chart"
        class="timeline-panel energy-chart-panel"
        aria-live="polite"
      >
        Nog geen gesloten PV-intervallen beschikbaar.
      </section>
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

    <section id="planning-reset" class="status" aria-live="polite">
      <span id="planning-reset-result">
        Huidige en toekomstige planning kan handmatig opnieuw worden opgebouwd.
      </span>
      <button id="reset-planning" type="button">
        Planning resetten
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

    <h2>Huidige planning en besluit</h2>
    <section
      id="planning-status"
      class="timeline-panel"
      aria-live="polite"
    >
      Nog geen actuele planningsfeiten beschikbaar.
    </section>

    <h2>Canonieke planning naast etmaalsimulatie</h2>
    <section
      id="daily-observer-comparison"
      class="timeline-panel"
      aria-live="polite"
    >
      Nog geen etmaalsimulatie-uitkomst beschikbaar.
    </section>

    <h2>Onderliggende energiekansen</h2>
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
      if (value === null || value === undefined) return "—";
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

    const POWER_HISTORY_SELECTION_KEY = "picot-power-history-selection";
    let powerHistoryZoomWindow = null;
    let powerHistoryInteractionMode = "zoom";
    let pvForecastZoomWindow = null;
    let pvForecastInteractionMode = "pan";
    let planningIncidentHistorySignature = null;

    function renderPowerHistory(history) {
      const container = element("power-history-chart");
      container.replaceChildren();
      const series = Array.isArray(history?.series)
        ? history.series.filter((item) => Array.isArray(item.points))
        : [];
      const start = new Date(history?.starts_at);
      const end = new Date(history?.ends_at);
      if (
        history?.status !== "available" ||
        Number.isNaN(start.getTime()) ||
        Number.isNaN(end.getTime()) ||
        end <= start ||
        !series.some((item) => item.points.length > 0)
      ) {
        container.textContent = history?.error
          ? `Vermogenshistorie niet beschikbaar: ${history.error}.`
          : "Nog geen canonieke vermogenshistorie beschikbaar.";
        return;
      }

      const roleLabels = {
        pv_generation: "PV",
        household_load: "Huisverbruik",
        battery_charge: "Batterij laden",
        battery_discharge: "Batterij ontladen",
        grid_import: "Netimport",
        grid_export: "Netexport",
      };
      const roleColors = {
        pv_generation: "#ffd400",
        household_load: "#3994e6",
        battery_charge: "#35a862",
        battery_discharge: "#35a862",
        grid_import: "#ef4444",
        grid_export: "#aab2bd",
      };
      const signedPower = (role, value) =>
        ["pv_generation", "battery_charge", "grid_export"].includes(role)
          ? -Number(value)
          : Number(value);
      const available = series.filter((item) => roleLabels[item.role]);
      let storedSelection = null;
      try {
        const decoded = JSON.parse(
          localStorage.getItem(POWER_HISTORY_SELECTION_KEY)
        );
        if (Array.isArray(decoded)) storedSelection = new Set(decoded);
      } catch (_error) {
        storedSelection = null;
      }
      const selectedIds = storedSelection ?? new Set(
        available.map((item) => item.series_id)
      );
      const visible = available.filter((item) => selectedIds.has(item.series_id));
      const legend = document.createElement("div");
      legend.className = "energy-chart-legend";
      for (const item of available) {
        const key = document.createElement("button");
        key.type = "button";
        key.className = "energy-chart-key";
        key.setAttribute("aria-pressed", String(selectedIds.has(item.series_id)));
        key.title = `${roleLabels[item.role]} tonen of verbergen`;
        const swatch = document.createElement("span");
        swatch.className = `power-flow-line ${item.role}`;
        swatch.style.width = "18px";
        swatch.style.borderTop = "2px solid";
        swatch.style.borderColor = roleColors[item.role];
        key.append(swatch, document.createTextNode(roleLabels[item.role]));
        key.addEventListener("click", () => {
          if (selectedIds.has(item.series_id)) {
            selectedIds.delete(item.series_id);
          } else {
            selectedIds.add(item.series_id);
          }
          localStorage.setItem(
            POWER_HISTORY_SELECTION_KEY,
            JSON.stringify([...selectedIds]),
          );
          renderPowerHistory(history);
        });
        legend.appendChild(key);
      }
      const showAll = document.createElement("button");
      showAll.type = "button";
      showAll.className = "energy-chart-selection-action";
      showAll.textContent = "Alles tonen";
      showAll.addEventListener("click", () => {
        localStorage.removeItem(POWER_HISTORY_SELECTION_KEY);
        renderPowerHistory(history);
      });
      legend.appendChild(showAll);
      container.appendChild(legend);

      if (visible.length === 0) {
        const empty = document.createElement("p");
        empty.textContent = "Selecteer één of meer energiestromen.";
        container.appendChild(empty);
        return;
      }

      const currentValues = document.createElement("div");
      currentValues.className = "power-current-values";
      for (const item of visible) {
        const latest = item.points.at(-1);
        if (!latest) continue;
        const value = document.createElement("div");
        value.className = "power-current-value";
        const amount = document.createElement("strong");
        amount.style.color = roleColors[item.role];
        amount.textContent = `${new Intl.NumberFormat("nl-NL", {
          maximumFractionDigits: 1,
        }).format(signedPower(item.role, latest.power_w))} W`;
        value.append(document.createTextNode(roleLabels[item.role]), amount);
        currentValues.appendChild(value);
      }
      container.appendChild(currentValues);

      const width = 1180;
      const height = 330;
      const plot = { left: 72, right: 24, top: 20, bottom: 48 };
      const plotWidth = width - plot.left - plot.right;
      const plotHeight = height - plot.top - plot.bottom;
      const startMs = start.getTime();
      const dayEnd = new Date(start);
      dayEnd.setDate(dayEnd.getDate() + 1);
      const fullEndMs = dayEnd.getTime();
      const validZoom = powerHistoryZoomWindow &&
        powerHistoryZoomWindow.startsAt >= startMs &&
        powerHistoryZoomWindow.endsAt <= fullEndMs &&
        powerHistoryZoomWindow.startsAt < powerHistoryZoomWindow.endsAt;
      if (!validZoom) powerHistoryZoomWindow = null;
      const windowStartMs = powerHistoryZoomWindow?.startsAt ?? startMs;
      const windowEndMs = powerHistoryZoomWindow?.endsAt ?? fullEndMs;
      const pointsInWindow = (item) => {
        const sourcePoints = [...item.display_points].sort((left, right) =>
          new Date(left.sampled_at).getTime() -
          new Date(right.sampled_at).getTime()
        );
        return sourcePoints.filter((point) => {
          const sampledAt = new Date(point.sampled_at).getTime();
          return sampledAt >= windowStartMs && sampledAt <= windowEndMs;
        });
      };
      const allValues = visible.flatMap((item) =>
        pointsInWindow(item)
          .map((point) => signedPower(item.role, point.power_w))
      ).filter(Number.isFinite);
      const rawMinimum = Math.min(0, ...allValues);
      const rawMaximum = Math.max(0, ...allValues);
      const span = Math.max(1, rawMaximum - rawMinimum);
      const padding = span * 0.05;
      const hasRange = rawMinimum < 0 || rawMaximum > 0;
      const minimum = hasRange
        ? (rawMinimum < 0 ? rawMinimum - padding : 0)
        : -1;
      const maximum = hasRange
        ? (rawMaximum > 0 ? rawMaximum + padding : 0)
        : 1;
      const x = (value) => plot.left +
        (new Date(value).getTime() - windowStartMs) /
        (windowEndMs - windowStartMs) * plotWidth;
      const y = (value) => plot.top +
        (maximum - Number(value)) / (maximum - minimum) * plotHeight;

      const toolbar = document.createElement("div");
      toolbar.className = "power-chart-toolbar";
      const changeZoom = (factor) => {
        const fullDuration = fullEndMs - startMs;
        const currentDuration = windowEndMs - windowStartMs;
        const duration = Math.min(
          fullDuration,
          Math.max(15 * 60 * 1000, currentDuration * factor),
        );
        const center = (windowStartMs + windowEndMs) / 2;
        let startsAt = center - duration / 2;
        let endsAt = center + duration / 2;
        if (startsAt < startMs) {
          endsAt += startMs - startsAt;
          startsAt = startMs;
        }
        if (endsAt > fullEndMs) {
          startsAt -= endsAt - fullEndMs;
          endsAt = fullEndMs;
        }
        powerHistoryZoomWindow = { startsAt, endsAt };
        renderPowerHistory(history);
      };
      for (const [label, title, action] of [
        ["+", "Inzoomen", () => changeZoom(0.5)],
        ["−", "Uitzoomen", () => changeZoom(2)],
        ["↺", "Volledige dag tonen", () => {
          powerHistoryZoomWindow = null;
          renderPowerHistory(history);
        }],
      ]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = title;
        button.addEventListener("click", action);
        toolbar.appendChild(button);
      }
      for (const [mode, label, title] of [
        ["zoom", "⌕", "Sleep om een tijdvak te vergroten"],
        ["pan", "✋", "Versleep het ingezoomde tijdvak"],
      ]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = title;
        button.setAttribute(
          "aria-pressed",
          String(powerHistoryInteractionMode === mode),
        );
        button.addEventListener("click", () => {
          powerHistoryInteractionMode = mode;
          renderPowerHistory(history);
        });
        toolbar.prepend(button);
      }
      container.appendChild(toolbar);

      const scroll = document.createElement("div");
      scroll.className = "energy-chart-scroll";
      const svg = createSvgElement("svg", {
        class: "energy-chart",
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": "Canonieke vermogensstromen van vandaag",
      });
      const gridValues = Array.from(new Set([
        ...Array.from(
          { length: 5 },
          (_item, index) => minimum + (maximum - minimum) * index / 4,
        ),
        0,
      ])).sort((left, right) => left - right);
      for (const value of gridValues) {
        const lineY = y(value);
        svg.appendChild(createSvgElement("line", {
          x1: plot.left,
          x2: width - plot.right,
          y1: lineY,
          y2: lineY,
          class: value === 0
            ? "power-zero-line"
            : "grid-line",
        }));
        appendSvgText(
          svg,
          `${Math.round(value)} W`,
          { x: plot.left - 8, y: lineY + 4, "text-anchor": "end" },
          "axis-label",
        );
      }
      for (let index = 0; index <= 12; index += 1) {
        const tick = new Date(
          windowStartMs + (windowEndMs - windowStartMs) * index / 12
        );
        appendSvgText(
          svg,
          tick.toLocaleTimeString("nl-NL", {
            hour: "2-digit",
            minute: "2-digit",
          }),
          { x: x(tick), y: height - 18, "text-anchor": "middle" },
          "axis-label",
        );
      }
      for (const item of visible) {
        const points = pointsInWindow(item)
          .map((point) => ({
            x: x(point.sampled_at),
            y: y(signedPower(item.role, point.power_w)),
          }))
          .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
        if (points.length === 0) continue;
        let path = `M ${points[0].x} ${points[0].y}`;
        for (const point of points.slice(1)) {
          path += ` L ${point.x} ${point.y}`;
        }
        const pathEndsAtX = points.at(-1).x;
        if (["grid_export", "battery_charge"].includes(item.role)) {
          const area = `${path} L ${pathEndsAtX} ${y(0)}` +
            ` L ${points[0].x} ${y(0)} Z`;
          svg.appendChild(createSvgElement("path", {
            d: area,
            class: `power-flow-area ${item.role}`,
          }));
        }
        svg.appendChild(createSvgElement("path", {
          d: path,
          class: `power-flow-line ${item.role}`,
        }));
      }
      const hitbox = createSvgElement("rect", {
        x: plot.left,
        y: plot.top,
        width: plotWidth,
        height: plotHeight,
        class: `power-zoom-hitbox ${powerHistoryInteractionMode}`,
      });
      let dragStartsAt = null;
      let selection = null;
      const svgX = (event) => {
        const bounds = svg.getBoundingClientRect();
        return Math.max(
          plot.left,
          Math.min(
            width - plot.right,
            (event.clientX - bounds.left) * width / bounds.width,
          ),
        );
      };
      hitbox.addEventListener("pointerdown", (event) => {
        dragStartsAt = svgX(event);
        hitbox.setPointerCapture(event.pointerId);
        if (powerHistoryInteractionMode === "zoom") {
          selection = createSvgElement("rect", {
            x: dragStartsAt,
            y: plot.top,
            width: 0,
            height: plotHeight,
            class: "power-zoom-selection",
          });
          svg.appendChild(selection);
        }
      });
      hitbox.addEventListener("pointermove", (event) => {
        if (
          dragStartsAt === null ||
          powerHistoryInteractionMode !== "zoom" ||
          !selection
        ) return;
        const current = svgX(event);
        selection.setAttribute("x", String(Math.min(dragStartsAt, current)));
        selection.setAttribute("width", String(Math.abs(current - dragStartsAt)));
      });
      hitbox.addEventListener("pointerup", (event) => {
        if (dragStartsAt === null) return;
        const dragEndsAt = svgX(event);
        selection?.remove();
        selection = null;
        if (
          powerHistoryInteractionMode === "pan" &&
          powerHistoryZoomWindow &&
          Math.abs(dragEndsAt - dragStartsAt) >= 2
        ) {
          const duration = windowEndMs - windowStartMs;
          const shift = -(dragEndsAt - dragStartsAt) / plotWidth * duration;
          let startsAt = windowStartMs + shift;
          let endsAt = windowEndMs + shift;
          if (startsAt < startMs) {
            endsAt += startMs - startsAt;
            startsAt = startMs;
          }
          if (endsAt > fullEndMs) {
            startsAt -= endsAt - fullEndMs;
            endsAt = fullEndMs;
          }
          powerHistoryZoomWindow = { startsAt, endsAt };
          renderPowerHistory(history);
        } else if (
          powerHistoryInteractionMode === "zoom" &&
          Math.abs(dragEndsAt - dragStartsAt) >= 8
        ) {
          const left = Math.min(dragStartsAt, dragEndsAt);
          const right = Math.max(dragStartsAt, dragEndsAt);
          const toTime = (position) => windowStartMs +
            (position - plot.left) / plotWidth *
            (windowEndMs - windowStartMs);
          powerHistoryZoomWindow = {
            startsAt: toTime(left),
            endsAt: toTime(right),
          };
          renderPowerHistory(history);
        }
        dragStartsAt = null;
      });
      hitbox.addEventListener("dblclick", () => {
        powerHistoryZoomWindow = null;
        renderPowerHistory(history);
      });
      svg.appendChild(hitbox);
      scroll.appendChild(svg);
      container.appendChild(scroll);
    }

    function renderSelfConsumptionHistory(history) {
      const container = element("self-consumption-history-chart");
      container.replaceChildren();
      const series = Array.isArray(history?.series) ? history.series : [];
      const start = new Date(history?.starts_at);
      const end = new Date(history?.ends_at);
      if (
        history?.status !== "available" ||
        Number.isNaN(start.getTime()) ||
        Number.isNaN(end.getTime()) ||
        !series.some((item) => item.points?.length > 0)
      ) {
        container.textContent = history?.error
          ? `Zelfverbruikshistorie niet beschikbaar: ${history.error}.`
          : "Nog geen zelfverbruikshistorie beschikbaar.";
        return;
      }

      const labels = {
        pv_generation: "PV-opwek totaal",
        local_pv_use: "Lokaal gebruikte PV",
        grid_import: "Netimport",
      };
      const colors = {
        pv_generation: "#ffd600",
        local_pv_use: "#2196f3",
        grid_import: "#d32f2f",
      };
      const visible = series.filter((item) => labels[item.role]);
      const currentValues = document.createElement("div");
      currentValues.className = "power-current-values";
      for (const item of visible) {
        const current = Number(history.current_values?.[item.role]);
        if (!Number.isFinite(current)) continue;
        const value = document.createElement("div");
        value.className = "power-current-value";
        const amount = document.createElement("strong");
        amount.style.color = colors[item.role];
        amount.textContent = `${new Intl.NumberFormat("nl-NL", {
          maximumFractionDigits: 1,
        }).format(Math.max(0, current))} W`;
        value.append(document.createTextNode(labels[item.role]), amount);
        currentValues.appendChild(value);
      }
      container.appendChild(currentValues);

      const width = 1180;
      const height = 330;
      const plot = { left: 72, right: 24, top: 20, bottom: 48 };
      const plotWidth = width - plot.left - plot.right;
      const plotHeight = height - plot.top - plot.bottom;
      const startMs = start.getTime();
      const dayEnd = new Date(start);
      dayEnd.setDate(dayEnd.getDate() + 1);
      const endMs = dayEnd.getTime();
      const values = visible.flatMap((item) =>
        item.points.map((point) => Math.max(0, Number(point.power_w)))
      ).filter(Number.isFinite);
      const maximum = Math.max(1, ...values) * 1.05;
      const x = (value) => plot.left +
        (new Date(value).getTime() - startMs) / (endMs - startMs) * plotWidth;
      const y = (value) => plot.top +
        (maximum - Math.max(0, Number(value))) / maximum * plotHeight;

      const scroll = document.createElement("div");
      scroll.className = "energy-chart-scroll";
      const svg = createSvgElement("svg", {
        class: "energy-chart",
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": "Zelfverbruik ten opzichte van PV vandaag",
      });
      for (let index = 0; index <= 4; index += 1) {
        const value = maximum * index / 4;
        const lineY = y(value);
        svg.appendChild(createSvgElement("line", {
          x1: plot.left,
          x2: width - plot.right,
          y1: lineY,
          y2: lineY,
          class: value === 0 ? "power-zero-line" : "grid-line",
        }));
        appendSvgText(
          svg,
          `${Math.round(value)} W`,
          { x: plot.left - 8, y: lineY + 4, "text-anchor": "end" },
          "axis-label",
        );
      }
      for (let index = 0; index <= 12; index += 1) {
        const tick = new Date(startMs + (endMs - startMs) * index / 12);
        appendSvgText(
          svg,
          tick.toLocaleTimeString("nl-NL", {
            hour: "2-digit",
            minute: "2-digit",
          }),
          { x: x(tick), y: height - 18, "text-anchor": "middle" },
          "axis-label",
        );
      }
      for (const item of visible) {
        const points = item.points.map((point) => ({
          x: x(point.sampled_at),
          y: y(point.power_w),
        })).filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
        if (points.length === 0) continue;
        let path = `M ${points[0].x} ${points[0].y}`;
        for (const point of points.slice(1)) {
          path += ` L ${point.x} ${point.y}`;
        }
        const area = `${path} L ${points.at(-1).x} ${y(0)}` +
          ` L ${points[0].x} ${y(0)} Z`;
        svg.appendChild(createSvgElement("path", {
          d: area,
          class: `self-consumption-area ${item.role}`,
        }));
        svg.appendChild(createSvgElement("path", {
          d: path,
          class: `self-consumption-line ${item.role}`,
        }));
      }
      const now = Date.now();
      if (now >= startMs && now <= endMs) {
        svg.appendChild(createSvgElement("line", {
          x1: x(now),
          x2: x(now),
          y1: plot.top,
          y2: height - plot.bottom,
          stroke: "#ffb300",
          "stroke-width": 1.5,
          "stroke-dasharray": "4 4",
        }));
        appendSvgText(
          svg,
          "Nu",
          { x: x(now) + 4, y: plot.top + 12 },
          "axis-label",
        );
      }
      scroll.appendChild(svg);
      container.appendChild(scroll);
    }

    function renderPvForecastActualChart(deviations, timeline, history) {
      const container = element("pv-forecast-actual-chart");
      container.replaceChildren();
      const forecastByStart = new Map();
      for (const item of Array.isArray(deviations) ? deviations : []) {
        const startsAt = new Date(item.starts_at).getTime();
        const endsAt = new Date(item.ends_at).getTime();
        const energyWh = Number(item.forecast_central_energy_wh);
        const durationHours = (endsAt - startsAt) / 3_600_000;
        if (
          Number.isFinite(startsAt) && Number.isFinite(endsAt) &&
          Number.isFinite(energyWh) && durationHours > 0
        ) {
          forecastByStart.set(startsAt, {
            sampledAt: startsAt + (endsAt - startsAt) / 2,
            powerW: energyWh / durationHours,
          });
        }
      }
      for (const item of Array.isArray(timeline?.intervals)
        ? timeline.intervals : []) {
        if (item.evidence_type !== "FORECAST") continue;
        const startsAt = new Date(item.starts_at).getTime();
        const endsAt = new Date(item.ends_at).getTime();
        const energyWh = Number(item.pv_energy_wh);
        const durationHours = (endsAt - startsAt) / 3_600_000;
        if (
          Number.isFinite(startsAt) && Number.isFinite(endsAt) &&
          Number.isFinite(energyWh) && durationHours > 0
        ) {
          forecastByStart.set(startsAt, {
            sampledAt: startsAt + (endsAt - startsAt) / 2,
            powerW: energyWh / durationHours,
          });
        }
      }
      const forecastPoints = [...forecastByStart.values()]
        .sort((left, right) => left.sampledAt - right.sampledAt);
      const actualPoints = (Array.isArray(history?.pv_actual_display_points)
        ? history.pv_actual_display_points : [])
        .map((point) => ({
          sampledAt: new Date(point.sampled_at).getTime(),
          powerW: Math.max(0, Number(point.power_w)),
        }))
        .filter((point) =>
          Number.isFinite(point.sampledAt) && Number.isFinite(point.powerW)
        )
        .sort((left, right) => left.sampledAt - right.sampledAt);
      if (forecastPoints.length === 0 && actualPoints.length === 0) {
        container.textContent = "Nog geen Solcast- of GoodWe-vermogensdata.";
        return;
      }

      const legend = document.createElement("div");
      legend.className = "energy-chart-legend";
      for (const [kind, label] of [
        ["forecast", "Solcast verwacht"],
        ["actual", "GoodWe werkelijk"],
      ]) {
        const item = document.createElement("span");
        item.className = "energy-chart-key";
        const swatch = document.createElement("span");
        swatch.className = `energy-chart-swatch ${kind}`;
        item.append(swatch, document.createTextNode(label));
        legend.appendChild(item);
      }
      container.appendChild(legend);

      const width = 1180;
      const height = 430;
      const plot = { left: 72, right: 24, top: 20, bottom: 48 };
      const plotWidth = width - plot.left - plot.right;
      const plotHeight = height - plot.top - plot.bottom;
      const sourceStartMs = new Date(history?.starts_at).getTime();
      const firstMs = Math.min(
        ...forecastPoints.map((point) => point.sampledAt),
        ...actualPoints.map((point) => point.sampledAt),
      );
      const dayStart = Number.isFinite(sourceStartMs)
        ? new Date(sourceStartMs) : new Date(firstMs);
      dayStart.setHours(0, 0, 0, 0);
      const startMs = dayStart.getTime();
      const fullEndMs = startMs + 24 * 60 * 60 * 1000;
      const validZoom = pvForecastZoomWindow &&
        pvForecastZoomWindow.startsAt >= startMs &&
        pvForecastZoomWindow.endsAt <= fullEndMs &&
        pvForecastZoomWindow.startsAt < pvForecastZoomWindow.endsAt;
      if (!validZoom) pvForecastZoomWindow = null;
      const windowStartMs = pvForecastZoomWindow?.startsAt ?? startMs;
      const windowEndMs = pvForecastZoomWindow?.endsAt ?? fullEndMs;
      const inWindow = (point) =>
        point.sampledAt >= windowStartMs && point.sampledAt <= windowEndMs;
      const visibleForecast = forecastPoints.filter(inWindow);
      const visibleActual = actualPoints.filter(inWindow);
      const values = [...visibleForecast, ...visibleActual]
        .map((point) => point.powerW);
      const maximum = Math.max(1, ...values) * 1.05;
      const x = (value) => plot.left +
        (value - windowStartMs) / (windowEndMs - windowStartMs) * plotWidth;
      const y = (value) => plot.top +
        (maximum - Math.max(0, Number(value))) / maximum * plotHeight;

      const toolbar = document.createElement("div");
      toolbar.className = "power-chart-toolbar";
      const rerender = () => renderPvForecastActualChart(
        deviations, timeline, history
      );
      const changeZoom = (factor) => {
        const currentDuration = windowEndMs - windowStartMs;
        const duration = Math.min(
          fullEndMs - startMs,
          Math.max(15 * 60 * 1000, currentDuration * factor),
        );
        const center = (windowStartMs + windowEndMs) / 2;
        let startsAt = Math.max(startMs, center - duration / 2);
        let endsAt = Math.min(fullEndMs, startsAt + duration);
        startsAt = Math.max(startMs, endsAt - duration);
        pvForecastZoomWindow = { startsAt, endsAt };
        rerender();
      };
      for (const [mode, label, title] of [
        ["pan", "✋", "Versleep het ingezoomde tijdvak"],
        ["zoom", "⌕", "Sleep om een tijdvak te vergroten"],
      ]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = title;
        button.setAttribute(
          "aria-pressed", String(pvForecastInteractionMode === mode)
        );
        button.addEventListener("click", () => {
          pvForecastInteractionMode = mode;
          rerender();
        });
        toolbar.appendChild(button);
      }
      for (const [label, title, action] of [
        ["+", "Inzoomen", () => changeZoom(0.5)],
        ["−", "Uitzoomen", () => changeZoom(2)],
        ["↺", "Volledige dag tonen", () => {
          pvForecastZoomWindow = null;
          rerender();
        }],
      ]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = title;
        button.addEventListener("click", action);
        toolbar.appendChild(button);
      }
      container.appendChild(toolbar);

      const scroll = document.createElement("div");
      scroll.className = "energy-chart-scroll";
      const svg = createSvgElement("svg", {
        class: "energy-chart",
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": "Solcast forecast versus GoodWe werkelijk vermogen",
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
          `${Math.round(value)} W`,
          { x: plot.left - 8, y: lineY + 4, "text-anchor": "end" },
          "axis-label",
        );
      }

      for (let index = 0; index <= 12; index += 1) {
        const tick = new Date(
          windowStartMs + (windowEndMs - windowStartMs) * index / 12
        );
        appendSvgText(
          svg,
          tick.toLocaleTimeString("nl-NL", {
            hour: "2-digit",
            minute: "2-digit",
          }),
          { x: x(tick.getTime()), y: height - 18, "text-anchor": "middle" },
          "axis-label",
        );
      }
      const chartPoints = (points) => points.map((point) => ({
        x: x(point.sampledAt),
        y: y(point.powerW),
      }));
      const smoothPath = (points) => {
        if (points.length === 0) return "";
        if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
        let path = `M ${points[0].x} ${points[0].y}`;
        for (let index = 1; index < points.length - 1; index += 1) {
          const current = points[index];
          const next = points[index + 1];
          path += ` Q ${current.x} ${current.y}` +
            ` ${(current.x + next.x) / 2} ${(current.y + next.y) / 2}`;
        }
        const last = points.at(-1);
        return `${path} L ${last.x} ${last.y}`;
      };
      const forecastChartPoints = chartPoints(visibleForecast);
      const forecastPath = smoothPath(forecastChartPoints);
      if (forecastPath) {
        const area = `${forecastPath} L ${forecastChartPoints.at(-1).x}` +
          ` ${y(0)} L ${forecastChartPoints[0].x} ${y(0)} Z`;
        svg.appendChild(createSvgElement("path", {
          d: area,
          class: "forecast-range",
        }));
        svg.appendChild(createSvgElement("path", {
          d: forecastPath,
          class: "forecast-line",
        }));
      }
      const actualPath = smoothPath(chartPoints(visibleActual));
      if (actualPath) {
        svg.appendChild(createSvgElement("path", {
          d: actualPath,
          class: "actual-line",
        }));
      }
      const hitbox = createSvgElement("rect", {
        x: plot.left,
        y: plot.top,
        width: plotWidth,
        height: plotHeight,
        class: `power-zoom-hitbox ${pvForecastInteractionMode}`,
      });
      let dragStartsAt = null;
      let selection = null;
      const svgX = (event) => {
        const bounds = svg.getBoundingClientRect();
        return Math.max(plot.left, Math.min(
          width - plot.right,
          (event.clientX - bounds.left) * width / bounds.width,
        ));
      };
      hitbox.addEventListener("pointerdown", (event) => {
        dragStartsAt = svgX(event);
        hitbox.setPointerCapture(event.pointerId);
        if (pvForecastInteractionMode === "zoom") {
          selection = createSvgElement("rect", {
            x: dragStartsAt, y: plot.top, width: 0, height: plotHeight,
            class: "power-zoom-selection",
          });
          svg.appendChild(selection);
        }
      });
      hitbox.addEventListener("pointermove", (event) => {
        if (dragStartsAt === null || !selection) return;
        const current = svgX(event);
        selection.setAttribute("x", String(Math.min(dragStartsAt, current)));
        selection.setAttribute("width", String(Math.abs(current - dragStartsAt)));
      });
      hitbox.addEventListener("pointerup", (event) => {
        if (dragStartsAt === null) return;
        const dragEndsAt = svgX(event);
        selection?.remove();
        selection = null;
        const delta = dragEndsAt - dragStartsAt;
        if (
          pvForecastInteractionMode === "pan" && pvForecastZoomWindow &&
          Math.abs(delta) >= 2
        ) {
          const duration = windowEndMs - windowStartMs;
          const shift = -delta / plotWidth * duration;
          let startsAt = windowStartMs + shift;
          let endsAt = windowEndMs + shift;
          if (startsAt < startMs) {
            endsAt += startMs - startsAt;
            startsAt = startMs;
          }
          if (endsAt > fullEndMs) {
            startsAt -= endsAt - fullEndMs;
            endsAt = fullEndMs;
          }
          pvForecastZoomWindow = { startsAt, endsAt };
          rerender();
        } else if (
          pvForecastInteractionMode === "zoom" && Math.abs(delta) >= 8
        ) {
          const left = Math.min(dragStartsAt, dragEndsAt);
          const right = Math.max(dragStartsAt, dragEndsAt);
          const toTime = (position) => windowStartMs +
            (position - plot.left) / plotWidth *
            (windowEndMs - windowStartMs);
          pvForecastZoomWindow = {
            startsAt: toTime(left), endsAt: toTime(right),
          };
          rerender();
        }
        dragStartsAt = null;
      });
      hitbox.addEventListener("dblclick", () => {
        pvForecastZoomWindow = null;
        rerender();
      });
      svg.appendChild(hitbox);
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
        summary.textContent = `${group.label_nl} (${group.count})`;
        details.appendChild(summary);
        const table = document.createElement("table");
        const head = document.createElement("thead");
        const headRow = document.createElement("tr");
        for (const label of ["Periode", "Prijs", "Confidence", "Reden"]) {
          const cell = document.createElement("th");
          cell.textContent = label;
          headRow.append(cell);
        }
        head.append(headRow);
        const body = document.createElement("tbody");
        for (const item of group.items ?? []) {
          const row = document.createElement("tr");
          for (const value of [
            item.period_nl,
            item.price_nl,
            item.confidence_nl,
            item.reason_nl,
          ]) {
            const cell = document.createElement("td");
            cell.textContent = displayValue(value);
            row.append(cell);
          }
          body.append(row);
        }
        table.append(head, body);
        details.appendChild(table);
        fragment.appendChild(details);
      }
      container.replaceChildren(fragment);
    }

    function renderPlanningStatus(status) {
      const container = element("planning-status");
      if (!status) {
        container.textContent =
          "Niet beschikbaar · de actuele pipeline-run ontbreekt.";
        return;
      }
      const root = document.createElement("div");
      root.className = "planning-facts";
      const attention = status.attention ?? {};
      if (attention.required === true) {
        const warning = document.createElement("section");
        warning.className = "planning-attention";
        warning.textContent = `${attention.title} — ${attention.message}`;
        root.append(warning);
      }
      const addCard = (title, rows, fullWidth = false) => {
        const panel = document.createElement("article");
        panel.className = "planning-fact-card" +
          (fullWidth ? " full-width" : "");
        const heading = document.createElement("h3");
        heading.textContent = title;
        const facts = document.createElement("dl");
        for (const [label, value] of rows) {
          appendAttribute(facts, label, value);
        }
        panel.append(heading, facts);
        root.append(panel);
        return panel;
      };
      const strategy = status.strategy ?? {};
      addCard("Huidige strategie", [
        ["Regime", strategy.status],
        ["Reden", strategy.reason],
        ["Prioriteitsvolgorde", (strategy.objective_order ?? []).join(" → ")],
        [
          "PV-confidence",
          strategy.forecast_confidence_available === false
            ? "Niet beschikbaar"
            : formatConfidence(strategy.forecast_confidence),
        ],
        ["Batterijdoel in gevaar", strategy.storage_target_at_risk],
      ]);
      const decision = status.decision ?? {};
      addCard("Besluit", [
        ["Status", decision.status],
        ["Gekozen planfamilie", decision.candidate_family],
        ["Beslisregel", decision.decisive_step],
        ["Reden", decision.reason],
        ["Confidence", formatConfidence(decision.confidence)],
      ]);
      const target = status.storage_target ?? {};
      addCard("Batterijdoel", [
        ["Doelenergie", formatMeasurement(target.required_energy_wh, "Wh")],
        ["Doel-SoC", target.required_soc == null
          ? "Niet beschikbaar"
          : `${Math.round(Number(target.required_soc) * 100)}%`],
        ["Deadline", formatTimestamp(target.required_by)],
        ["Reden", target.reason],
        ["Doel gehaald in prognose", target.requirement_satisfied],
        ["Geprojecteerde energie", formatMeasurement(target.projected_energy_wh, "Wh")],
        ["Bijdrage PV", formatMeasurement(target.pv_contribution_wh, "Wh")],
        ["Bijdrage net", formatMeasurement(target.grid_contribution_wh, "Wh")],
        ["Confidence", formatConfidence(target.confidence)],
      ]);
      const execution = status.execution ?? {};
      addCard("Uitvoering", [
        ["Status", execution.status],
        ["Reden", execution.reason],
        ["Planning", execution.timing],
        ["Primitive", execution.planned_primitive],
        ["Geplande batterijmodus", execution.planned_vendor_mode],
        ["Primitive-status", execution.primitive_status],
        ["Blokkades", (execution.blockers ?? []).join(", ")],
      ]);
      addCard("Geldigheid", [
        ["Vastgelegd", formatTimestamp(status.captured_at)],
        ["Planningshorizon", formatTimestamp(status.valid_until)],
        ["Uitvoering vanaf", formatTimestamp(execution.valid_from)],
        ["Uitvoering tot", formatTimestamp(execution.valid_until)],
        ["Run", status.run_id],
        ["Snapshot", status.snapshot_id],
      ]);

      const chosenPlan = status.chosen_plan ?? {};
      const chosenCard = addCard("Gekozen uitvoeringsplan", [
        ["Kandidaat", chosenPlan.candidate_id],
        ["Energiepad", chosenPlan.energy_path_id],
        ["Planfamilie", chosenPlan.family],
        ["Beslisregel", chosenPlan.decisive_step],
        ["Beslisreden", chosenPlan.reason],
        ["Laadvenster vanaf", formatTimestamp(chosenPlan.charge_window_starts_at)],
        ["Laadvenster tot", formatTimestamp(chosenPlan.charge_window_ends_at)],
        ["Totale doelenergie", formatMeasurement(chosenPlan.required_energy_wh, "Wh")],
        ["Batterijenergie bij vastleggen", formatMeasurement(
          chosenPlan.initial_storage_energy_wh, "Wh"
        )],
        ["Verwacht accuverbruik tot laadstart", formatMeasurement(
          chosenPlan.projected_storage_use_before_window_wh, "Wh"
        )],
        ["Verwachte energie bij laadstart", formatMeasurement(
          chosenPlan.storage_energy_at_window_start_wh, "Wh"
        )],
        ["Benodigde toevoeging bij laadstart", formatMeasurement(
          chosenPlan.required_storage_addition_wh, "Wh"
        )],
        ["Gebruikte PV-forecastbasis", chosenPlan.pv_forecast_basis],
        ["Energie einde laadvenster", formatMeasurement(
          chosenPlan.storage_energy_at_window_end_wh, "Wh"
        )],
        ["Energie bij deadline", formatMeasurement(
          chosenPlan.storage_energy_at_requirement_wh, "Wh"
        )],
        ["Laaddoel 100% gehaald", chosenPlan.charge_target_satisfied],
        ["Reserve bij deadline gehaald", chosenPlan.reserve_satisfied],
        ["Minimaal benodigde reserve", formatMeasurement(
          chosenPlan.reserve_energy_required_wh, "Wh"
        )],
        ["Bijdrage PV", formatMeasurement(chosenPlan.pv_contribution_wh, "Wh")],
        ["Bijdrage net", formatMeasurement(chosenPlan.grid_contribution_wh, "Wh")],
        ["Conversieverlies", formatMeasurement(chosenPlan.conversion_losses_wh, "Wh")],
        ["Doel gehaald", chosenPlan.requirement_satisfied],
        ["Herstelbaarheid", formatConfidence(chosenPlan.recoverability)],
        ["Planconfidence", formatConfidence(chosenPlan.confidence)],
        ["Confidence batterijdoel", formatConfidence(
          chosenPlan.requirement_confidence
        )],
      ], true);
      const segments = Array.isArray(chosenPlan.execution_segments)
        ? chosenPlan.execution_segments : [];
      const segmentTable = document.createElement("table");
      const segmentHead = document.createElement("thead");
      const segmentHeadRow = document.createElement("tr");
      for (const label of [
        "Vanaf", "Tot", "Primitive", "Batterijmodus",
        "Laadbron", "Doel", "Status"
      ]) {
        const cell = document.createElement("th");
        cell.textContent = label;
        segmentHeadRow.append(cell);
      }
      segmentHead.append(segmentHeadRow);
      const segmentBody = document.createElement("tbody");
      for (const segment of segments) {
        const row = document.createElement("tr");
        for (const value of [
          formatTimestamp(segment.starts_at),
          formatTimestamp(segment.ends_at),
          segment.primitive,
          segment.planned_vendor_mode,
          segment.charge_source_policy,
          segment.purpose,
          segment.lifecycle_status,
        ]) {
          const cell = document.createElement("td");
          cell.textContent = displayValue(value);
          row.append(cell);
        }
        segmentBody.append(row);
      }
      segmentTable.append(segmentHead, segmentBody);
      chosenCard.append(segmentTable);

      const alternatives = Array.isArray(status.alternatives)
        ? status.alternatives : [];
      const card = addCard("Kandidaten", [], true);
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      for (const label of [
        "Kandidaat", "Planfamilie", "Gekozen", "Venster vanaf", "Venster tot",
        "Energie einde venster", "Energie bij deadline", "Doel gehaald",
        "PV", "Net", "Herstelbaarheid", "Confidence"
      ]) {
        const cell = document.createElement("th");
        cell.textContent = label;
        headRow.append(cell);
      }
      head.append(headRow);
      const body = document.createElement("tbody");
      for (const alternative of alternatives) {
        const row = document.createElement("tr");
        for (const value of [
          alternative.candidate_id,
          alternative.family,
          alternative.selected,
          formatTimestamp(alternative.charge_window_starts_at),
          formatTimestamp(alternative.charge_window_ends_at),
          formatMeasurement(alternative.storage_energy_at_window_end_wh, "Wh"),
          formatMeasurement(alternative.storage_energy_at_requirement_wh, "Wh"),
          alternative.requirement_satisfied,
          formatMeasurement(alternative.pv_contribution_wh, "Wh"),
          formatMeasurement(alternative.grid_contribution_wh, "Wh"),
          formatConfidence(alternative.recoverability),
          formatConfidence(alternative.confidence),
        ]) {
          const cell = document.createElement("td");
          cell.textContent = displayValue(value);
          row.append(cell);
        }
        body.append(row);
      }
      table.append(head, body);
      card.append(table);
      container.replaceChildren(root);
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

    async function resetPlanning() {
      const resetButton = element("reset-planning");
      const confirmed = globalThis.confirm(
        "Alle huidige en toekomstige plannen worden beëindigd. PicoT maakt " +
        "direct een nieuw plan met actuele gegevens. Historie, leerdata en " +
        "instellingen blijven behouden. Een actieve laadplanning kan worden " +
        "afgebroken. Doorgaan?"
      );
      if (!confirmed) return;
      resetButton.disabled = true;
      try {
        const response = await fetch("api/planning/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reset_id: storageModeResetId() })
        });
        if (!response.ok) {
          throw new Error(`Planningreset geweigerd (${response.status})`);
        }
        const result = await response.json();
        element("planning-reset-result").textContent =
          `Reset geaccepteerd; ${result.removed_commitment_count ?? 0} ` +
          "commitment(s) verwijderd. Nieuwe planning wordt opgebouwd.";
        await loadView();
      } catch (error) {
        element("planning-reset-result").textContent =
          error instanceof Error ? error.message : "Planningreset mislukt.";
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

    function renderDailyObserverComparison(view) {
      const container = element("daily-observer-comparison");
      container.replaceChildren();
      const observer = view.daily_observer_comparison ?? {};
      const canonical = view.planning_status?.chosen_plan ?? {};
      const grid = document.createElement("div");
      grid.className = "daily-comparison-grid";

      function comparisonCard(title, className, rows) {
        const card = document.createElement("article");
        card.className = "daily-comparison-card " + className;
        const heading = document.createElement("h3");
        heading.textContent = title;
        card.append(heading);
        const values = document.createElement("dl");
        for (const [label, value] of rows) {
          const row = document.createElement("div");
          row.className = "attribute";
          const term = document.createElement("dt");
          term.textContent = label;
          const description = document.createElement("dd");
          description.textContent = displayValue(value);
          row.append(term, description);
          values.append(row);
        }
        card.append(values);
        return card;
      }

      grid.append(comparisonCard("Huidige canonieke keuze", "canonical", [
        ["Kandidaat", canonical.candidate_id],
        ["Planfamilie", canonical.family],
        ["Venster vanaf", canonical.charge_window_starts_at],
        ["Venster tot", canonical.charge_window_ends_at],
        ["Benodigde toevoeging", formatEnergyKwh(
          canonical.required_storage_addition_wh
        )],
        ["Confidence", formatConfidence(canonical.confidence)],
        ["Beslisreden", canonical.reason],
      ]));

      const aligned = observer.snapshot_id === view.snapshot_id;
      const best = Array.isArray(observer.candidates)
        ? observer.candidates.filter((candidate) => candidate.best_observation)
        : [];
      const observerReasonLabels = {
        daily_reference_physical_limits_missing:
          "Fysieke batterijlimieten ontbreken in de Planning Input",
        daily_tariff_price_coverage_incomplete:
          "Wacht op volledige Nordpool-prijzen voor de komende 24 uur",
      };
      const observerRows = [
        ["Status", observer.status],
        ["Reden", observerReasonLabels[observer.reason] ?? observer.reason],
        ["Snapshot", observer.snapshot_id],
        ["Vergelijkbaarheid", aligned
          ? "Exact dezelfde Planning Input"
          : "Wacht op dezelfde Planning Input-snapshot"],
        ["Doel", observer.objective],
        ["Richting", observer.direction],
        ["Beste observatie(s)", best.map((item) => item.candidate_id).join(", ")],
        ["Rekentijd", Number.isFinite(Number(observer.duration_ms))
          ? `${formatDutchNumber(Number(observer.duration_ms))} ms`
          : null],
      ];
      const observerCard = comparisonCard(
        "Etmaalsimulatie · observer-only",
        "daily-reference",
        observerRows
      );
      observerCard.querySelector("h3").className = "daily-reference-label";
      if (!aligned && observer.snapshot_id) {
        const warning = document.createElement("p");
        warning.className = "daily-lineage-warning";
        warning.textContent =
          "Deze uitkomst hoort nog bij de vorige snapshot en wordt niet als " +
          "eerlijke winnaarvergelijking beschouwd.";
        observerCard.append(warning);
      }
      for (const candidate of best) {
        const details = document.createElement("details");
        details.className = "technical-details";
        const summary = document.createElement("summary");
        summary.textContent = [
          displayValue(candidate.family),
          Number.isFinite(Number(candidate.worst_case_financial_result_eur))
            ? `€ ${formatDutchNumber(Number(
                candidate.worst_case_financial_result_eur
              ))}`
            : "—",
          formatConfidence(candidate.minimum_confidence),
        ].join(" · ");
        details.append(summary);
        const schedule = document.createElement("p");
        schedule.textContent = (candidate.intent_intervals ?? [])
          .filter((interval) => interval.intent !== "household_support_only")
          .map((interval) => [
            interval.intent,
            interval.starts_at,
            interval.ends_at,
          ].map(displayValue).join(" · "))
          .join(" | ") || "Alleen huishoudondersteuning nodig.";
        details.append(schedule);
        observerCard.append(details);
      }
      grid.append(observerCard);
      container.append(grid);
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
      movePanelContent("planning-status", "planning");
      movePanelContent("daily-observer-comparison", "planning");
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

    function renderStorageModeTransitionHistory(events) {
      const container = element("storage-mode-transition-history");
      container.replaceChildren();
      if (!Array.isArray(events) || events.length === 0) {
        container.textContent =
          "Nog geen door PicoT uitgevoerde moduswissels vastgelegd.";
        return;
      }
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headerRow = document.createElement("tr");
      for (const label of [
        "Moment", "Van", "Naar", "Reden", "Confidence", "Run"
      ]) {
        const cell = document.createElement("th");
        cell.textContent = label;
        headerRow.append(cell);
      }
      head.append(headerRow);
      const body = document.createElement("tbody");
      for (const event of [...events].reverse()) {
        const row = document.createElement("tr");
        const occurredAt = new Date(event.occurred_at);
        const confidence = Number(event.confidence);
        const values = [
          Number.isNaN(occurredAt.getTime())
            ? displayValue(event.occurred_at)
            : occurredAt.toLocaleString("nl-NL"),
          displayValue(event.previous_vendor_mode),
          displayValue(event.requested_vendor_mode),
          displayValue(event.reason),
          Number.isFinite(confidence)
            ? `${Math.round(confidence * 100)}%`
            : "—",
          displayValue(event.run_id),
        ];
        for (const value of values) {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.append(cell);
        }
        body.append(row);
      }
      table.append(head, body);
      container.append(table);
    }

    function renderPlanningIncidentHistory(events) {
      const container = element("planning-incident-history");
      const signature = JSON.stringify(events);
      if (signature === planningIncidentHistorySignature) return;
      const openIncidentKeys = new Set(
        [...container.querySelectorAll("details[open]")]
          .map((details) => details.dataset.incidentKey)
          .filter(Boolean)
      );
      container.replaceChildren();
      planningIncidentHistorySignature = signature;
      if (!Array.isArray(events) || events.length === 0) {
        container.textContent = "Nog geen fallbackincidenten vastgelegd.";
        return;
      }
      for (const incident of [...events].reverse()) {
        const details = document.createElement("details");
        const incidentKey = [
          incident.incident_id,
          incident.event,
          incident.captured_at_utc,
          incident.run_id,
        ].map(displayValue).join("|");
        details.dataset.incidentKey = incidentKey;
        details.open = openIncidentKeys.has(incidentKey);
        const summary = document.createElement("summary");
        const moment = new Date(incident.captured_at_local);
        summary.textContent = [
          Number.isNaN(moment.getTime())
            ? displayValue(incident.captured_at_local)
            : moment.toLocaleString("nl-NL"),
          displayValue(incident.event),
          displayValue(incident.reason),
        ].join(" — ");
        details.append(summary);
        for (const poll of incident.polls ?? []) {
          const heading = document.createElement("h4");
          heading.textContent = [
            displayValue(poll.captured_at_local),
            displayValue(poll.run_id),
          ].join(" · ");
          details.append(heading);
          const table = document.createElement("table");
          const body = document.createElement("tbody");
          for (const entity of poll.entities ?? []) {
            const row = document.createElement("tr");
            for (const value of [
              entity.entity_id,
              entity.state,
              entity.unit,
              entity.availability,
              entity.last_updated_at,
            ]) {
              const cell = document.createElement("td");
              cell.textContent = displayValue(value);
              row.append(cell);
            }
            body.append(row);
          }
          table.append(body);
          details.append(table);
        }
        container.append(details);
      }
    }

    async function loadPlanningIncidentHistory() {
      try {
        const response = await fetch("api/diagnostics/incidents", {
          cache: "no-store"
        });
        if (!response.ok) return;
        renderPlanningIncidentHistory(await response.json());
      } catch (_error) {
        // The main dashboard remains usable when no incident file exists.
      }
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
        planningInput?.attributes?.pv_interval_deviations ?? [],
        view.pv_energy_timeline ?? { intervals: [] },
        view.power_history ?? { pv_actual_display_points: [] },
      );
      renderPowerHistory(view.power_history ?? {
        available: false,
        status: "unavailable",
        error: null,
        starts_at: null,
        ends_at: null,
        series: [],
      });
      renderSelfConsumptionHistory(view.self_consumption_history ?? {
        available: false,
        status: "unavailable",
        error: null,
        starts_at: null,
        ends_at: null,
        series: [],
      });
      renderStorageModeTransitionHistory(
        view.storage_mode_transition_history ?? []
      );
      loadPlanningIncidentHistory();
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
      renderPlanningStatus(view.planning_status);
      renderDailyObserverComparison(view);
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
    element("reset-planning").addEventListener("click", resetPlanning);
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
        self._daily_observer_comparison: dict[str, object] | None = None
        self._revision = 0
        self._reset_storage_mode_override: (
            Callable[[str], dict[str, object]] | None
        ) = None
        self._reset_planning: Callable[[str], dict[str, object]] | None = None
        self._diagnostic_paths: tuple[Path, ...] = ()
        self._incident_history_path: Path | None = None

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
        if self._daily_observer_comparison is not None:
            view["daily_observer_comparison"] = dict(
                self._daily_observer_comparison
            )
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

    def publish_power_history(
        self,
        power_history: PowerHistorySnapshot,
    ) -> None:
        """Refresh observer charts without running or replacing the Planner."""

        history_view = _power_history_view(power_history)
        self_consumption_view = _self_consumption_history_view(power_history)
        with self._condition:
            if self._latest_json is None:
                return
            latest: object = json.loads(self._latest_json)
            if not isinstance(latest, dict):
                raise TypeError("latest web view must be an object")
            latest["power_history"] = history_view
            latest["self_consumption_history"] = self_consumption_view
            self._replace_latest_locked(latest)

    def publish_daily_observer_comparison(
        self,
        comparison: dict[str, object],
    ) -> None:
        """Overlay a passive daily result without running the Planner."""
        copied: object = json.loads(json.dumps(comparison))
        if not isinstance(copied, dict):
            raise TypeError("daily observer comparison must be an object")
        if (
            copied.get("observer_only") is not True
            or copied.get("selection_permitted") is not False
            or copied.get("commitment_permitted") is not False
        ):
            raise ValueError("daily dashboard comparison must remain passive")
        with self._condition:
            self._daily_observer_comparison = copied
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

    def set_planning_reset(
        self,
        reset: Callable[[str], dict[str, object]],
    ) -> None:
        """Register the explicit manual planning-reset authority."""

        with self._lock:
            self._reset_planning = reset

    def planning_reset(self) -> Callable[[str], dict[str, object]] | None:
        with self._lock:
            return self._reset_planning

    def set_diagnostic_paths(
        self,
        paths: tuple[Path, ...],
        *,
        incident_history_path: Path,
    ) -> None:
        """Register the fixed runtime export allow-list before serving."""
        with self._lock:
            self._diagnostic_paths = paths
            self._incident_history_path = incident_history_path

    def diagnostic_paths(self) -> tuple[Path, ...]:
        with self._lock:
            return self._diagnostic_paths

    def incident_history_path(self) -> Path | None:
        with self._lock:
            return self._incident_history_path


def create_web_server(
    store: WebViewStore,
    *,
    host: str,
    port: int,
    reset_storage_mode_override: (
        Callable[[str], dict[str, object]] | None
    ) = None,
    reset_planning: Callable[[str], dict[str, object]] | None = None,
) -> ThreadingHTTPServer:
    """Create, but do not start, the read-only observer HTTP server."""

    class Handler(BaseHTTPRequestHandler):
        def handle_one_request(self) -> None:
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

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

        def _send_download(
            self,
            body: bytes,
            *,
            content_type: str,
            filename: str,
        ) -> None:
            self.send_response(int(HTTPStatus.OK))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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

            if path == "/api/diagnostics/incidents":
                incident_path = store.incident_history_path()
                overview = (
                    incident_overview(incident_path)
                    if incident_path is not None
                    else []
                )
                self._send_json(
                    HTTPStatus.OK,
                    json.dumps(overview, separators=(",", ":")),
                )
                return

            if path == "/downloads/planning-incidents.jsonl":
                incident_path = store.incident_history_path()
                if incident_path is None or not incident_path.is_file():
                    self._send_json(
                        HTTPStatus.NOT_FOUND,
                        '{"status":"incident_history_not_found"}',
                    )
                    return
                self._send_download(
                    incident_path.read_bytes(),
                    content_type="application/x-ndjson",
                    filename=incident_path.name,
                )
                return

            if path == "/downloads/picot-diagnostics.zip":
                self._send_download(
                    diagnostic_zip(store.diagnostic_paths()),
                    content_type="application/zip",
                    filename="picot-diagnostics.zip",
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
            if path not in {
                "/api/storage-mode-override/reset",
                "/api/planning/reset",
            }:
                self._reject_write()
                return
            reset = (
                reset_planning or store.planning_reset()
                if path == "/api/planning/reset"
                else reset_storage_mode_override
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


def _build_planning_status(run: CanonicalPipelineRun) -> dict[str, object]:
    """Expose one pipeline run as facts without deriving new conclusions."""
    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in run.candidate_set.candidates
    }
    outcomes_by_candidate = {
        outcome.candidate_id: outcome
        for outcome in run.outcomes.outcomes
    }
    winning_candidate_id = run.evaluation.winning_candidate_id
    winning_candidate = (
        candidates_by_id.get(winning_candidate_id)
        if winning_candidate_id is not None
        else None
    )
    winning_outcome = (
        outcomes_by_candidate.get(winning_candidate_id)
        if winning_candidate_id is not None
        else None
    )
    winning_execution_plans = tuple(sorted(
        (
            plan
            for plan in run.execution_plan_set.plans
            if plan.winning_candidate_id == winning_candidate_id
        ),
        key=lambda plan: (plan.valid_from, plan.valid_until, plan.plan_id),
    ))
    requirement = next(
        iter(run.candidate_set.storage_requirements),
        None,
    )
    storage_states_by_id = {
        state.storage_state_id: state
        for state in run.planning_input.current_storage_states
    }
    initial_storage_state = (
        storage_states_by_id.get(requirement.storage_state_id)
        if requirement is not None
        else None
    )
    initial_storage_energy_wh = (
        initial_storage_state.current_stored_energy_wh
        if initial_storage_state is not None
        else None
    )
    energy_to_target_wh = (
        max(0.0, requirement.required_energy_wh - initial_storage_energy_wh)
        if requirement is not None and initial_storage_energy_wh is not None
        else None
    )
    regime = run.planning_input.household_planning_regime
    due_plan = next(
        (
            plan
            for plan in run.execution_plan_set.plans
            if plan.valid_from <= run.planning_input.captured_at < plan.valid_until
        ),
        None,
    )
    next_plan = min(
        (
            plan
            for plan in run.execution_plan_set.plans
            if plan.valid_from > run.planning_input.captured_at
        ),
        key=lambda plan: plan.valid_from,
        default=None,
    )
    applicable_plan = due_plan or next_plan
    fallback_active = run.evaluation.status == "fallback_active"
    return {
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "captured_at": run.planning_input.captured_at.isoformat(),
        "valid_until": (
            run.planning_input.horizon_end.isoformat()
            if run.planning_input.horizon_end is not None
            else None
        ),
        "attention": {
            "required": fallback_active,
            "code": (
                "fallback_no_actionable_plan" if fallback_active else None
            ),
            "title": (
                "Geen uitvoerbaar plan beschikbaar"
                if fallback_active
                else None
            ),
            "message": (
                "De veilige terugvalmodus blijft actief; aandacht vereist."
                if fallback_active
                else None
            ),
        },
        "strategy": {
            "status": regime.regime if regime is not None else "not_available",
            "reason": regime.reason if regime is not None else "not_available",
            "objective_order": (
                list(regime.objective_order) if regime is not None else []
            ),
            "forecast_confidence": (
                regime.forecast_confidence if regime is not None else None
            ),
            "forecast_confidence_available": (
                regime.forecast_confidence_available
                if regime is not None
                else False
            ),
            "forecast_confidence_method_version": (
                regime.forecast_confidence_method_version
                if regime is not None
                else None
            ),
            "storage_target_at_risk": (
                regime.storage_target_at_risk if regime is not None else None
            ),
        },
        "decision": {
            "status": run.evaluation.status,
            "candidate_family": (
                winning_candidate.family
                if winning_candidate is not None and not fallback_active
                else None
            ),
            "reason": run.evaluation.reason,
            "decisive_step": run.evaluation.decisive_step,
            "confidence": (
                winning_outcome.confidence
                if winning_outcome is not None
                else None
            ),
        },
        "storage_target": {
            "required_energy_wh": (
                requirement.required_energy_wh
                if requirement is not None
                else None
            ),
            "required_soc": (
                requirement.required_soc if requirement is not None else None
            ),
            "required_by": (
                requirement.required_by.isoformat()
                if requirement is not None
                else None
            ),
            "reason": requirement.reason if requirement is not None else None,
            "confidence": (
                requirement.confidence if requirement is not None else None
            ),
            "requirement_satisfied": (
                winning_outcome.requirement_satisfied
                if winning_outcome is not None
                else None
            ),
            "projected_energy_wh": (
                winning_outcome.storage_energy_at_requirement_wh
                if winning_outcome is not None
                else None
            ),
            "pv_contribution_wh": (
                winning_outcome.pv_storage_contribution_wh
                if winning_outcome is not None
                else None
            ),
            "grid_contribution_wh": (
                winning_outcome.grid_storage_contribution_wh
                if winning_outcome is not None
                else None
            ),
        },
        "execution": {
            "status": run.execution_record.status,
            "reason": run.execution_record.reason,
            "timing": (
                "active" if due_plan is not None
                else "scheduled" if next_plan is not None
                else "not_available"
            ),
            "valid_from": (
                applicable_plan.valid_from.isoformat()
                if applicable_plan is not None
                else None
            ),
            "valid_until": (
                applicable_plan.valid_until.isoformat()
                if applicable_plan is not None
                else None
            ),
            "planned_primitive": (
                applicable_plan.planned_primitive.value
                if applicable_plan is not None
                else None
            ),
            "planned_vendor_mode": (
                applicable_plan.planned_vendor_mode
                if applicable_plan is not None
                else None
            ),
            "primitive_status": run.primitive_boundary.status,
            "blockers": list(run.primitive_boundary.blockers),
        },
        "chosen_plan": {
            "candidate_id": (
                winning_candidate.candidate_id
                if winning_candidate is not None and not fallback_active
                else None
            ),
            "energy_path_id": (
                winning_candidate.energy_path_id
                if winning_candidate is not None and not fallback_active
                else None
            ),
            "family": (
                winning_candidate.family
                if winning_candidate is not None and not fallback_active
                else None
            ),
            "decisive_step": (
                run.evaluation.decisive_step if not fallback_active else None
            ),
            "reason": run.evaluation.reason if not fallback_active else None,
            "charge_window_starts_at": (
                winning_outcome.charge_window_starts_at.isoformat()
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "charge_window_ends_at": (
                winning_outcome.charge_window_ends_at.isoformat()
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "required_energy_wh": (
                winning_outcome.required_energy_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "initial_storage_energy_wh": (
                initial_storage_energy_wh if not fallback_active else None
            ),
            "energy_to_target_wh": (
                energy_to_target_wh if not fallback_active else None
            ),
            "storage_energy_at_window_start_wh": (
                winning_outcome.storage_energy_at_window_start_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "projected_storage_use_before_window_wh": (
                winning_outcome.projected_storage_use_before_window_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "required_storage_addition_wh": (
                winning_outcome.required_storage_addition_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "pv_forecast_basis": (
                winning_outcome.pv_forecast_basis
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "storage_energy_at_window_end_wh": (
                winning_outcome.storage_energy_at_window_end_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "storage_energy_at_requirement_wh": (
                winning_outcome.storage_energy_at_requirement_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "charge_target_satisfied": (
                winning_outcome.charge_target_satisfied
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "reserve_satisfied": (
                winning_outcome.reserve_satisfied
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "reserve_energy_required_wh": (
                winning_outcome.reserve_energy_required_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "pv_contribution_wh": (
                winning_outcome.pv_storage_contribution_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "grid_contribution_wh": (
                winning_outcome.grid_storage_contribution_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "conversion_losses_wh": (
                winning_outcome.conversion_losses_wh
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "requirement_satisfied": (
                winning_outcome.requirement_satisfied
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "recoverability": (
                winning_outcome.recoverability
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "confidence": (
                winning_outcome.confidence
                if winning_outcome is not None and not fallback_active
                else None
            ),
            "requirement_confidence": (
                requirement.confidence
                if requirement is not None and not fallback_active
                else None
            ),
            "confidence_assessment": (
                {
                    "result": winning_outcome.confidence_assessment.result,
                    "limiting_component": (
                        winning_outcome.confidence_assessment.limiting_component
                    ),
                    "method_version": (
                        winning_outcome.confidence_assessment.method_version
                    ),
                    "components": [
                        {
                            "name": component.name,
                            "value": component.value,
                            "method_version": component.method_version,
                            "evidence_ids": list(component.evidence_ids),
                        }
                        for component in (
                            winning_outcome.confidence_assessment.components
                        )
                    ],
                }
                if winning_outcome is not None
                and winning_outcome.confidence_assessment is not None
                and not fallback_active
                else None
            ),
            "execution_segments": [
                {
                    "plan_id": plan.plan_id,
                    "lifecycle_status": plan.lifecycle_status,
                    "planned_vendor_mode": segment.planned_vendor_mode,
                    "starts_at": segment.starts_at.isoformat(),
                    "ends_at": segment.ends_at.isoformat(),
                    "primitive": segment.primitive.value,
                    "purpose": segment.purpose,
                    "charge_source_policy": (
                        segment.charge_source_policy.value
                        if segment.charge_source_policy is not None
                        else None
                    ),
                }
                for plan in winning_execution_plans
                for segment in plan.segments
            ] if not fallback_active else [],
        },
        "alternatives": [
            {
                "candidate_id": candidate.candidate_id,
                "energy_path_id": candidate.energy_path_id,
                "family": candidate.family,
                "selected": (
                    not fallback_active
                    and
                    candidate.candidate_id
                    == run.evaluation.winning_candidate_id
                ),
                "charge_window_starts_at": (
                    outcome.charge_window_starts_at.isoformat()
                    if outcome is not None
                    else None
                ),
                "charge_window_ends_at": (
                    outcome.charge_window_ends_at.isoformat()
                    if outcome is not None
                    else None
                ),
                "storage_energy_at_window_end_wh": (
                    outcome.storage_energy_at_window_end_wh
                    if outcome is not None
                    else None
                ),
                "storage_energy_at_requirement_wh": (
                    outcome.storage_energy_at_requirement_wh
                    if outcome is not None
                    else None
                ),
                "requirement_satisfied": (
                    outcome.requirement_satisfied
                    if outcome is not None
                    else None
                ),
                "charge_target_satisfied": (
                    outcome.charge_target_satisfied
                    if outcome is not None
                    else None
                ),
                "reserve_satisfied": (
                    outcome.reserve_satisfied
                    if outcome is not None
                    else None
                ),
                "recoverability": (
                    outcome.recoverability if outcome is not None else None
                ),
                "confidence": (
                    outcome.confidence if outcome is not None else None
                ),
                "pv_contribution_wh": (
                    outcome.pv_storage_contribution_wh
                    if outcome is not None
                    else None
                ),
                "grid_contribution_wh": (
                    outcome.grid_storage_contribution_wh
                    if outcome is not None
                    else None
                ),
            }
            for candidate in run.candidate_set.candidates
            for outcome in (outcomes_by_candidate.get(candidate.candidate_id),)
        ],
    }


def build_web_view(
    run: CanonicalPipelineRun,
    projection: Projection,
    *,
    display_price_points: tuple[PriceForecastPoint, ...] | None = None,
    power_history: PowerHistorySnapshot | None = None,
    storage_mode_transitions: tuple[StorageModeTransitionEvent, ...] = (),
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

    power_history_view = _power_history_view(power_history)

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
        "planning_status": _build_planning_status(run),
        "plan_explanation": _build_plan_explanation(run),
        "price_timeline": price_timeline,
        "pv_energy_timeline": pv_energy_timeline,
        "household_load_forecast": household_load_forecast,
        "power_history": power_history_view,
        "self_consumption_history": _self_consumption_history_view(power_history),
        "storage_mode_transition_history": [
            {
                "event_id": event.event_id,
                "occurred_at": event.occurred_at.isoformat(),
                "previous_vendor_mode": event.previous_vendor_mode,
                "requested_vendor_mode": event.requested_vendor_mode,
                "source": event.source,
                "reason": event.reason,
                "confidence": event.confidence,
                "run_id": event.run_id,
                "snapshot_id": event.snapshot_id,
                "evaluation_id": event.evaluation_id,
                "plan_id": event.plan_id,
                "application_id": event.application_id,
            }
            for event in storage_mode_transitions
        ],
    }
