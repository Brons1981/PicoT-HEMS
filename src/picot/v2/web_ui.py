"""Pure read-only projection of canonical PicoT v2 records.

ADR-030 owns projected Energy States; the UI presents them without recalculation.
See ADR-017, ADR-030 and the frozen canonical pipeline contract.
"""

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

from picot.diagnostic_export_job import DiagnosticExportJob
from picot.domain.energy_path import PathSegment
from picot.v2.contracts import (
    CanonicalPipelineRun,
    DelegatedStorageCandidateOutcome,
    MepCandidateOutcome,
    PriceForecastPoint,
)
from picot.v2.diagnostic_downloads import diagnostic_zip, incident_overview
from picot.v2.household_calendar_history import CALENDAR_REPORT_PATH, calendar_dashboard_view
from picot.v2.plan_decision_cache import PlanDecisionCache, retain_plan_decision
from picot.v2.plan_decision_explanation import build_plan_decision
from picot.v2.plan_narrative import build_plan_narrative
from picot.v2.power_history import PowerHistorySeries, PowerHistorySnapshot
from picot.v2.price_plan_reference import PricePlanReference
from picot.v2.projection import Projection, project_market_revision_comparison
from picot.v2.recovery_messages import recovery_details, recovery_message
from picot.v2.soc_projection_cache import SOCDisplayHistory, SOCProjectionCache
from picot.v2.standby_explanation import standby_comparison
from picot.v2.startup_progress import StartupProgress
from picot.v2.storage_mode_transition_history import StorageModeTransitionEvent

POWER_HISTORY_DISPLAY_INTERVAL = timedelta(minutes=5)
SELF_CONSUMPTION_DISPLAY_INTERVAL = timedelta(minutes=10)
PV_ACTUAL_DISPLAY_INTERVAL = timedelta(minutes=2)
MAX_DISPLAY_EVIDENCE_IDS = 16
MAX_WEB_VIEW_CHARACTERS = 8_000_000


class _DisplayPowerPoint(TypedDict):
    sampled_at: str
    power_w: float
    coverage_ratio: float
    derived_from_evidence_ids: list[str]


def _bounded_evidence_ids(values: tuple[str, ...]) -> list[str]:
    """Keep dashboard provenance useful without copying unbounded telemetry IDs."""
    unique = tuple(dict.fromkeys(values))
    if len(unique) <= MAX_DISPLAY_EVIDENCE_IDS:
        return list(unique)
    edge = MAX_DISPLAY_EVIDENCE_IDS // 2
    return [*unique[:edge], *unique[-edge:]]


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
            while point_index < len(points) and points[point_index].sampled_at <= bucket_start:
                held_point = points[point_index]
                point_index += 1
            current = held_point
            cursor = bucket_start if current is not None else None
            weighted_power_seconds = 0.0
            covered_seconds = 0.0
            used_evidence: list[str] = []
            if current is not None:
                used_evidence.append(current.evidence_id)
            while point_index < len(points) and points[point_index].sampled_at < bucket_end:
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
            average = weighted_power_seconds / covered_seconds if covered_seconds > 0 else None
            evidence_ids = tuple(dict.fromkeys(used_evidence))
        else:
            while point_index < len(points) and points[point_index].sampled_at < bucket_start:
                point_index += 1
            bucket_points = []
            while point_index < len(points) and points[point_index].sampled_at < bucket_end:
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
            result.append(
                {
                    "sampled_at": (bucket_start + (bucket_end - bucket_start) / 2).isoformat(),
                    "power_w": average,
                    "coverage_ratio": min(1.0, covered_seconds / bucket_seconds),
                    "derived_from_evidence_ids": _bounded_evidence_ids(evidence_ids),
                }
            )
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
                "missing_roles:" + ",".join(missing_roles) if missing_roles else power_history.error
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
    pv_by_time = {point["sampled_at"]: point for point in display_by_role["pv_generation"]}
    export_by_time = {point["sampled_at"]: point for point in display_by_role["grid_export"]}
    local_pv_points: list[_DisplayPowerPoint] = []
    for sampled_at, pv_point in pv_by_time.items():
        export_point = export_by_time.get(sampled_at)
        if export_point is None:
            continue
        pv_power_w = max(0.0, pv_point["power_w"])
        grid_export_w = max(0.0, export_point["power_w"])
        local_pv_points.append(
            {
                "sampled_at": sampled_at,
                "power_w": min(pv_power_w, max(0.0, pv_power_w - grid_export_w)),
                "coverage_ratio": min(
                    pv_point["coverage_ratio"],
                    export_point["coverage_ratio"],
                ),
                "derived_from_evidence_ids": list(
                    dict.fromkeys(
                        [
                            *pv_point["derived_from_evidence_ids"],
                            *export_point["derived_from_evidence_ids"],
                        ]
                    )
                ),
            }
        )

    current_pv_w = max(0.0, by_role["pv_generation"].points[-1].power_w)
    current_export_w = max(0.0, by_role["grid_export"].points[-1].power_w)
    current_import_w = max(0.0, by_role["grid_import"].points[-1].power_w)

    return {
        "available": bool(local_pv_points),
        "status": "available" if local_pv_points else "empty",
        "error": None,
        "starts_at": power_history.starts_at.isoformat(),
        "ends_at": power_history.ends_at.isoformat(),
        "display_interval_seconds": int(SELF_CONSUMPTION_DISPLAY_INTERVAL.total_seconds()),
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
        "available": power_history is not None and power_history.status == "available",
        "status": power_history.status if power_history is not None else "unavailable",
        "error": power_history.error if power_history is not None else None,
        "starts_at": starts_at.isoformat() if starts_at is not None else None,
        "ends_at": ends_at.isoformat() if ends_at is not None else None,
        "method_version": (power_history.method_version if power_history is not None else None),
        "display_aggregation": "five_minute_average",
        "display_interval_seconds": int(POWER_HISTORY_DISPLAY_INTERVAL.total_seconds()),
        "display_curve": "linear_between_bucket_averages",
        "pv_actual_display_interval_seconds": int(PV_ACTUAL_DISPLAY_INTERVAL.total_seconds()),
        "pv_actual_display_points": next(
            (
                _power_history_display_points(
                    series,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    interval=PV_ACTUAL_DISPLAY_INTERVAL,
                )
                for series in power_history.series
                if series.role == "pv_generation"
            ),
            [],
        )
        if power_history is not None and starts_at is not None and ends_at is not None
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
      color-scheme: light;
      font-family: Inter, system-ui, sans-serif;
      background: #f4f6f8;
      color: #253749;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: #f4f6f8; }
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
    .muted { color: #647588; }
    .dashboard-tabs {
      display: flex;
      gap: 8px;
      margin: 0 0 18px;
      overflow-x: auto;
      scrollbar-width: thin;
    }
    #household-calendar-history table { width: 100%; border-collapse: collapse; }
    #household-calendar-history th, #household-calendar-history td {
      padding: 8px; border-bottom: 1px solid #e0e6ec; text-align: left;
      white-space: nowrap;
    }
    .tab-button {
      border: 1px solid #386f96;
      border-radius: 8px;
      padding: 9px 13px;
      background: #ffffff;
      color: #315f83;
      cursor: pointer;
      white-space: nowrap;
    }
    .tab-button[aria-selected="true"] {
      border-color: #5db9f3;
      background: #e6eff6;
      color: #ffffff;
    }
    .tab-panel[hidden] { display: none; }
    .empty-panel {
      padding: 14px;
      border: 1px solid #e0e6ec;
      border-radius: 12px;
      background: #ffffff;
      color: #647588;
    }
    .strategy-rules {
      display: grid;
      gap: 14px;
      max-width: 760px;
      padding: 18px;
      border: 1px solid #e0e6ec;
      border-radius: 12px;
      background: #ffffff;
    }
    .strategy-rule {
      display: grid;
      gap: 6px;
    }
    .strategy-rule-line {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
    }
    .strategy-rule input[type="number"] {
      width: 90px;
      padding: 7px;
      border: 1px solid #386f96;
      border-radius: 7px;
      background: #f4f7f9;
      color: #253749;
    }
    .strategy-rules button {
      justify-self: start;
      padding: 9px 14px;
      border: 1px solid #5db9f3;
      border-radius: 8px;
      background: #e6eff6;
      color: #fff;
      cursor: pointer;
    }
    .energy-device-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin: 14px 0;
    }
    .energy-device-card {
      padding: 14px;
      border: 1px solid #334155;
      border-radius: 10px;
      background: #ffffff;
    }
    .energy-device-card[data-selected="true"] { border-color: #b96cff; }
    .energy-device-placement-list { display: grid; gap: 8px; margin-top: 14px; }
    .observer {
      padding: 8px 12px;
      border: 1px solid #386f96;
      border-radius: 999px;
      background: #ffffff;
      color: #315f83;
      white-space: nowrap;
    }
    .metadata {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .metric, .source-card, .stage-card, .timeline-panel, .price-panel,
    .zendure-now {
      border: 1px solid #e0e6ec;
      border-radius: 12px;
      background: #ffffff;
    }
    .metric { padding: 12px; }
    .financial-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 12px;
    }
    .financial-week-nav { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
    .financial-week-nav h3 { margin-right: auto; }
    .financial-quality-marker { padding: 0 6px; margin-left: 6px; border-radius: 50%;
      color: #f5c542; background: transparent; min-width: 24px; min-height: 24px; }
    .financial-week-sources { padding: 16px; margin: 18px 0; }
    .financial-source-day { display: grid; align-items: center; gap: 10px; margin: 12px 0;
      grid-template-columns: 30px minmax(30px, 1fr) 165px 24px; }
    .financial-week-nav button, .financial-week-nav select { padding: 7px; background: #ffffff;
      color: inherit; border: 1px solid #334155; border-radius: 6px; }
    .financial-week-nav button:disabled { opacity: .45; }
    #financial-results > .financial-grid .value { font-size: 24px; font-weight: 600; }
    @media (max-width: 600px) {
      .financial-source-day { grid-template-columns: 24px minmax(30px, 1fr) 85px 24px; gap: 6px; }
    }
    .financial-source-day > span:first-child { width: 30px; }
    .financial-source-bar { display: flex; flex: 1; height: 20px; min-width: 60px; }
    #financial-results > details { margin-top: 18px; }
    #financial-results summary { cursor: pointer; padding: 10px 0; }
    /* Keep the financial overview light without changing other dashboard tabs. */
    #financial-results { color-scheme: light; background: #f6f7f9; color: #243245;
      padding: 20px; border: 1px solid #dde3ea; border-radius: 14px; }
    #financial-results .metric, #financial-results .timeline-panel,
    #financial-results .empty-panel { background: #ffffff; border-color: #dde3ea; }
    #financial-results .muted, #financial-results th,
    #financial-results .financial-equation-symbol { color: #586678; }
    #financial-results th, #financial-results td { border-color: #dde3ea; }
    #financial-results .financial-week-nav button,
    #financial-results .financial-week-nav select { background: #ffffff; border-color: #c5ced9; }
    #financial-results .financial-quality-marker { color: #8a5700; border: 1px solid #a56c12; }
    #financial-results .value { color: #243245; }
    #financial-results .financial-positive { color: #19723b; }
    #financial-results .financial-negative { color: #b32d40; }
    #financial-results .financial-donut::after { background: #ffffff; }
    #financial-results .payback-track { background: #e1e7ee; }
    #financial-results :focus-visible { outline: 2px solid #245d9b; outline-offset: 3px; }
    @media (max-width: 600px) { #financial-results { padding: 12px; } }
    .financial-positive { color: #28633d; }
    .financial-negative { color: #a72d43; }
    .financial-source-panel {
      display: grid;
      grid-template-columns: minmax(190px, 260px) minmax(260px, 1fr);
      gap: 22px;
      align-items: center;
      margin-top: 12px;
      padding: 16px;
    }
    .financial-donut {
      position: relative;
      width: min(220px, 70vw);
      aspect-ratio: 1;
      margin: 0 auto;
      border-radius: 50%;
    }
    .financial-donut::after {
      content: "";
      position: absolute;
      inset: 24%;
      border-radius: 50%;
      background: #ffffff;
    }
    .financial-donut-center {
      position: absolute;
      inset: 30%;
      z-index: 1;
      display: grid;
      place-content: center;
      text-align: center;
    }
    .financial-source-legend { display: grid; gap: 10px; }
    .financial-source-row {
      display: grid;
      grid-template-columns: 12px minmax(100px, 1fr) auto;
      gap: 10px;
      align-items: center;
    }
    .financial-source-swatch {
      width: 12px; height: 12px; border-radius: 3px;
    }
    .financial-equation {
      display: grid;
      grid-template-columns: 1fr auto 1fr auto 1fr;
      gap: 10px;
      align-items: center;
      margin-top: 12px;
      padding: 14px;
    }
    .financial-equation-part { text-align: center; }
    .financial-equation-symbol { color: #647588; font-size: 1.4rem; }
    .payback-track {
      height: 14px; overflow: hidden; border-radius: 999px;
      background: #e0e6ec;
    }
    .payback-fill { height: 100%; background: #35a862; }
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
      background: #ffffff;
    }
    .daily-comparison-card.daily-reference {
      border-color: #a855f7;
      background: #f5effb;
      box-shadow: inset 4px 0 0 #c084fc;
    }
    .daily-reference-label { color: #744398; }
    .daily-comparison-card.market-daily {
      border-color: #2dd4bf;
      background: #edf7f6;
      box-shadow: inset 4px 0 0 #5eead4;
    }
    .daily-lineage-warning { color: #805516; }
    @media (max-width: 800px) {
      .financial-source-panel { grid-template-columns: 1fr; }
      .financial-equation { grid-template-columns: 1fr; }
      .financial-equation-symbol { transform: rotate(90deg); }
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
      background: #edf3f7;
      color: #315f83;
    }
    .status[data-state="error"] {
      background: #fdeef0;
      color: #a72d43;
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
      background: #eaf6ee;
      color: #28633d;
    }
    .source-status[data-state="unavailable"] {
      background: #fdeef0;
      color: #a72d43;
    }
    .source-status[data-state="unconfigured"] {
      background: #fff3de;
      color: #805516;
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
      color: #536779;
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
      background: #eaf6ee;
      color: #28633d;
    }
    .pipeline-health[data-health="fault"] {
      background: #fdeef0;
      color: #a72d43;
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
      background: #eaf6ee;
      color: #28633d;
    }
    dl { margin: 0; }
    .attribute {
      display: grid;
      grid-template-columns: minmax(110px, 0.8fr) minmax(0, 1.2fr);
      gap: 8px;
      padding: 6px 0;
      border-top: 1px solid #e0e6ec;
    }
    dt { color: #647588; overflow-wrap: anywhere; }
    dd { margin: 0; overflow-wrap: anywhere; }
    .technical-details {
      margin-top: 12px;
      border-top: 1px solid #e0e6ec;
      padding-top: 10px;
      color: #647588;
    }
    .technical-details summary { cursor: pointer; }
    .technical-details pre {
      max-height: 320px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: #536779;
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
    .energy-chart .grid-line { stroke: #e0e6ec; stroke-width: 1; }
    .energy-chart .axis-label { fill: #647588; font-size: 12px; }
    .energy-chart .forecast-range {
      fill: #ff9800;
      opacity: 0.24;
    }
    .energy-chart .forecast-line {
      fill: none;
      stroke: #ff9800;
      stroke-width: 1.4;
    }
    .energy-chart .forecast-lower-line,
    .energy-chart .forecast-upper-line {
      fill: none;
      stroke-width: 1;
      stroke-dasharray: 6 4;
    }
    .energy-chart .forecast-lower-line { stroke: #ef6c00; }
    .energy-chart .forecast-upper-line { stroke: #ffb74d; }
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
    .power-zero-line { stroke: #647588; stroke-width: 1.5; }
    .energy-chart-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-bottom: 10px;
      color: #647588;
    }
    .energy-chart-key {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    button.energy-chart-key {
      border: 1px solid #334155;
      border-radius: 999px;
      background: #ffffff;
      color: #647588;
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
    .power-current-value { color: #647588; font-size: 0.76rem; }
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
      background: #ffffff;
      color: #536779;
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
    }
    .energy-chart-swatch.forecast-lower {
      background: #ef6c00;
    }
    .energy-chart-swatch.forecast-upper {
      background: #ffb74d;
    }
    .price-panel { padding: 14px; overflow: hidden; }
    .price-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-bottom: 10px;
      color: #647588;
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
    .price-swatch.missing { background: #edf1f5; }
    .price-swatch.canonical-nom { background: #35a862; }
    .price-swatch.energy-device-placement { background: #b96cff; }
    .price-swatch.canonical-charge { background: #df5c57; }
    .price-swatch.canonical-trade { background: #aab2bd; }
    .price-swatch.canonical-support { background: #3994e6; }
    .price-swatch.canonical-standby { background: #e3aa45; }
    .price-swatch.optimized {
      background: repeating-linear-gradient(135deg, #b9c3cf 0 2px, #edf1f5 2px 6px);
    }
    .price-swatch.soc-actual { background: #c084fc; height: 3px; }
    .price-swatch.soc-projected { background: #ffd600; height: 3px; }
    .plan-history-panels {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
      gap: 16px;
    }
    .plan-history-panels article { min-width: 0; overflow-x: auto; }
    .plan-history-panels th, .plan-history-panels td { padding: 6px; text-align: left; }
    .plan-history-panels table { width: 100%; }
    .plan-history-panels code { overflow-wrap: anywhere; }
    .planner-window-summary {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 10px;
    }
    .planner-window-chip {
      border: 1px solid;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      font-weight: 700;
    }
    .planner-window-chip.canonical-nom {
      border-color: #35a862;
      color: #6fd68f;
    }
    .planner-window-chip.canonical-charge {
      border-color: #df5c57;
      color: #ff9b95;
    }
    .planner-window-chip.canonical-trade {
      border-color: #aab2bd;
      color: #d1d7de;
    }
    .planner-window-chip.canonical-support {
      border-color: #3994e6;
      color: #62b8f5;
    }
    .planner-window-chip.canonical-standby { border-color: #e3aa45; color: #f2c875; }
    .planner-window-chip.energy-device-placement {
      border-color: #b96cff;
      color: #e2c5ff;
    }
    .price-chart-scroll { overflow-x: auto; }
    .price-chart {
      display: block;
      width: 100%;
      min-width: 1000px;
      height: auto;
    }
    .price-chart .grid-line {
      stroke: #e0e6ec;
      stroke-width: 1;
    }
    .price-chart .zero-line {
      stroke: #647588;
      stroke-width: 1.5;
    }
    .price-chart .axis-label {
      fill: #647588;
      font-size: 12px;
    }
    .price-chart .missing-area { fill: #edf1f5; }
    .price-chart .price-bar {
      fill: #477fa8;
      opacity: 0.85;
    }
    .price-chart .price-bar.canonical-nom { stroke: #35a862; stroke-width: 3; }
    .price-chart .price-bar.canonical-charge { stroke: #df5c57; stroke-width: 3; }
    .price-chart .price-bar.canonical-trade { stroke: #aab2bd; stroke-width: 3; }
    .price-chart .price-bar.canonical-support { stroke: #3994e6; stroke-width: 3; }
    .price-chart .price-bar.canonical-standby { stroke: #e3aa45; stroke-width: 3; }
    .price-chart .price-bar.past { opacity: 0.30; }
    .price-chart .planner-window {
      pointer-events: none;
    }
    .price-chart .planner-window.canonical-nom { fill: #35a862; }
    .price-chart .planner-window.canonical-charge { fill: #df5c57; }
    .price-chart .planner-window.canonical-trade { fill: #aab2bd; }
    .price-chart .planner-window.canonical-support { fill: #3994e6; }
    .price-chart .planner-window.canonical-standby { fill: #e3aa45; }
    .price-chart .planner-window.energy-device-placement { fill: #b96cff; }
    .price-chart .soc-line { fill: none; stroke-width: 3; }
    .price-chart .soc-line.soc-actual { stroke: #c084fc; stroke-width: 3; }
    .price-chart .soc-line.soc-projected { stroke: #ffd600; }
    .price-chart .soc-point { fill: #253749; stroke: #ffffff; stroke-width: 2; }
    .price-chart .now-line {
      stroke: #253749;
      stroke-width: 1.5;
      stroke-dasharray: 3 4;
    }
    .price-chart .now-label {
      fill: #253749;
      font-size: 12px;
    }
    .price-chart .horizon-line {
      stroke: #805516;
      stroke-width: 2;
      stroke-dasharray: 6 5;
    }
    .price-chart .horizon-label {
      fill: #805516;
      font-size: 12px;
    }
    .price-detail {
      min-height: 22px;
      margin: 8px 0 0;
      color: #647588;
    }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid #e0e6ec;
      text-align: left;
      white-space: nowrap;
    }
    th { color: #647588; font-weight: 600; }
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

    .tab-button[aria-selected="true"] { color: #253749; border-color: #abc3d5; }
    .dashboard-tools { margin-bottom: 16px; color: #647588; }
    .dashboard-tools nav { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    #central-health[data-health="healthy"] { background: #eaf6ee; color: #28633d; }
    #central-health[data-health="fault"] { background: #fff3de; color: #805516; }
    .price-chart .soc-quarter-outline { fill: none; stroke: #becfc5; stroke-width: .7; }
    .price-chart .soc-quarter-fill { fill: #35a364; }
    .price-swatch.soc-actual { background: #35a364; height: 10px; }
    .price-chart.soc-chart { margin-top: 4px; }
    .price-chart text { fill: #536779; }
    .planner-details { margin: 10px 0; color: #647588; }

    .strategy-rules button { color: #253749; }
    .today-summary { display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
    .today-summary strong { display: block; font-size: 1.5rem; margin: 6px 0; }
    .today-summary small { display: block; color: #647588; }
    #central-health { padding: 10px 14px; border-radius: 10px; }
    #planning-reset { display:flex; flex-wrap:wrap; align-items:center; gap:12px; }
    #reset-planning { order:-1; background:#246b50; color:white;
      font-weight:700; padding:12px 18px; }
    .comparison-scroll { overflow-x:auto; }
    .comparison-chart { width:100%; min-width:680px; display:block; }
    .comparison-legend { display:flex; flex-wrap:wrap; gap:12px; }
    .comparison-legend span { padding-left:6px; }
    .comparison-differences { padding-left:22px; line-height:1.6; }
    #central-health p { margin:8px 0; overflow-wrap:anywhere; }
    [hidden] { display:none !important; }
  </style>
</head>
<body data-observer-only="true">
  <main>
    <header>
      <div>
        <h1>PicoT</h1>
        <p class="muted">Energie in overzicht · vandaag en morgen</p>
      </div>
      <div id="execution-mode" class="observer">Status wordt geladen</div>
    </header>

    <p id="dashboard-status" class="planning-attention" role="status" hidden></p>
    <p id="ev-storage-warning" class="planning-attention" role="alert" hidden></p>
    <p id="soc-reserve-status" role="status" hidden></p>

    <section id="planning-reset" class="status" aria-live="polite">
      <span id="planning-reset-result">
        Nieuwe planning maken vanaf actuele gegevens; oude plannen worden gearchiveerd.
      </span>
      <button id="reset-planning" type="button">
        Maak een nieuw plan
      </button>
    </section>

    <nav class="dashboard-tabs" aria-label="Dashboardweergave">
      <button class="tab-button" type="button" data-tab="planning"
        aria-selected="true">Vandaag</button>
      <button
        class="tab-button" type="button" data-tab="history"
        aria-selected="false"
      >Historie</button>
      <button
        class="tab-button" type="button" data-tab="financial"
        aria-selected="false"
      >Financieel</button>
    </nav>
    <div id="dashboard-tools" class="dashboard-tools">
      <nav aria-label="Aanvullende weergaven">
      <button
        class="tab-button" type="button" data-tab="strategy"
        aria-selected="false"
      >Strategie</button>
      <button
        class="tab-button" type="button" data-tab="devices"
        aria-selected="false"
      >Apparaten</button>
      <button
        class="tab-button" type="button" data-tab="technical"
        aria-selected="false"
      >Instellingen</button>
      </nav>
    </div>
    <section id="central-health" class="status" role="status">Status nog onbekend</section>
    <div id="today-summary" class="today-summary" aria-live="polite"></div>
    <section id="plan-decision" class="timeline-panel" aria-live="polite">
      Nog geen planbeslissing vastgelegd.
    </section>
    <section id="route-choice-panel" class="timeline-panel" hidden>
      <h2>Keuze voor deze laadopdracht</h2>
      <div id="route-choices"></div>
      <p id="route-choice-feedback" role="status" aria-live="polite"></p>
    </section>
    <section
      id="tab-overview" class="tab-panel" data-tab-panel="overview"
    ></section>
    <section
      id="tab-planning" class="tab-panel" data-tab-panel="planning" hidden
    ></section>
    <section
      id="tab-history" class="tab-panel" data-tab-panel="history" hidden
    >
      <h2>Huisverbruik per kalenderdag</h2>
      <p class="muted">
        Vergelijk maandag t/m zondag en werkdagen met weekenden. Deze registratie
        wordt opgebouwd naast de huidige planning. Alleen voldoende gemeten,
        afgesloten dagen tellen mee in de daggemiddelden.
      </p>
      <section id="household-calendar-history" class="timeline-panel" aria-live="polite">
        Kalenderhistorie wordt opgebouwd…
      </section>
      <h2>Schakelhistorie batterijmodus</h2>
      <label>Periode <select id="switch-history-period">
        <option value="today">Vandaag</option>
        <option value="all">Meer dagen · beschikbare historie</option>
      </select></label>
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
          <button id="diagnostic-export" type="button">Diagnose downloaden</button>
          <div id="diagnostic-export-status" role="status" aria-live="polite"></div>
          <progress id="diagnostic-export-progress" hidden
            aria-label="Voortgang diagnose"></progress>
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
      id="tab-financial" class="tab-panel" data-tab-panel="financial" hidden
    >
      <h2>Financieel resultaat</h2>
      <p class="muted">
        Achteraf berekend uit gemeten energiestromen en werkelijke
        kwartierprijzen. Deze administratie beïnvloedt geen PicoT-beslissing.
      </p>
      <div id="financial-results" aria-live="polite">
        Nog geen volledige financiële meetperiode beschikbaar.
      </div>
    </section>
    <section
      id="tab-strategy" class="tab-panel" data-tab-panel="strategy" hidden
    >
      <h2>Gebruikersregels</h2>
      <p class="muted">
        Deze regels begrenzen eerst de geldige plannen. Daarna kiest PicoT het
        financieel beste plan binnen die grenzen.
      </p>
      <form id="user-rules-form" class="strategy-rules">
        <label class="strategy-rule">
          <span class="strategy-rule-line">
            <strong>Beschikbare PV behouden bij netladen</strong>
            <input id="rule-preserve-pv" type="checkbox">
          </span>
          <span class="muted">
            Netenergie vult alleen het resterende opslagtekort; de omliggende
            basisstand blijft zonne-energie opvangen.
          </span>
        </label>
        <label class="strategy-rule">
          <span class="strategy-rule-line">
            <strong>Energiebelasting bij teruglevering verrekenen</strong>
            <input id="rule-saldering-tax" type="checkbox">
          </span>
          <span class="muted">
            Gebruik dit alleen zolang jouw resterende afname binnen de
            contractperiode nog saldering toestaat. Omschakelen laat PicoT
            dezelfde begrensde kandidaten opnieuw financieel beoordelen.
          </span>
        </label>
        <label class="strategy-rule">
          <span class="strategy-rule-line">
            <strong>Batterijcapaciteit voor handel per leveringsdag</strong>
            <span><input id="rule-trading-soc" type="number" min="0" max="100" step="1"> %</span>
          </span>
          <span id="rule-trading-limit" class="muted">
            Percentagepunten van de bruikbare batterijcapaciteit. Bij onvoldoende
            SOC wordt de opdracht overgeslagen. 0% schakelt nieuwe handel uit.
          </span>
        </label>
        <label class="strategy-rule">
          <strong>Minimale spread (€/kWh)</strong>
          <input id="rule-market-spread" type="number" min="0" step="any">
          <span class="muted">Leeg: nieuwe handel uit.
            Vergelijking met een fictief goedkoop laadvenster.</span>
        </label>
        <label class="strategy-rule">
          <span><input id="rule-market-recovery" type="checkbox">
            Extra nettomarge eisen</span>
          <span class="muted">Nieuwe handel wacht altijd op bekend herstel en een
            positief resultaat. Hiermee geldt ook de onderstaande minimummarge.</span>
        </label>
        <label class="strategy-rule">
          <strong>Minimale nettowinst bij herstel (€/export-kWh)</strong>
          <input id="rule-market-margin" type="number" min="0" step="0.001" value="0.05">
        </label>
        <button id="save-user-rules" type="submit">Regels toepassen</button>
        <span id="user-rules-status" class="muted" aria-live="polite"></span>
      </form>
    </section>
    <section
      id="tab-devices" class="tab-panel" data-tab-panel="devices" hidden
    >
      <h2>Energie-apparaatkaarten</h2>
      <p class="muted">
        Nieuwe kaarten uit PicoT Energy Devices verschijnen hier automatisch.
        Een kaart doet niets totdat je hem zelf op de tijdlijn plaatst. Deze
        eerste versie bewaart plaatsingen alleen ter observatie en verandert
        geen MEP-plan.
      </p>
      <p id="energy-device-catalog-status" class="status">
        Wachten op de optionele apparaatcatalogus…
      </p>
      <div id="energy-device-cards" class="energy-device-grid"></div>
      <form id="energy-device-placement-form" class="strategy-rules">
        <label class="strategy-rule">
          <strong>Geselecteerde kaart</strong>
          <select id="energy-device-card-select" required></select>
        </label>
        <label class="strategy-rule">
          <strong>Start</strong>
          <input id="energy-device-start" type="datetime-local" required>
        </label>
        <label class="strategy-rule">
          <strong>Duur</strong>
          <span>
            <input id="energy-device-duration" type="number" min="1" step="1" value="60">
            minuten
          </span>
        </label>
        <button id="add-energy-device-placement" type="submit">
          Op tijdlijn plaatsen
        </button>
        <span id="energy-device-placement-status" class="muted" aria-live="polite"></span>
      </form>
      <div id="energy-device-placements" class="energy-device-placement-list"></div>
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





    <h2>Prijsverloop vandaag en morgen</h2>
    <section id="price-timeline" class="price-panel" aria-live="polite">
      Nog geen prijsgegevens beschikbaar.
    </section>




    <h2>Planwijzigingen vergelijken</h2>
    <section id="plan-history" class="timeline-panel" aria-label="Planwijzigingen vergelijken">
      <p class="muted">Alleen terugkijken. Deze vergelijking verandert de huidige planning niet.
        Historische SOC-prognoses worden hier niet opnieuw berekend.</p>
      <label for="plan-history-select">Vergelijk met</label>
      <select id="plan-history-select" aria-label="Plan voor vergelijking"></select>
      <p id="plan-history-message" class="muted" aria-live="polite">Planhistorie laden.</p>
      <div id="plan-history-panels" class="plan-history-panels"></div>
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
    let planHistoryPlans = [];
    let planHistoryTruncated = false;
    let planHistoryOmitted = 0;
    let planHistoryStale = false;
    let planHistoryLoading = false;
    let planHistorySelectionId = "";
    let planHistoryOptionsKey = "";
    let pendingView = null;
    let latestLiveView = null;
    let latestStorageStatus = null;
    let storageStatusLoading = false;
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
      if (value === null || value === undefined) return "—";
      const numeric = Number(value);
      return Number.isFinite(numeric)
        ? `${numeric.toFixed(3).replace(".", ",")} €/kWh`
        : "—";
    }

    function formatCurrency(value) {
      if (value === null || value === undefined) return "—";
      const numeric = Number(value);
      return Number.isFinite(numeric)
        ? numeric.toLocaleString("nl-NL", {
            style: "currency",
            currency: "EUR",
            minimumFractionDigits: 2,
            maximumFractionDigits: 3,
          })
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

    function socQuarterSlots(startsAt, endsAt, history, now) {
      const points = (Array.isArray(history.points) ? history.points : [])
        .filter(point => Number.isFinite(Date.parse(point.at)))
        .slice().sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
      const observedEnd = history.status === "unavailable"
        ? NaN : Math.min(now, Date.parse(history.ends_at));
      const slots = [];
      let index = -1;
      for (let start = startsAt; start < endsAt; start += 900000) {
        const end = Math.min(start + 900000, endsAt);
        const sampleAt = Math.min(end, now);
        while (index + 1 < points.length && Date.parse(points[index + 1].at) <= sampleAt) {
          index += 1;
        }
        const raw = points[index]?.soc_percent;
        const value = typeof raw === "number" ? raw : NaN;
        slots.push({start, end, sampleAt, value:
          start < now && sampleAt <= observedEnd && Number.isFinite(value) &&
          value >= 0 && value <= 100 ? value : null});
      }
      return slots;
    }

    function renderPriceTimeline(
      timeline,
      capturedAt,
      plannerWindows = [],
      socTimeline = [],
      actualSoc = {},
      originalReference = {}
    ) {
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
      const timezone =
        timeline.market_timezone ?? "Europe/Amsterdam";
      const startsAtMs = start.getTime();
      const endsAtMs = end.getTime();
      const nowMs = Date.now();
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
        ["missing", "Nog niet gepubliceerd"],
        ["canonical-nom", "NOM / PV laden"],
        ["canonical-charge", "Net import / snel laden"],
        ["canonical-trade", "MEP handel / terugleveren"],
        ["canonical-support", "Slim huishoudelijk ontladen"],
        ["canonical-standby", "Stand-by — woning op netstroom"],
        ["optimized", "Geoptimaliseerd plandeel"],
        ["soc-actual", "Werkelijke SOC"],
        ["soc-projected", "SOC-prognose (historie + actuele verwachting)"],
        ["energy-device-placement", "Geplaatst energie-apparaat"]
      ]) {
        const item = document.createElement("span");
        item.className = "price-legend-item";
        const swatch = document.createElement("span");
        swatch.className = `price-swatch ${kind}`;
        item.append(swatch, label);
        legend.appendChild(item);
      }
      container.appendChild(legend);
      const referenceNote = document.createElement("p");
      referenceNote.className = "muted";
      referenceNote.textContent = originalReference.status === "available"
        ? "Arcering: latere aanpassingen ten opzichte van het oorspronkelijke plan, " +
          "inclusief handel."
        : "Oorspronkelijk plan niet beschikbaar; verschillen worden niet gearceerd.";
      container.appendChild(referenceNote);

      const width = 1280;
      const height = 430;
      const margin = {
        top: 36,
        right: 64,
        bottom: 76,
        left: 82
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
      const socHeight = 170;
      const socTop = 24;
      const socPlotHeight = plotHeight / 3;
      const socYPosition = value => socTop + (1 - value / 100) * socPlotHeight;
      const socSvg = createSvgElement("svg", {
        class: "price-chart soc-chart", viewBox: `0 0 ${width} ${socHeight}`,
        role: "img", "aria-label": "Batterijvulling: groene metingen en gele verwachting"
      });
      for (const value of [0, 50, 100]) {
        appendSvgText(socSvg, `${value}%`, {
          x: margin.left - 8, y: socYPosition(value) + 4, "text-anchor": "end"
        }, "axis-label");
      }
      const slots = socQuarterSlots(startsAtMs, endsAtMs, actualSoc, nowMs);
      for (const slot of slots) {
        const x = xPosition(slot.start) + .6;
        const barWidth = Math.max(.2, xPosition(slot.end) - xPosition(slot.start) - 1.2);
        if (slot.value !== null) {
          socSvg.appendChild(createSvgElement("rect", {
            class: "soc-quarter-fill", x, width: barWidth,
            y: socYPosition(slot.value), height: socYPosition(0) - socYPosition(slot.value)
          }));
        }
        const outline = createSvgElement("rect", {
          class: "soc-quarter-outline", x, y: socYPosition(100),
          width: barWidth, height: socPlotHeight
        });
        const title = createSvgElement("title", {});
        title.textContent = `${formatChartTime(slot.start, timezone)} · ` +
          (slot.value === null ? "Geen meting" : `Gemeten SOC ${slot.value}%`);
        outline.appendChild(title);
        socSvg.appendChild(outline);
      }
      for (let hour = 0; hour <= displayHours; hour += 6) {
        const timestamp = startsAtMs + hour * 3600000;
        appendSvgText(socSvg, formatChartTime(timestamp, timezone), {
          x: xPosition(timestamp), y: socHeight - 12, "text-anchor": "middle"
        }, "axis-label");
      }
      if (nowMs >= startsAtMs && nowMs <= endsAtMs) {
        socSvg.appendChild(createSvgElement("line", {
          class: "now-line", x1: xPosition(nowMs), x2: xPosition(nowMs),
          y1: socTop, y2: socYPosition(0)
        }));
      }

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
      const defs = createSvgElement("defs", {});
      for (const [kind, color] of [
        ["canonical-nom", "#35a862"],
        ["canonical-charge", "#df5c57"],
        ["canonical-trade", "#aab2bd"],
        ["canonical-support", "#3994e6"],
        ["canonical-standby", "#e3aa45"],
        ["normal", "#aab2bd"]
      ]) {
        const pattern = createSvgElement("pattern", {
          id: `price-hatch-${kind}`, width: 6, height: 6,
          patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)"
        });
        pattern.appendChild(createSvgElement("rect", {
          width: 6, height: 6, fill: color, "fill-opacity": 0.18
        }));
        pattern.appendChild(createSvgElement("line", {
          x1: 0, y1: 0, x2: 0, y2: 6, stroke: color, "stroke-width": 2
        }));
        defs.appendChild(pattern);
      }
      svg.appendChild(defs);

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
            y: height - 16,
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

        const isPast = pointEnd <= nowMs;
        const valueY = yPosition(value);
        const selectedWindows = plannerWindows.filter((window) => {
          const windowStart = new Date(window.starts_at).getTime();
          const windowEnd = new Date(window.ends_at).getTime();
          return pointStart < windowEnd && pointEnd > windowStart;
        });
        const selectedWindowClasses = [
          ...new Set(selectedWindows.map((window) => window.kind))
        ].join(" ");
        const bar = createSvgElement("rect", {
          class: [
            "price-bar",
            selectedWindowClasses || "normal",
            isPast ? "past" : "",
          ].filter(Boolean).join(" "),
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
          const selectedBy = selectedWindows.map((window) => window.label);
          detail.textContent = [
            `${formatTimestamp(point.starts_at)} – ` +
              formatTimestamp(point.ends_at),
            formatPrice(value),
            `Confidence ${formatConfidence(point.confidence)}`,
            ...(selectedWindows.some(w => w.optimized)
              ? ["Aangepast ten opzichte van het oorspronkelijke plan"] : []),
            ...(selectedBy.length
              ? [`Gekozen door ${selectedBy.join(" en ")}`]
              : [])
          ].join(" · ");
        };
        bar.addEventListener("mouseenter", showDetail);
        bar.addEventListener("focus", showDetail);
        bar.addEventListener("click", showDetail);
        svg.appendChild(bar);
        // Hatch only the exact overlap, including partial price quarters.
        for (const window of selectedWindows.filter(w => w.optimized === true)) {
          const a = Math.max(pointStart, new Date(window.starts_at).getTime());
          const b = Math.min(pointEnd, new Date(window.ends_at).getTime());
          svg.appendChild(createSvgElement("rect", {
            class: `optimized-price-part ${window.kind}`,
            x: xPosition(a), y: Math.min(valueY, zeroY),
            width: xPosition(b) - xPosition(a), height: Math.max(1, Math.abs(zeroY - valueY)),
            fill: `url(#price-hatch-${window.kind})`, "pointer-events": "none",
            opacity: isPast ? 0.45 : 1
          }));
        }
      }

      for (const window of plannerWindows) {
        const windowStart = Math.max(
          startsAtMs,
          new Date(window.starts_at).getTime()
        );
        const windowEnd = Math.min(
          endsAtMs,
          new Date(window.ends_at).getTime()
        );
        if (!Number.isFinite(windowStart) || !Number.isFinite(windowEnd) ||
            windowEnd <= windowStart) continue;
        svg.appendChild(createSvgElement("rect", {
          class: `planner-window ${window.kind}`,
          x: xPosition(windowStart),
          y: height - margin.bottom + 14,
          width: Math.max(2, xPosition(windowEnd) - xPosition(windowStart)),
          height: 6,
          rx: 2
        }));
      }

      const visibleSoc = socTimeline.filter((point) => {
        const timestamp = new Date(point.at).getTime();
        const soc = Number(point.soc_percent);
        return Number.isFinite(timestamp) && point.soc_percent !== null &&
          point.soc_percent !== undefined && Number.isFinite(soc) && soc >= 0 && soc <= 100 &&
          timestamp >= startsAtMs && timestamp <= endsAtMs;
      });
      for (let index = 1; index < visibleSoc.length; index += 1) {
        const previous = visibleSoc[index - 1];
        const current = visibleSoc[index];
        if (current.break_before === true) {
          if (current.source_identity?.plan_id !== previous.source_identity?.plan_id) {
            const marker = createSvgElement("circle", {
              class: "soc-replan-marker", fill: "#ffd600", r: 3,
              cx: xPosition(new Date(current.at).getTime()),
              cy: socYPosition(Number(current.soc_percent))
            });
            const title = createSvgElement("title", {});
            title.textContent = `Nieuw plan · ${formatTimestamp(current.at)}`;
            marker.appendChild(title);
            socSvg.appendChild(marker);
          }
          continue;
        }
        socSvg.appendChild(createSvgElement("line", {
          class: "soc-line soc-projected",
          x1: xPosition(new Date(previous.at).getTime()),
          y1: socYPosition(Number(previous.soc_percent)),
          x2: xPosition(new Date(current.at).getTime()),
          y2: socYPosition(Number(current.soc_percent))
        }));
      }
      if (actualSoc.ends_at || actualSoc.status === "unavailable") {
        const freshness = document.createElement("p");
        freshness.className = "muted";
        freshness.textContent = actualSoc.ends_at
          ? "Werkelijke SOC: meetgegevens tot " + `${formatTimestamp(actualSoc.ends_at)}.`
          : "Werkelijke SOC: historie tijdelijk niet beschikbaar.";
        if (actualSoc.status === "stale") {
          freshness.textContent +=
            " Historie tijdelijk niet beschikbaar; laatste gegevens behouden.";
        }
        container.appendChild(freshness);
      }

      if (
        nowMs > startsAtMs &&
        nowMs < endsAtMs
      ) {
        const x = xPosition(nowMs);
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
      const socHeading = document.createElement("h3");
      socHeading.textContent = "Batterijvulling · kwartierstaven · 0–100%";
      scroll.append(socHeading, socSvg);
      const socNote = document.createElement("p");
      socNote.className = "muted";
      socNote.textContent = "Groen: gemeten SOC aan het kwartiereinde (lopend kwartier: nu). " +
        "Geel: verwachting. Leeg: nog geen meting; meetgaten worden niet aangevuld.";
      container.append(scroll, socNote, detail);
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
      if (value === null || value === undefined) return "—";
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
      const details = document.createElement("section");
      details.className = "technical-details";
      const summary = document.createElement("h3");
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
        ? history.series.filter((item) => Array.isArray(item.display_points))
        : [];
      const start = new Date(history?.starts_at);
      const end = new Date(history?.ends_at);
      if (
        history?.status !== "available" ||
        Number.isNaN(start.getTime()) ||
        Number.isNaN(end.getTime()) ||
        end <= start ||
        !series.some((item) => item.display_points.length > 0)
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
        const latest = item.display_points.at(-1);
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
      const optionalEnergyWh = (value) =>
        value === null || value === undefined ? null : Number(value);
      for (const item of Array.isArray(deviations) ? deviations : []) {
        const startsAt = new Date(item.starts_at).getTime();
        const endsAt = new Date(item.ends_at).getTime();
        const centralEnergyWh = Number(item.forecast_central_energy_wh);
        const lowerEnergyWh = optionalEnergyWh(item.forecast_lower_energy_wh);
        const upperEnergyWh = optionalEnergyWh(item.forecast_upper_energy_wh);
        const durationHours = (endsAt - startsAt) / 3_600_000;
        if (
          Number.isFinite(startsAt) && Number.isFinite(endsAt) &&
          Number.isFinite(centralEnergyWh) && durationHours > 0
        ) {
          forecastByStart.set(startsAt, {
            sampledAt: startsAt + (endsAt - startsAt) / 2,
            centralPowerW: centralEnergyWh / durationHours,
            lowerPowerW: Number.isFinite(lowerEnergyWh)
              ? lowerEnergyWh / durationHours : centralEnergyWh / durationHours,
            upperPowerW: Number.isFinite(upperEnergyWh)
              ? upperEnergyWh / durationHours : centralEnergyWh / durationHours,
          });
        }
      }
      for (const item of Array.isArray(timeline?.intervals)
        ? timeline.intervals : []) {
        if (item.evidence_type !== "FORECAST") continue;
        const startsAt = new Date(item.starts_at).getTime();
        const endsAt = new Date(item.ends_at).getTime();
        const centralEnergyWh = Number(
          item.forecast_central_energy_wh ?? item.pv_energy_wh
        );
        const lowerEnergyWh = optionalEnergyWh(item.forecast_lower_energy_wh);
        const upperEnergyWh = optionalEnergyWh(item.forecast_upper_energy_wh);
        const durationHours = (endsAt - startsAt) / 3_600_000;
        if (
          Number.isFinite(startsAt) && Number.isFinite(endsAt) &&
          Number.isFinite(centralEnergyWh) && durationHours > 0
        ) {
          forecastByStart.set(startsAt, {
            sampledAt: startsAt + (endsAt - startsAt) / 2,
            centralPowerW: centralEnergyWh / durationHours,
            lowerPowerW: Number.isFinite(lowerEnergyWh)
              ? lowerEnergyWh / durationHours : centralEnergyWh / durationHours,
            upperPowerW: Number.isFinite(upperEnergyWh)
              ? upperEnergyWh / durationHours : centralEnergyWh / durationHours,
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
        ["forecast-lower", "Solcast lower (P10)"],
        ["forecast", "Solcast verwacht (centraal)"],
        ["forecast-upper", "Solcast upper (P90)"],
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
      const fullEnd = new Date(startMs);
      fullEnd.setDate(fullEnd.getDate() + 2);
      const fullEndMs = fullEnd.getTime();
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
      const values = [
        ...visibleForecast.flatMap((point) => [
          point.lowerPowerW, point.centralPowerW, point.upperPowerW,
        ]),
        ...visibleActual.map((point) => point.powerW),
      ];
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
            weekday: "short",
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
      const forecastCentralPoints = visibleForecast.map((point) => ({
        x: x(point.sampledAt), y: y(point.centralPowerW),
      }));
      const forecastLowerPoints = visibleForecast.map((point) => ({
        x: x(point.sampledAt), y: y(point.lowerPowerW),
      }));
      const forecastUpperPoints = visibleForecast.map((point) => ({
        x: x(point.sampledAt), y: y(point.upperPowerW),
      }));
      const forecastPath = smoothPath(forecastCentralPoints);
      const lowerPath = smoothPath(forecastLowerPoints);
      const upperPath = smoothPath(forecastUpperPoints);
      if (lowerPath && upperPath) {
        const reversedLowerPath = smoothPath([...forecastLowerPoints].reverse())
          .replace(/^M/, "L");
        svg.appendChild(createSvgElement("path", {
          d: `${upperPath} ${reversedLowerPath} Z`,
          class: "forecast-range",
        }));
      }
      if (lowerPath) {
        svg.appendChild(createSvgElement("path", {
          d: lowerPath,
          class: "forecast-lower-line",
        }));
      }
      if (forecastPath) {
        svg.appendChild(createSvgElement("path", {
          d: forecastPath,
          class: "forecast-line",
        }));
      }
      if (upperPath) {
        svg.appendChild(createSvgElement("path", {
          d: upperPath,
          class: "forecast-upper-line",
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

    function dashboardFaults(view) {
      const faults = [];
      const names = {p1:"P1 netmeting", pv:"Zonnepanelen", zendure:"Zendure batterij",
        solcast:"Solcast voorspelling", nordpool:"Nord Pool prijzen"};
      const stages = ["Planningsinvoer", "Energiekansen", "Mogelijke plannen", "Planbeoordeling",
        "Uitvoeringsplan", "Uitvoering", "Uitvoerbare opdracht", "Apparaatkoppeling", "Zendure"];
      for (const item of view.pipeline ?? []) {
        const attrs = item.attributes ?? {};
        const sources = (attrs.sources ?? []).filter(
          s => s.availability === "unavailable" || s.error);
        for (const source of sources) {
          const label = source.semantic_role === "controlled_load_measurement"
            ? "Home Climate-belastingsmeting" : names[source.category] ?? source.category ?? "Bron";
          faults.push(`${label}: ` +
            `${source.error || "geen bruikbare meting beschikbaar"}` +
            (source.entity_id ? ` (${source.entity_id})` : ""));
        }
        if (item.health !== "fault") continue;
        if (item.fault_explanation_nl) {
          faults.push(item.fault_explanation_nl);
          continue;
        }
        if (sources.length && !attrs.error) continue;
        const reasons = [attrs.error, ...(Array.isArray(attrs.blockers) ? attrs.blockers : [])]
          .filter(value => typeof value === "string" && value && value !== "-");
        faults.push(`${stages[item.stage - 1] ?? "PicoT"}: ` +
          (reasons.join("; ") || `stap mislukt (${item.state ?? "oorzaak niet aangeleverd"})`));
      }
      const catalog = view.energy_device_catalog;
      if (catalog && ["error", "failed", "unavailable"].includes(catalog.status)) {
        faults.push("Energy Devices: apparaatcatalogus niet beschikbaar" +
          (catalog.error ? ` — ${catalog.error}` : ". Controleer of Energy Devices draait.") +
          " Nieuwe apparaatkaarten kunnen niet worden opgehaald.");
      }
      if (!faults.length && view.pipeline_health?.healthy === false) {
        faults.push("PicoT meldt een probleem, maar heeft de oorzaak niet aangeleverd. " +
          "Download een diagnose om de ontbrekende foutdetails te onderzoeken.");
      }
      const readiness = view.plan_explanation?.readiness;
      if (readiness?.status === "blocked" && readiness.warning_nl) {
        faults.push(readiness.warning_nl);
      }
      return [...new Set(faults)];
    }

    function renderDashboardFaults(view) {
      const target = element("central-health");
      const faults = dashboardFaults(view);
      target.replaceChildren();
      target.hidden = faults.length === 0;
      target.dataset.health = faults.length ? "fault" : "healthy";
      for (const message of faults) {
        const line = document.createElement("p"); line.textContent = message; target.append(line);
      }
    }

    function comparisonSegments(route) {
      const source = route?.timeline ?? route ?? {};
      const full = Array.isArray(source.segments);
      const raw = full ? source.segments : (route?.main_signature ?? []).map(
        item => ({starts_at:item[0], ends_at:item[1], intent:item[2]}));
      const segments = raw.map(item => ({start:Date.parse(item.starts_at),
        end:Date.parse(item.ends_at), mode:item.intent ?? item.primitive,
        power:item.requested_power_w ?? null, exportWh:item.storage_export_target_wh ?? null,
        policy:item.charge_source_policy ?? null})).filter(item =>
          Number.isFinite(item.start) && Number.isFinite(item.end) && item.end > item.start);
      return {segments:segments.sort((a,b) => a.start-b.start),
        partial:!full || source.truncated === true || source.segments_truncated === true ||
          segments.length !== raw.length};
    }

    function comparisonDifferences(left, right) {
      const points = [...new Set([...left.segments,...right.segments]
        .flatMap(s => [s.start,s.end]))].sort((a,b) => a-b);
      const result = [];
      for (let i=0;i<points.length-1;i++) {
        const start=points[i], end=points[i+1];
        const a=left.segments.find(s => s.start<=start && s.end>=end);
        const b=right.segments.find(s => s.start<=start && s.end>=end);
        const signature = s => s ? JSON.stringify([s.mode,s.power,
          s.exportWh == null ? null : Math.round(s.exportWh/(s.end-s.start)*3600000*1e6)/1e6,
          s.policy]) : "unknown";
        if (signature(a)===signature(b)) continue;
        const item={start,end,from:a?.mode ?? "unknown",to:b?.mode ?? "unknown",
          parameters: a?.mode === b?.mode};
        const last=result.at(-1);
        if (last && last.end===start && last.from===item.from && last.to===item.to &&
            last.parameters===item.parameters) last.end=end;
        else result.push(item);
      }
      return result;
    }

    function comparisonMode(mode) {
      return ({balance_bidirectional:["Nul op de meter","#35a862"],
        balance_charge_only:["Alleen slim opladen","#35a862"],
        balance_discharge_only:["Slim ontladen","#3994e6"],
        charge_at_power:["Laden","#df5c57"],discharge_at_power:["Terugleveren","#aab2bd"],
        stop_all:["Stand-by","#e3aa45"],grid_requirement:["Netladen","#df5c57"],grid_charge:["Netladen","#df5c57"],
        charge:["Laden","#df5c57"],nom:["Nul op de meter","#35a862"],
        household_support_only:["Slim ontladen","#3994e6"],
        discharge_only:["Slim ontladen","#3994e6"],self_consumption:["Slim ontladen","#3994e6"],
        standby:["Stand-by","#e3aa45"],hold_storage:["Stand-by","#e3aa45"],
        storage_export:["Terugleveren","#aab2bd"],discharge:["Terugleveren","#aab2bd"],
        unknown:["Geen gegevens","#e2e8f0"]})[mode] ?? [mode ?? "Geen gegevens","#64748b"];
    }

    function appendPlanComparison(target, a, b, labels) {
      const single=labels.length === 1;
      const left=comparisonSegments(a), right=comparisonSegments(single ? a : b);
      const changes=comparisonDifferences(left,right);
      const all=[...left.segments,...right.segments];
      const note=document.createElement("p");
      if (!left.segments.length || !right.segments.length) {
        note.textContent="Tijdlijnvergelijking niet beschikbaar: " +
          "van een route ontbreken de tijdvakken.";
        target.append(note); return;
      }
      const start=Math.min(...all.map(s=>s.start)), end=Math.max(...all.map(s=>s.end));
      const svg=createSvgElement("svg", {
        viewBox:single ? "0 0 1000 130" : "0 0 1000 210",role:"img",
        "aria-label":single ? labels[0] : `${labels[0]} en ${labels[1]} op dezelfde tijdschaal`});
      svg.classList.add("comparison-chart");
      const x=time=>20+(time-start)/(end-start)*960;
      for (let i=0;i<=4;i++) {
        const time=start+(end-start)*i/4;
        appendSvgText(svg,planHistoryTime(new Date(time).toISOString()),
          {x:x(time),y:single ? 122 : 202,
            "text-anchor":i===0?"start":i===4?"end":"middle","font-size":11});
      }
      (single ? [left] : [left,right]).forEach((route,row)=> {
        const y=25+row*80;
        appendSvgText(svg,labels[row],{x:20,y:y-8,"font-size":14,"font-weight":600});
        svg.append(createSvgElement("rect",{x:20,y,width:960,height:35,fill:"#eef2f6"}));
        for (const s of route.segments) {
          const rect=createSvgElement("rect",{x:x(s.start),y,width:x(s.end)-x(s.start),
            height:35,fill:comparisonMode(s.mode)[1]});
          const title=createSvgElement("title");
          title.textContent=`${comparisonMode(s.mode)[0]}: `+
            `${planHistoryTime(new Date(s.start).toISOString())} – `+
            planHistoryTime(new Date(s.end).toISOString());
          rect.append(title); svg.append(rect);
        }
        for (const change of changes) svg.append(createSvgElement("rect",{
          x:x(change.start),y:y-2,width:Math.max(2,x(change.end)-x(change.start)),height:39,
          fill:"none",stroke:"#172b4d","stroke-width":2,"stroke-dasharray":"4 2"}));
      });
      const scroll=document.createElement("div"); scroll.className="comparison-scroll";
      scroll.append(svg); target.append(scroll);
      const legend=document.createElement("p"); legend.className="comparison-legend";
      for (const mode of [...new Set(all.map(s=>s.mode))]) {
        const swatch=document.createElement("span");
        swatch.style.borderLeft=`12px solid ${comparisonMode(mode)[1]}`;
        swatch.textContent=comparisonMode(mode)[0]; legend.append(swatch);
      }
      target.append(legend);
      note.textContent=single ? labels[0] : changes.length
        ? "Gestippelde kaders markeren de verschillen." :
        "Geen verschil in de getoonde batterijmodi, tijden en vastgelegde instellingen.";
      if (left.partial || right.partial) note.textContent +=
        " Onvolledige vergelijking: oudere voorstellen bevatten alleen laadvensters " +
        "of de reeks is afgekapt. " +
        "Lege delen zijn onbekend; dit is geen volledige planvergelijking.";
      target.append(note);
      const list=document.createElement("ul"); list.className="comparison-differences";
      for (const change of changes.slice(0,12)) {
        const line=document.createElement("li");
        line.textContent=`${planHistoryTime(new Date(change.start).toISOString())} – `+
          `${planHistoryTime(new Date(change.end).toISOString())}: `+
          `${comparisonMode(change.from)[0]} → ${comparisonMode(change.to)[0]}`+
          (change.parameters ? " (vastgelegde vermogens-/broninstelling verschilt)" : "");
        list.append(line);
      }
      if (changes.length>12) {
        const line=document.createElement("li");
        line.textContent=`Nog ${changes.length-12} verschillen; ` +
          "alle verschillen zijn gemarkeerd in de tijdlijn.";
        list.append(line);
      }
      target.append(list);
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
        const details = document.createElement("section");
        details.className = "stage-card";

        const summary = document.createElement("h3");
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
      const central = element("central-health");
      central.dataset.health = healthy ? "healthy" : "fault";
      central.textContent = healthy ? "PicoT · pipeline in orde" :
        health?.summary_nl ?? "PicoT · status nog onbekend";
      container.dataset.health = healthy ? "healthy" : "fault";
      container.textContent = health?.summary_nl ??
        "De gezondheid van de pipeline is nog niet bekend.";
    }

    function modeFreshness(status, now = Date.now()) {
      const observed = Date.parse(status?.observed_at);
      const seconds = Math.floor((now - observed) / 1000);
      if (!Number.isFinite(seconds) || seconds < 0) {
        return {stale: true, label: "Meetouderdom onbekend"};
      }
      const age = seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min`;
      const stale = seconds > 120 || status?.availability === "unavailable";
      return {stale, label: `${stale ? "Verouderd · " : ""}${age} geleden waargenomen`};
    }

    function currentStorageStatus(status) {
      const independent = Date.parse(latestStorageStatus?.observed_at);
      const bundled = Date.parse(status?.observed_at);
      return Number.isFinite(independent) && (!Number.isFinite(bundled) || independent >= bundled)
        ? {...status, ...latestStorageStatus} : status;
    }

    function refreshLiveStatus(view) {
      if (view) latestLiveView = view;
      if (!latestLiveView) return;
      const status = currentStorageStatus(latestLiveView.zendure_now);
      renderTodaySummary({...latestLiveView, zendure_now: status});

    }

    async function loadStorageStatus() {
      if (storageStatusLoading) return;
      storageStatusLoading = true;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch("api/storage-status", {
          cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const received = await response.json();
        const time = Date.parse(received.observed_at);
        const previous = Date.parse(latestStorageStatus?.observed_at);
        if (Number.isFinite(time) && (!Number.isFinite(previous) || time >= previous)) {
          latestStorageStatus = received;
        }
      } catch (error) {
        // Keep the last measured value; its age continues to increase visibly.
      } finally {
        clearTimeout(timer);
        storageStatusLoading = false;
        refreshLiveStatus(latestLiveView);
      }
    }

    function renderZendureNow(status) {
      status = currentStorageStatus(status);
      const container = element("zendure-now");
      const grid = document.createElement("dl");
      grid.className = "zendure-now-grid";
      const originLabels = {
        picot: "PicoT",
        manual: "Handmatig vastgesteld",
        unknown: "Nog onbekend"
      };
      appendAttribute(grid, "Actieve modus", status?.active_mode);
      appendAttribute(grid, "Actualiteit", modeFreshness(status).label);
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
        const details = document.createElement("section");
        details.className = "plan-explanation-detail";
        details.dataset.explanationKey = `opportunity:${group.label_nl}`;
        const summary = document.createElement("h3");
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

    function renderMarketRevisionComparison(comparison, addCard) {
      const alternatives = comparison?.alternatives;
      if (!Array.isArray(alternatives) || !alternatives.length) return;
      const card = addCard("Marktroute: financiële vergelijking", [
        ["Berekend", formatTimestamp(comparison.comparison_captured_at)],
        ["Weergave", comparison.retained
          ? "Laatste vergelijking voor dit plan; niet opnieuw berekend"
          : "Vergelijking bij deze planbeslissing"],
        ["Beslisregel", comparison.decisive_step],
        ["Reden", comparison.reason],
      ], true);
      const note = document.createElement("p");
      note.textContent = "Verwachte bedragen vanaf het rekenmoment. " +
        "Verschillen zijn ten opzichte van behoud van het bestaande plan.";
      card.append(note);
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const heading = document.createElement("tr");
      for (const label of [
        "Alternatief", "Gekozen", "Vergelijkingsperiode", "Afname en export per dag",
        "Netladen", "Eindvoorraad", "Minimumvoorraad", "Slijtage",
        "Vergelijkbaar resultaat", "Verschil met behoud", "Afwijsreden",
      ]) {
        const cell = document.createElement("th");
        cell.textContent = label;
        heading.append(cell);
      }
      head.append(heading);
      const body = document.createElement("tbody");
      const labels = {retained: "Behouden", shortened: "Inkorten", removed: "Verwijderen"};
      for (const alternative of alternatives) {
        const row = document.createElement("tr");
        row.dataset.candidateId = alternative.candidate_id;
        const reasons = [...new Set([
          ...(alternative.invalidity_reasons ?? []),
          ...(alternative.evaluation_invalidity_reasons ?? []),
        ])];
        const days = (alternative.days ?? []).map(day => (
          `${day.delivery_date}: afname ${formatCurrency(day.import_cost_eur)}, ` +
          `export ${formatCurrency(day.export_revenue_eur)}`
        ));
        for (const value of [
          (labels[alternative.variant] ?? alternative.variant) +
            (alternative.incumbent ? " (bestaand plan)" : ""),
          alternative.selected ? "Ja" : "Nee",
          `${formatTimestamp(alternative.horizon_start)} – ` +
            formatTimestamp(alternative.horizon_end),
          days.join("; "),
          formatMeasurement(alternative.grid_charge_wh, "Wh"),
          formatMeasurement(alternative.terminal_storage_wh, "Wh"),
          formatMeasurement(alternative.minimum_storage_wh, "Wh"),
          formatCurrency(alternative.wear_cost_eur),
          alternative.comparable_result_eur === null
            ? "Onvoldoende vergelijkingsbewijs"
            : formatCurrency(alternative.comparable_result_eur),
          formatCurrency(alternative.delta_from_incumbent_eur),
          reasons.length ? reasons.join("; ") : "—",
        ]) {
          const cell = document.createElement("td");
          cell.textContent = displayValue(value);
          row.append(cell);
        }
        body.append(row);
      }
      table.append(head, body);
      card.append(table);
    }

    function planHistoryTime(value) {
      const date = new Date(value);
      if (!value || !Number.isFinite(date.getTime())) return "Onbekend";
      const parts = new Intl.DateTimeFormat("nl-NL", {
        timeZone: "Europe/Amsterdam", year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "longOffset",
      }).formatToParts(date);
      const valueOf = name => parts.find(part => part.type === name)?.value ?? "";
      const offset = valueOf("timeZoneName").replace("GMT", "UTC");
      return `${valueOf("day")}-${valueOf("month")}-${valueOf("year")} ` +
        `${valueOf("hour")}:${valueOf("minute")} (${offset})`;
    }

    function planHistorySelection(plans, selectedId) {
      const current = plans.find(plan => plan.active === true) ?? null;
      const selected = plans.find(plan => plan.plan_id === selectedId) ??
        plans.find(plan => plan.active !== true) ?? current;
      return {current, selected};
    }

    function planHistoryReason(reason) {
      return {
        initial_main_route: "Eerste dagplan",
        existing_route_cannot_reach_target: "Eerder plan kon het laaddoel niet halen",
        projected_reserve_shortfall: "Verwacht tekort aan batterijreserve",
        current_soc_allows_grid_reduction: "Actuele SOC maakt minder netladen mogelijk",
        explicit_user_recalculation: "Opnieuw berekend op verzoek",
      }[reason] ?? reason ?? "Reden niet vastgelegd";
    }

    function renderPlanHistory() {
      const picker = element("plan-history-select");
      const {current, selected} = planHistorySelection(planHistoryPlans, planHistorySelectionId);
      planHistorySelectionId = selected?.plan_id ?? "";
      const optionsKey = JSON.stringify(planHistoryPlans.map(plan =>
        [plan.plan_id, plan.created_at, plan.active]));
      if (optionsKey !== planHistoryOptionsKey) {
        picker.replaceChildren();
        for (const plan of planHistoryPlans) {
          const option = document.createElement("option");
          option.value = plan.plan_id;
          option.textContent = `${plan.active ? "Huidig" : "Historisch"} · ` +
            `${planHistoryTime(plan.created_at)}`;
          picker.append(option);
        }
        planHistoryOptionsKey = optionsKey;
      }
      picker.value = planHistorySelectionId;
      picker.disabled = planHistoryPlans.length === 0;
      const panels = element("plan-history-panels");
      panels.replaceChildren();
      for (const [plan, label] of [[current, "Huidig plan"],
          [selected !== current ? selected : null, "Historisch plan - niet actief"]]) {
        if (!plan) continue;
        const heading=document.createElement("p");
        heading.textContent=`${label}: ${planHistoryTime(plan.created_at)}. `+
          `Reden: ${planHistoryReason(plan.revision_reason)}`;
        panels.append(heading);
        if (plan.segments_truncated) {
          const warning=document.createElement("p");
          warning.textContent="Dit plan bevat meer segmenten dan hier getoond worden.";
          panels.append(warning);
        }
      }
      if (current && selected && selected !== current) {
        appendPlanComparison(panels, selected, current, ["Historisch plan", "Huidig plan"]);
      } else if (selected) {
        appendPlanComparison(panels, selected, null,
          [selected === current ? "Huidig plan" : "Historisch plan - niet actief"]);
      }
      let message = !planHistoryPlans.length
        ? "Geen opgeslagen planhistorie beschikbaar."
        : !current ? "Historische vergelijking; geen actief plan in deze gegevens."
          : selected === current
            ? "Huidig plan geselecteerd. Kies een eerder plan om te vergelijken."
            : "Vergelijking met een eerder plan; de actieve tijdlijn en SOC blijven ongewijzigd.";
      if (planHistoryTruncated) message += " Alleen de meest recente plannen zijn beschikbaar.";
      if (planHistoryOmitted > 0) {
        message += ` ${planHistoryOmitted} onvolledige historierecords overgeslagen.`;
      }
      if (planHistoryStale) {
        message = "Niet ververst: deze vergelijking kan verouderd zijn. " + message;
      }
      element("plan-history-message").textContent = message;
    }

    async function loadPlanHistory() {
      if (planHistoryLoading) return;
      planHistoryLoading = true;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch("api/plan-history", {
          cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!Array.isArray(body.plans)) throw new Error("Ongeldige planhistorie");
        planHistoryPlans = body.plans.filter(plan => typeof plan?.plan_id === "string");
        planHistoryTruncated = body.truncated === true;
        planHistoryOmitted = Number(body.omitted_invalid_records) || 0;
        planHistoryStale = false;
        renderPlanHistory();
      } catch (error) {
        planHistoryStale = true;
        element("plan-history-message").textContent =
          "Planhistorie niet ververst; eventuele getoonde vergelijking kan verouderd zijn.";
      } finally {
        clearTimeout(timer); planHistoryLoading = false;
      }
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
      const availablePlanningRows = (rows) => rows.filter(([, value]) => (
        value !== null && value !== undefined && value !== "" && value !== "—"
      ));
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
        ["SOC-prognose", status.soc_expectation?.status === "available"
          ? "Actuele verwachting van het geldende plan"
          : status.soc_expectation?.status === "unavailable"
            ? "Actuele verwachting tijdelijk niet beschikbaar"
            : status.soc_projection_retained
              ? "Oorspronkelijke prognose van behouden plan" : null],
        ["SOC-prognose berekend", formatTimestamp(status.soc_projection_captured_at)],
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
        ["Plan berekend", formatTimestamp(status.captured_at)],
        ["SoC bij berekening", status.initial_soc == null
          ? "Niet beschikbaar"
          : `${Math.round(Number(status.initial_soc) * 100)}%`],
        ["Planningshorizon", formatTimestamp(status.valid_until)],
        ["Uitvoering vanaf", formatTimestamp(execution.valid_from)],
        ["Uitvoering tot", formatTimestamp(execution.valid_until)],
        ["Run", status.run_id],
        ["Snapshot", status.snapshot_id],
      ]);

      const chosenPlan = status.chosen_plan ?? {};
      const chosenCard = addCard("Gekozen uitvoeringsplan", availablePlanningRows([
        ["Plan-ID", chosenPlan.plan_id],
        ["Planrevisie", chosenPlan.plan_revision],
        ["Uitvoeringsscope", chosenPlan.execution_scope_id],
        ["Kandidaat", chosenPlan.candidate_id],
        ["Energiepad", chosenPlan.energy_path_id],
        ["Planfamilie", chosenPlan.family],
        ["Beslisregel", chosenPlan.decisive_step],
        ["Beslisreden", chosenPlan.reason],
        ["Plan geldig vanaf", formatTimestamp(chosenPlan.valid_from)],
        ["Plan geldig tot", formatTimestamp(chosenPlan.valid_until)],
        ["Laadvenster vanaf", formatTimestamp(chosenPlan.charge_window_starts_at)],
        ["Laadvenster tot", formatTimestamp(chosenPlan.charge_window_ends_at)],
        ["Laadbronbeleid", chosenPlan.source_policy],
        ["Gemiddelde laadvensterprijs", formatPrice(
          chosenPlan.average_charge_window_price_eur_per_kwh
        )],
        ["Totale doelenergie", formatMeasurement(chosenPlan.required_energy_wh, "Wh")],
        ["Batterijenergie bij berekening", formatMeasurement(
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
        ["Effectieve maximale doelenergie", formatMeasurement(
          chosenPlan.effective_maximum_storage_energy_wh, "Wh"
        )],
        ["Gewogen voorspelde piekenergie", formatMeasurement(
          chosenPlan.confidence_weighted_peak_storage_energy_wh, "Wh"
        )],
        ["Gewogen piekmoment", formatTimestamp(
          chosenPlan.confidence_weighted_peak_at
        )],
        ["Effectief maximum vereist voor", formatTimestamp(
          chosenPlan.effective_maximum_required_by
        )],
        ["Effectief maximum bereikt", chosenPlan.effective_maximum_reached],
        ["Effectief maximum bereikt op", formatTimestamp(
          chosenPlan.effective_maximum_reached_at
        )],
        ["Confidence effectief maximum", formatConfidence(
          chosenPlan.effective_maximum_basis_confidence
        )],
        ["Reden effectief maximum", chosenPlan.effective_maximum_reason],
        ["Evidence effectief maximum", chosenPlan.effective_maximum_evidence_id],
        ["Energie einde laadvenster", formatMeasurement(
          chosenPlan.storage_energy_at_window_end_wh, "Wh"
        )],
        ["Energie bij deadline", formatMeasurement(
          chosenPlan.storage_energy_at_requirement_wh, "Wh"
        )],
        ["Minimale energie einde horizon", formatMeasurement(
          chosenPlan.minimum_storage_energy_at_horizon_end_wh, "Wh"
        )],
        ["Laaddoel 100% gehaald", chosenPlan.charge_target_satisfied],
        ["Reserve bij deadline gehaald", chosenPlan.reserve_satisfied],
        ["Reserve in alle scenario's",
          chosenPlan.reserve_respected_across_scenarios],
        ["Doel vastgehouden in alle scenario's",
          chosenPlan.target_held_across_scenarios],
        ["Minimaal benodigde reserve", formatMeasurement(
          chosenPlan.reserve_energy_required_wh, "Wh"
        )],
        ["Bijdrage PV", formatMeasurement(chosenPlan.pv_contribution_wh, "Wh")],
        ["Bijdrage net", formatMeasurement(chosenPlan.grid_contribution_wh, "Wh")],
        ["Conversieverlies", formatMeasurement(chosenPlan.conversion_losses_wh, "Wh")],
        ["Doel gehaald", chosenPlan.requirement_satisfied],
        ["Slechtste financiële uitkomst", formatCurrency(
          chosenPlan.worst_case_financial_result_eur
        )],
        ["Herstelbaarheid", formatConfidence(chosenPlan.recoverability)],
        ["Planconfidence", formatConfidence(chosenPlan.confidence)],
        ["Confidence batterijdoel", formatConfidence(
          chosenPlan.requirement_confidence
        )],
      ]), true);
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

      renderMarketRevisionComparison(status.market_revision_comparison, addCard);
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
      element("storage-mode-override").hidden = !manualOverrideActive;
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

    function renderPlanningRecalculation(result) {
      const status = result?.status ?? "idle";
      if (result?.mode === "recovery_reset") {
        element("planning-reset-result").textContent = status === "completed"
          ? "Nieuw plan gemaakt. Oude plannen zijn gearchiveerd; historie blijft behouden."
          : "Herstelverzoek opgeslagen. PicoT maakt een nieuw plan met actuele gegevens.";
        element("reset-planning").disabled = false;
        return;
      }
      const results = Object.values(result?.results ?? {});
      const rebuilt = results.filter((item) => item.status === "replanned").length;
      const messages = {
        idle: "Nieuwe planning maken vanaf actuele gegevens; oude plannen worden gearchiveerd.",
        pending: "Verzoek opgeslagen. PicoT berekent de open dagplannen opnieuw.",
        completed: rebuilt > 0
          ? `${rebuilt} dagplan(nen) opnieuw berekend. Dagdoelen en historie zijn behouden.`
          : "Geen herberekening meer nodig: de aangevraagde dagdoelen zijn afgerond of verstreken.",
        failed: rebuilt > 0
          ? `${rebuilt} dagplan(nen) opnieuw berekend. ` +
            "Niet voor alle dagplannen is een geldige vervanger gevonden."
          : "Herberekening niet gelukt. Er is geen nieuw plan opgeslagen. " +
            "Dagdoelen en historie zijn behouden.",
        not_applicable: "Er is geen open vastgelegd dagplan om opnieuw te berekenen. " +
          "Behaalde doelen blijven behouden.",
      };
      const unavailable = result?.reason === "recalculation_state_unavailable";
      element("planning-reset-result").textContent = unavailable
        ? "De status van de herberekening kan niet worden gelezen. Bekijk de diagnose."
        : (messages[status] ?? "De status van de herberekening is onbekend.");
      element("reset-planning").disabled = status === "pending";
    }

    async function resetPlanning() {
      const resetButton = element("reset-planning");
      const confirmed = globalThis.confirm(
        "PicoT laat bestaande laad- en marktplannen los. " +
        "Een nieuw plan wordt met actuele gegevens gemaakt. " +
        "Historie en bewezen 100%-momenten blijven bewaard. " +
        "Een onhaalbaar dagdoel wordt als gemist geregistreerd. " +
        "Een handmatige modusoverride blijft apart actief. Doorgaan?"
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
          throw new Error(`Herberekening geweigerd (${response.status})`);
        }
        const result = await response.json();
        renderPlanningRecalculation(result);
        await loadView();
      } catch (error) {
        element("planning-reset-result").textContent =
          error instanceof Error ? error.message : "Herberekening mislukt.";
        resetButton.disabled = false;
      }
    }

    function executionPlanActionLabel(primitive) {
      return {
        balance_discharge_only: "Huishouden ondersteunen",
        charge_at_power: "Batterij laden",
        discharge_at_power: "Naar het net ontladen",
        standby: "Stand-by",
      }[primitive] ?? displayValue(primitive);
    }

    function executionPlanSourceLabel(sourcePolicy) {
      return {
        pv_only: "Alleen PV",
        pv_preferred_grid_allowed: "PV heeft voorkeur; net toegestaan",
        grid_only: "Alleen net",
      }[sourcePolicy] ?? displayValue(sourcePolicy);
    }

    function executionPlanDayLabel(value) {
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) return "—";
      return parsed.toLocaleDateString("nl-NL", {
        timeZone: "Europe/Amsterdam",
        weekday: "long",
        day: "numeric",
        month: "long",
      });
    }

    function renderBatteryEnergyPlan(plans, execution) {
      const container = element("storage-energy-source-needs");
      container.replaceChildren();

      if (!Array.isArray(plans) || plans.length === 0) {
        container.textContent =
          "Nog geen energieplan voor de batterij beschikbaar.";
        return;
      }

      const blockers = Array.isArray(execution?.blockers)
        ? execution.blockers : [];
      if (blockers.includes("manual_override_active")) {
        const notice = document.createElement("p");
        notice.className = "planning-attention";
        notice.textContent =
          "Handmatige instelling actief: PicoT toont dit plan, maar stuurt " +
          "het niet naar de batterij.";
        container.appendChild(notice);
      }

      for (const plan of plans) {
        const article = document.createElement("article");
        const heading = document.createElement("h3");
        heading.textContent = "MEP-uitvoeringsplan";
        const attributes = document.createElement("dl");
        appendAttribute(attributes, "Plan", plan.plan_id);
        appendAttribute(attributes, "Status", plan.lifecycle_status);
        appendAttribute(attributes, "Geldig vanaf", formatTimestamp(plan.valid_from));
        appendAttribute(attributes, "Geldig tot", formatTimestamp(plan.valid_until));
        article.append(heading, attributes);

        const table = document.createElement("table");
        const head = document.createElement("thead");
        const headRow = document.createElement("tr");
        for (const label of [
          "Dag", "Vanaf", "Tot", "Actie", "Vermogen", "Laadbron", "Doel"
        ]) {
          const cell = document.createElement("th");
          cell.textContent = label;
          headRow.append(cell);
        }
        head.append(headRow);
        const body = document.createElement("tbody");
        for (const segment of plan.segments ?? []) {
          const row = document.createElement("tr");
          for (const value of [
            executionPlanDayLabel(segment.starts_at),
            formatTimestamp(segment.starts_at),
            formatTimestamp(segment.ends_at),
            executionPlanActionLabel(segment.primitive),
            formatMeasurement(segment.requested_power_w, "W"),
            executionPlanSourceLabel(segment.charge_source_policy),
            segment.purpose,
          ]) {
            const cell = document.createElement("td");
            cell.textContent = displayValue(value);
            row.append(cell);
          }
          body.append(row);
        }
        table.append(head, body);
        article.append(table);
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

      const details = document.createElement("section");
      details.className = "technical-details";
      details.open = quarterDetailsOpen;
      const summary = document.createElement("h3");
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

    function mergeDailyIntentWindows(intervals) {
      const actionable = (intervals ?? []).filter(
        (interval) => interval.intent !== "household_support_only"
      );
      const merged = [];
      for (const interval of actionable) {
        const previous = merged.at(-1);
        if (
          previous &&
          previous.intent === interval.intent &&
          previous.ends_at === interval.starts_at
        ) {
          previous.ends_at = interval.ends_at;
        } else {
          merged.push({...interval});
        }
      }
      return merged;
    }

    function dailyStrategyLabel(candidate) {
      const intents = new Set(candidate?.intents_used ?? []);
      if (intents.has("grid_requirement")) return "PV + netaanvulling";
      if (intents.has("nom") && intents.has("household_support_only")) {
        return "PV laden + slim ontladen";
      }
      if (intents.has("nom")) return "PV laden";
      if (intents.has("storage_export")) return "Batterij ontladen naar het net";
      if (intents.has("standby")) return "Stand-by";
      return "Alleen slim ontladen";
    }

    function dailyIntentLabel(intent) {
      return {
        nom: "PV laden (NOM)",
        grid_requirement: "Netaanvulling",
        storage_export: "Ontladen naar het net",
        standby: "Stand-by",
      }[intent] ?? displayValue(intent);
    }

    function dailyWindowLabel(candidate) {
      const windows = mergeDailyIntentWindows(candidate?.intent_intervals);
      if (!windows.length) return "Geen laad- of ontlaadvenster nodig";
      return windows.map((window) => [
        dailyIntentLabel(window.intent),
        formatTimestamp(window.starts_at),
        "tot",
        formatTimestamp(window.ends_at),
      ].join(" ")).join(" | ");
    }

    function primitivePlanKind(primitive) {
      return {
        balance_bidirectional: "canonical-nom",
        charge_at_power: "canonical-charge",
        discharge_at_power: "canonical-trade",
        balance_discharge_only: "canonical-support",
        standby: "canonical-standby",
        actual: "normal",
      }[primitive] ?? "normal";
    }

    function pricePlanParts(segment, plan, reference) {
      const start = Date.parse(segment.starts_at), end = Date.parse(segment.ends_at);
      const originals = (reference?.plans ?? [])
        .filter(p => p.execution_scope_id === plan.execution_scope_id)
        .flatMap(p => p.segments ?? [])
        .filter(s => Date.parse(s.starts_at) < end && Date.parse(s.ends_at) > start);
      const cuts = [...new Set([start, end, ...originals.flatMap(s => [
        Math.max(start, Date.parse(s.starts_at)), Math.min(end, Date.parse(s.ends_at))
      ])])].sort((a, b) => a - b);
      return cuts.slice(0, -1).map((a, i) => {
        const b = cuts[i + 1];
        const baseline = originals.filter(s => Date.parse(s.starts_at) <= a &&
          Date.parse(s.ends_at) >= b);
        const same = s => ["primitive", "requested_power_w", "charge_source_policy"]
          .every(k => (s[k] ?? null) === (segment[k] ?? null));
        return {starts_at: new Date(a).toISOString(), ends_at: new Date(b).toISOString(),
          optimized: baseline.length > 0 && !baseline.some(same)};
      });
    }

    function selectedExecutionPlanWindows(view) {
      const windows = [];
      const plans = view.planning_status?.execution_plans ?? [];
      for (const plan of plans) {
        for (const segment of plan.segments ?? []) {
          const labels = {
            balance_bidirectional: "NOM / PV laden",
            charge_at_power: "Net import / snel laden",
            discharge_at_power: "Handel / terugleveren",
            balance_discharge_only: "Slim huishoudelijk ontladen",
            standby: "Stand-by",
          };
          windows.push(...pricePlanParts(segment, plan, view.original_price_plan).map(part => ({
            ...part,
            starts_at: part.starts_at,
            ends_at: part.ends_at,
            kind: primitivePlanKind(segment.primitive),
            label: (labels[segment.primitive] ?? displayValue(segment.primitive)) +
              (part.optimized ? " (aangepast)" : ""),
          })));
        }
      }
      for (const placement of view.energy_device_placements?.placements ?? []) {
        windows.push({
          starts_at: placement.starts_at,
          ends_at: placement.ends_at,
          kind: "energy-device-placement",
          label: placement.name,
        });
      }
      return windows;
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

    function activateTab(tabName, revealTools = true) {
      if (tabName === "overview") tabName = "planning";
      const available = Array.from(
        document.querySelectorAll("[data-tab-panel]")
      ).map((panel) => panel.dataset.tabPanel);
      const requested = tabName === "overview" ? "planning" : tabName;
      const selected = available.includes(requested) ? requested : "planning";
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
      if (revealTools && ["strategy", "devices", "technical"].includes(selected)) {
        element("dashboard-tools").open = true;
      }
      if (selected === "history" && !calendarLoaded) loadHouseholdCalendar();
    }

    let calendarLoading = false;
    let calendarLoaded = false;
    async function loadHouseholdCalendar() {
      if (calendarLoading || element("tab-history").hidden) return;
      calendarLoading = true;
      const target = element("household-calendar-history");
      try {
        const response = await fetch("api/household-calendar", { cache: "no-store" });
        if (!response.ok) throw new Error("Kalenderoverzicht tijdelijk niet beschikbaar.");
        const report = await response.json();
        calendarLoaded = true;
        const previousDetailsOpen = target.querySelector("details")?.open ?? false;
        if (report.status !== "ready") {
          target.textContent = report.status === "collecting"
            ? "Kalenderhistorie wordt opgebouwd. Na installatie start de aanvulling automatisch."
            : "Kalenderoverzicht tijdelijk niet beschikbaar; de planning blijft doorlopen.";
          return;
        }
        target.replaceChildren();
        function paragraph(text) {
          const p = document.createElement("p");
          p.textContent = text; target.append(p);
        }
        function table(headings, rows) {
          const wrapper = document.createElement("div");
          wrapper.style.overflowX = "auto";
          const grid = document.createElement("table");
          const head = grid.createTHead().insertRow();
          for (const text of headings) {
            const cell = document.createElement("th");
            cell.textContent = text; head.append(cell);
          }
          const body = grid.createTBody();
          for (const row of rows) {
            const tr = body.insertRow();
            for (const value of row) tr.insertCell().textContent = String(value);
          }
          wrapper.append(grid); target.append(wrapper);
        }
        const energy = (value) => value == null ? "—" : formatEnergyKwh(value);
        const progress = report.source_progress ?? {};
        paragraph("Bijgewerkt: " + formatTimestamp(report.generated_at) + ". " +
          (progress.caught_up ? "Bestaande historie ingelezen. " :
            "Bestaande historie wordt aangevuld. ") +
          "Verwerkt: " + (progress.accepted ?? 0) + " metingen.");
        if (Date.now() - Date.parse(report.generated_at) > 1800000) {
          paragraph("Dit overzicht is ouder dan 30 minuten; " +
            "controleer of de kalenderregistratie actief is.");
        }
        const summaries = [...Object.entries(report.weekday_summary ?? {}),
          ...Object.entries(report.day_type_summary ?? {}).map(([key, value]) =>
            [key === "workday" ? "Werkdagen" : "Weekend", value])];
        table(["Dag", "Bruikbare dagen", "Gemiddeld gemeten", "Mediaan", "Meetdekking"],
          summaries.map(([name, s]) => [name, s.eligible_days,
            energy(s.mean_observed_energy_wh), energy(s.median_observed_energy_wh),
            s.mean_coverage_fraction == null ? "—" :
              (s.mean_coverage_fraction * 100).toFixed(1) + "%"]));
        paragraph("Dagwaarden zijn de gemeten energie; " +
          "meetgaten worden niet tot een volledige dag aangevuld. " +
          "EV-laden, wassen en drogen zijn inbegrepen voor zover gemeten in het huisverbruik.");
        const comparison = report.model_comparison ?? {};
        paragraph("Modelvergelijking over " + (comparison.common_quarters ?? 0) +
          " gemeenschappelijk bruikbare kwartieren, uitsluitend met eerdere dagen. " +
          "Dit is een terugblik op verbruiksmodellen; het toont geen financiële besparing.");
        const labels = {current_clock_quarter: "Huidige klokkwartiermethode",
          same_weekday: "Dezelfde weekdag", workday_weekend: "Werkdag / weekend"};
        table(["Methode", "Gemiddelde absolute fout per kwartier", "Over- / onderschatting"],
          Object.entries(comparison.models ?? {}).map(([key, s]) => [labels[key] ?? key,
            formatMeasurement(s.mean_absolute_quarter_error_wh, "Wh"),
            formatMeasurement(s.mean_signed_quarter_error_wh, "Wh")]));
        const details = document.createElement("section");
        const summary = document.createElement("h3");
        summary.textContent = "Dagsommen en meetdekking (laatste 28 dagen)";
        details.append(summary); target.append(details);
        table(["Datum", "Dag", "Gemeten verbruik", "Dekking", "Status"],
          (report.days ?? []).slice(-28).reverse().map((d) => [d.local_date, d.weekday_name,
            energy(d.observed_energy_wh), (d.coverage_fraction * 100).toFixed(1) + "%",
            !d.closed ? "Dag loopt nog" :
              d.usable_for_profile ? "Bruikbaar" : "Onvoldoende dekking"]));
        details.append(target.lastElementChild);
        details.open = previousDetailsOpen;
      } catch (error) {
        target.textContent = error.message;
      } finally {
        calendarLoading = false;
      }
    }

    function initializeTabs() {
      const technical = element("tab-technical");
      technical.append(document.querySelector(".metadata"), element("status"));
      element("tab-planning").prepend(element("today-summary"), element("plan-decision"));
      movePanelContent("price-timeline", "planning");
      movePanelContent("pv-forecast-actual-chart", "planning");
      movePanelContent("plan-history", "history");
      element("central-health").after(element("storage-mode-override"));
      const history = element("tab-history");
      const power = element("power-history-chart");
      const selfUse = element("self-consumption-history-chart");
      history.prepend(power.previousElementSibling, power,
        selfUse.previousElementSibling, selfUse);
      element("switch-history-period").addEventListener("change", () =>
        renderStorageModeTransitionHistory(lastSwitchEvents));
      document.querySelectorAll(".tab-button").forEach((button) => {
        button.addEventListener("click", () => activateTab(button.dataset.tab));
      });
      activateTab(localStorage.getItem(ACTIVE_TAB_KEY) ?? "planning");
    }

    function captureDashboardFocus() {
      const node = document.activeElement;
      if (!node || !["SUMMARY", "BUTTON", "A", "INPUT", "SELECT", "TEXTAREA"]
        .includes(node.tagName)) return null;
      return {
        node, id: node.id, tag: node.tagName,
        containerId: node.parentElement?.closest("[id]")?.id,
        label: node.getAttribute("aria-label") ?? node.textContent
      };
    }

    function restoreDashboardFocus(saved) {
      if (!saved || saved.node.isConnected) return;
      const active = document.activeElement;
      if (active && active.tagName !== "BODY" && active !== saved.node) return;
      const matches = Array.from(document.querySelectorAll(
        "summary, button, a[href], input, select, textarea"
      )).filter(node => node.tagName === saved.tag && !node.disabled &&
        !node.closest?.("[hidden]") && (saved.id ? node.id === saved.id :
          saved.containerId && node.parentElement?.closest("[id]")?.id === saved.containerId &&
          (node.getAttribute("aria-label") ?? node.textContent) === saved.label));
      if (matches.length === 1) matches[0].focus({preventScroll: true});
    }

    function captureDashboardState() {
      const openStageCards = Array.from(
        document.querySelectorAll("details.stage-card")
      ).map((details) => details.open);
      const openTechnicalDetails = Array.from(
        document.querySelectorAll("details.technical-details")
      ).map((details) => details.open);
      const openTechnicalDetailsByKey = Object.fromEntries(
        Array.from(
          document.querySelectorAll(
            "details.technical-details[data-technical-key]"
          )
        ).map((details) => [details.dataset.technicalKey, details.open])
      );
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
      const openDisclosures = Object.fromEntries(Array.from(
        document.querySelectorAll("details[id]")
      ).map(node => [node.id, node.open]));
      return {
        focus: captureDashboardFocus(),
        openDisclosures,
        openStageCards,
        openTechnicalDetails,
        openTechnicalDetailsByKey,
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
      document.querySelectorAll("details[id]").forEach(node => {
        if (Object.hasOwn(state.openDisclosures ?? {}, node.id)) {
          node.open = state.openDisclosures[node.id];
        }
      });
      Array.from(
        document.querySelectorAll("details.stage-card")
      ).forEach((details, index) => {
        details.open = state.openStageCards[index] ?? false;
      });
      Array.from(
        document.querySelectorAll("details.technical-details")
      ).forEach((details, index) => {
        const key = details.dataset.technicalKey;
        details.open = key
          ? Boolean(state.openTechnicalDetailsByKey?.[key])
          : state.openTechnicalDetails[index] ?? false;
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
      activateTab(state.activeTab ?? "planning", false);
      restoreDashboardFocus(state.focus);
      window.scrollTo(state.windowScrollX, state.windowScrollY);
    }

    function shouldDeferRenderForSelection() {
      if (document.activeElement?.matches("input, select, textarea")) return true;
      const selection = window.getSelection();
      return Boolean(
        selection && !selection.isCollapsed && selection.toString()
      );
    }

    let lastSwitchEvents = [];
    function switchHistoryEvents(events, period, today = financialDate()) {
      return [...events].filter(event => period === "all" ||
        (Number.isFinite(Date.parse(event.occurred_at)) &&
          financialDate(new Date(event.occurred_at)) === today));
    }

    function renderStorageModeTransitionHistory(events) {
      lastSwitchEvents = Array.isArray(events) ? events : [];
      events = switchHistoryEvents(lastSwitchEvents, element("switch-history-period").value);
      const container = element("storage-mode-transition-history");
      container.replaceChildren();
      if (!Array.isArray(events) || events.length === 0) {
        container.textContent =
          "Geen door PicoT uitgevoerde moduswissels in deze periode.";
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
        const values = [
          Number.isNaN(occurredAt.getTime())
            ? displayValue(event.occurred_at)
            : occurredAt.toLocaleString("nl-NL"),
          displayValue(event.previous_vendor_mode),
          displayValue(event.requested_vendor_mode),
          displayValue(event.reason),
          formatConfidence(event.confidence),
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

    function financialValueClass(value) {
      return Number(value) >= 0 ? "financial-positive" : "financial-negative";
    }

    function renderHouseholdEnergySources(breakdown) {
      const panel = document.createElement("section");
      panel.className = "timeline-panel financial-source-panel";
      const sources = Array.isArray(breakdown?.sources)
        ? breakdown.sources : [];
      const sourceMeta = {
        pv_direct: {label: "PV rechtstreeks", color: "#f5c542", value: "vermeden inkoop"},
        battery: {label: "Batterij", color: "#35a862", value: "bruto vermeden inkoop"},
        grid: {label: "Net", color: "#ef6464", value: "kosten"},
      };
      let cursor = 0;
      const stops = [];
      for (const source of sources) {
        const share = Math.max(0, Number(source.share) || 0) * 100;
        const color = sourceMeta[source.source]?.color ?? "#64748b";
        stops.push(`${color} ${cursor}% ${cursor + share}%`);
        cursor += share;
      }
      const chartWrap = document.createElement("div");
      const heading = document.createElement("h3");
      heading.textContent = "Herkomst huishoudelijke energie in deze meetperiode";
      const donut = document.createElement("div");
      donut.className = "financial-donut";
      donut.setAttribute("role", "img");
      donut.setAttribute("aria-label", sources.map((source) => {
        const meta = sourceMeta[source.source] ?? {label: source.source};
        return `${meta.label}: ${formatDutchNumber(source.energy_kwh)} kWh, `
          + `${formatDutchNumber(Number(source.share) * 100)}%`;
      }).join("; "));
      donut.style.background = stops.length
        ? `conic-gradient(${stops.join(", ")})`
        : "#27313d";
      const center = document.createElement("div");
      center.className = "financial-donut-center";
      const total = document.createElement("strong");
      total.textContent = `${formatDutchNumber(breakdown?.household_load_kwh)} kWh`;
      const totalLabel = document.createElement("span");
      totalLabel.className = "muted";
      totalLabel.textContent = "huisverbruik";
      center.append(total, totalLabel);
      donut.append(center);
      chartWrap.append(heading, donut);

      const legend = document.createElement("div");
      legend.className = "financial-source-legend";
      for (const source of sources) {
        const meta = sourceMeta[source.source] ?? {
          label: displayValue(source.source), color: "#64748b", value: "waarde"
        };
        const row = document.createElement("div");
        row.className = "financial-source-row";
        const swatch = document.createElement("span");
        swatch.className = "financial-source-swatch";
        swatch.style.background = meta.color;
        const description = document.createElement("span");
        description.textContent = `${meta.label} · `
          + `${formatDutchNumber(source.energy_kwh)} kWh · `
          + `${formatDutchNumber(Number(source.share) * 100)}%`;
        const amount = document.createElement("span");
        amount.title = meta.value;
        amount.textContent = formatCurrency(source.value_eur);
        row.append(swatch, description, amount);
        legend.append(row);
      }
      panel.append(chartWrap, legend);
      return panel;
    }

    function renderGridChargeReview(review) {
      const container = element("grid-charge-review");
      container.replaceChildren();
      const days = Array.isArray(review.days) ? review.days : [];
      const completed = days.filter(d => d.finalized && d.status === "available");
      const summary = document.createElement("p");
      const avoidable = completed.filter(d => d.avoidable_grid_charge_kwh > 0.1);
      summary.textContent = completed.length
        ? `${avoidable.length} van ${completed.length} volledig beoordeelde dagen: ` +
          `meer dan 0,1 kWh netladen vermijdbaar in deze terugblik.`
        : "Nog geen volledig beoordeelde dagen. De lopende dag telt niet mee in het patroon.";
      container.appendChild(summary);
      const reasons = {
        history_unavailable: "Meetgeschiedenis tijdelijk niet beschikbaar",
        missing_measured_series: "Een benodigde meetreeks ontbreekt",
        main_window_evidence_missing: "Het bijbehorende hoofdlaadvenster ontbreekt",
        configured_maximum_below_daily_target: "Ingesteld maximum ligt onder 100%",
        measurement_start_missing: "Een beginmeting ontbreekt",
        household_measurement_gap: "Onderbreking in de huisverbruikmetingen",
        household_measurement_tail_missing: "Laatste huisverbruikmeting ontbreekt",
        measurement_unavailable: "Onderbreking of ongeldige meting",
        invalid_soc: "Ongeldige SOC-meting",
        price_coverage_incomplete: "Niet alle prijzen beschikbaar",
        flow_soc_mismatch: "Energiemetingen en SOC sluiten onvoldoende op elkaar aan",
        power_balance_mismatch: "De gemeten energiestromen sluiten onvoldoende op elkaar aan",
        reference_replay_not_feasible:
          "Dagdoel, export of eindvoorraad nog niet aantoonbaar haalbaar",
        settings_changed_during_day: "Batterij-instellingen veranderden tijdens de dag",
        review_resource_limit: "Te veel meetpunten voor deze terugblik"
      };
      if (!days.length) {
        const empty = document.createElement("p");
        empty.textContent = "Kostenverschil nog niet beschikbaar. Meetgegevens verzamelen; " +
          "automatische verversing elke vijf minuten.";
        container.appendChild(empty);
        return;
      }
      const latest = [...days].reverse().find(d => d.status === "available");
      const cost = document.createElement("p");
      cost.className = "grid-review-cost";
      cost.textContent = latest
        ? `Kostenverschil bij minder netladen (${latest.delivery_date ?? latest.day}): ` +
          `${formatCurrency(latest.cost_difference_eur)} — ` +
          (latest.finalized ? "volledige dag" : "voorlopige terugblik")
        : "Kostenverschil nog niet beschikbaar: " +
          (reasons[days.at(-1)?.reason] ?? "onvoldoende meet- of prijsgegevens") + ".";
      container.appendChild(cost);
      const scroll = document.createElement("div");
      scroll.style.overflowX = "auto";
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const row = document.createElement("tr");
      for (const label of ["Dag", "Status", "Net naar accu", "Vermijdbaar*",
        "Kostenverschil (€)*", "Piek SOC zonder netladen", "PV afwijking t.o.v. plan"]) {
        const th = document.createElement("th"); th.textContent = label; row.appendChild(th);
      }
      head.appendChild(row); table.appendChild(head);
      const body = document.createElement("tbody");
      const kwh = value => value === null || value === undefined ? "—"
        : `${formatDutchNumber(value)} kWh`;
      for (const day of [...days].reverse()) {
        const tr = document.createElement("tr");
        const ok = day.status === "available";
        const status = ok ? (day.finalized ? "Volledig" : "Voorlopig")
          : (reasons[day.reason] ?? "Onvoldoende gegevens");
        const values = [day.day, status, kwh(day.measured_grid_charge_kwh),
          ok ? kwh(day.avoidable_grid_charge_kwh) : "—",
          ok ? formatCurrency(day.cost_difference_eur) : "—",
          day.pv_only_peak_soc_percent == null ? "—"
            : `${formatDutchNumber(day.pv_only_peak_soc_percent)}%`,
          kwh(day.pv_comparison?.difference_kwh)];
        for (const value of values) {
          const td = document.createElement("td"); td.textContent = value; tr.appendChild(td);
        }
        body.appendChild(tr);
        const alignment = day.aligned_measurements;
        if (alignment) {
          const alignmentRow = document.createElement("tr");
          const alignmentCell = document.createElement("td");
          alignmentCell.colSpan = 7;
          const details = document.createElement("section");
          const summary = document.createElement("h3");
          summary.textContent = alignment.status === "unavailable"
            ? "Kwartierbalans niet beschikbaar"
            : `Kwartierbalans: ${alignment.derived_interval_count} berekend, ` +
              `${alignment.invalid_interval_count} onbruikbaar`;
          details.appendChild(summary);
          const explanation = document.createElement("p");
          explanation.textContent = "Afgeleid huisverbruik per tijdvak. " +
            "Verschillen in sensortiming blijven onzeker; geen vervanging van ontbrekende " +
            "metingen en geen zelfstandig bewijs van besparing.";
          details.appendChild(explanation);
          for (const interval of alignment.invalid_intervals ?? []) {
            const line = document.createElement("p");
            const reason = interval.reason === "negative_household_energy_balance"
              ? "Negatieve energiebalans" : "Onvolledige brongegevens";
            line.textContent = `${new Date(interval.starts_at).toLocaleString("nl-NL")} – ` +
              `${new Date(interval.ends_at).toLocaleString("nl-NL")}: ${reason}`;
            details.appendChild(line);
          }
          if (alignment.omitted_invalid_interval_count) {
            const line = document.createElement("p");
            line.textContent = `Nog ${alignment.omitted_invalid_interval_count} ` +
              "onbruikbare tijdvakken.";
            details.appendChild(line);
          }
          alignmentCell.appendChild(details); alignmentRow.appendChild(alignmentCell);
          body.appendChild(alignmentRow);
        }
        const coverage = day.measurement_coverage ?? {};
        const missing = Object.entries(coverage).filter(([, item]) => item.gap_count > 0);
        if (missing.length) {
          const detailRow = document.createElement("tr");
          const cell = document.createElement("td");
          cell.colSpan = 7;
          const details = document.createElement("section");
          const label = document.createElement("h3");
          label.textContent = `Meetonderbrekingen (${missing.length} meetreeksen)`;
          details.appendChild(label);
          for (const [role, item] of missing) {
            for (const gap of item.gaps ?? []) {
              const line = document.createElement("p");
              line.textContent = `${item.source_entity_id ?? role}: ` +
                `${reasons[gap.reason] ?? gap.reason} · ` +
                `${new Date(gap.starts_at).toLocaleString("nl-NL")} – ` +
                `${new Date(gap.ends_at).toLocaleString("nl-NL")}`;
              details.appendChild(line);
            }
            if (item.omitted_gap_count) {
              const more = document.createElement("p");
              more.textContent = `Nog ${item.omitted_gap_count} onderbrekingen voor ${role}.`;
              details.appendChild(more);
            }
          }
          cell.appendChild(details); detailRow.appendChild(cell); body.appendChild(detailRow);
        }
      }
      table.appendChild(body); scroll.appendChild(table); container.appendChild(scroll);
      const note = document.createElement("p");
      note.className = "muted";
      note.textContent = "* Modelschatting: netladen op de oorspronkelijke momenten stapsgewijs " +
        "verminderd, extra PV via NOM benut. Geen globaal minimum. Kostenverschil inclusief " +
        "huisimport, teruglevering, verliezen en slijtage; eindvoorraad blijft behouden. " +
        "PV-afwijking gebruikt de vastgelegde (LOWER + CENTRAL) / 2 " +
        "over dezelfde gesloten intervallen.";
      container.appendChild(note);
    }

    // Financial presentation only: consume existing per-metric results, never repair records.
    const financialColumns = [
      ["Netresultaat", "actual_energy_cost_eur", -1],
      ["Batterijvoordeel netto", "net_battery_value_eur", 1],
      ["Extra PicoT-resultaat netto", "net_picot_value_eur", 1],
    ];
    const financialQuality = {
      available: "Beschikbaar volgens de opgeslagen meetcontrole",
      estimated: "Geldig: volledig berekend met afgeleide meetgegevens",
      historical: "Historisch: niet opnieuw beoordeeld met de huidige kwaliteitscriteria",
      incomplete: "Onvolledig: onvoldoende gegevens voor dit bedrag",
    };
    function financialMetric(day, name, sign = 1) {
      const item = day?.financial_metrics
        ? day.financial_metrics.values?.[name]
        : {status: day?.status, value_eur: day?.[name]};
      const valid = ["available", "estimated"].includes(item?.status) &&
        typeof item.value_eur === "number" && Number.isFinite(item.value_eur);
      return {value: valid ? sign * item.value_eur : null,
        quality: !valid ? "incomplete" : !day.financial_metrics ? "historical" : item.status};
    }
    function financialDate(now = new Date()) {
      return new Intl.DateTimeFormat("sv-SE", {timeZone: "Europe/Amsterdam",
        year: "numeric", month: "2-digit", day: "2-digit"}).format(now);
    }
    function financialDateShift(day, offset) {
      const date = new Date(day + "T12:00:00Z");
      date.setUTCDate(date.getUTCDate() + offset);
      return date.toISOString().slice(0, 10);
    }
    function financialMonday(day) {
      return financialDateShift(day, -((new Date(day + "T12:00:00Z").getUTCDay() + 6) % 7));
    }
    function financialWeek(days, monday, today) {
      const byDay = new Map(days.map(day => [day.day, day]));
      return Array.from({length: 7}, (_, index) => {
        const date = financialDateShift(monday, index);
        return {date, future: date > today, record: byDay.get(date)};
      });
    }
    function financialWeekTotal(rows, name, sign) {
      const elapsed = rows.filter(row => !row.future);
      const values = elapsed.map(row => financialMetric(row.record, name, sign));
      const known = values.filter(item => item.value !== null);
      return {value: known.length ? known.reduce((sum, item) => sum + item.value, 0) : null,
        count: known.length, expected: elapsed.length,
        qualities: [...new Set(values.map(item => item.quality))]};
    }
    function financialHouseSources(day) {
      // A partial financial result may retain an older source allocation. Do not plot it.
      if (financialMetric(day, "net_total_energy_value_eur").value === null) return null;
      const breakdown = day?.household_energy_sources;
      const sources = breakdown?.sources;
      if (!Array.isArray(sources) || sources.length !== 3) return null;
      const values = ["pv_direct", "grid", "battery"].map(key => {
        const matches = sources.filter(source => source.source === key);
        return matches.length === 1 ? matches[0].energy_kwh : null;
      });
      if (values.some(value => typeof value !== "number" || !Number.isFinite(value) || value < 0))
        return null;
      const total = values.reduce((sum, value) => sum + value, 0);
      if (typeof breakdown.household_load_kwh !== "number" ||
          !Number.isFinite(breakdown.household_load_kwh) ||
          Math.abs(total - breakdown.household_load_kwh) > 0.001) return null;
      return {values, total, quality: financialMetric(day, "net_total_energy_value_eur").quality};
    }
    function financialFullDay(day) {
      // Validate the period of the selected amount, not a newer raw record's period.
      const period = day?.financial_metrics ?? day;
      const midnight = (value, date) => {
        if (typeof value !== "string" || !/(Z|[+-][0-9]{2}:[0-9]{2})$/.test(value))
          return false;
        const instant = new Date(value);
        if (!Number.isFinite(instant.getTime()) || instant.getUTCMilliseconds() !== 0)
          return false;
        const time = new Intl.DateTimeFormat("en-GB", {timeZone: "Europe/Amsterdam",
          hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"});
        return financialDate(instant) === date && time.format(instant) === "00:00:00";
      };
      if (!day?.day || !midnight(period?.starts_at, day.day)) return false;
      return midnight(period?.ends_at, financialDateShift(day.day, 1));
    }
    function financialPaybackEstimate(days, cumulative, today) {
      const remaining = cumulative?.remaining_eur;
      if (typeof remaining !== "number" || !Number.isFinite(remaining) || remaining < 0)
        return {reason: "Het resterende aankoopbedrag is niet beschikbaar."};
      if (remaining === 0 && cumulative.battery_purchase_eur > 0)
        return {completed: true};
      const byDay = new Map(days.map(day => [day.day, day]));
      const records = Array.from({length: 28}, (_, index) =>
        byDay.get(financialDateShift(today, -index - 1)));
      const period = records.map(day => financialMetric(day, "net_battery_value_eur"));
      const missing = period.filter(item => item.value === null).length;
      if (missing) return {
        reason: `${missing} van de laatste 28 afgesloten dagen missen een batterijbedrag.`};
      const partial = records.filter(day => !financialFullDay(day)).length;
      if (partial) return {
        reason: `${partial} van de laatste 28 dagen hebben geen bewezen volledige meetperiode.`};
      const daily = period.reduce((sum, item) => sum + item.value, 0) / 28;
      if (daily <= 0) return {
        reason: "Het netto batterijvoordeel over de laatste 28 dagen is niet positief."};
      return {days: Math.ceil(remaining / daily), daily,
        estimated: period.some(item => item.quality === "estimated"),
        historical: period.some(item => item.quality === "historical")};
    }
    let financialSelectedWeek = null;
    const financialOpenEvidence = new Set();
    function financialDisclosure(detail, key) {
      detail.financialDisclosureKey = key;
      detail.open = financialOpenEvidence.has(key);
    }
    function renderFinancialResults(financial) {
      const container = element("financial-results");
      // Capture synchronously: a refresh can arrive before the browser's toggle event.
      for (const detail of container.querySelectorAll("details")) {
        const key = detail.financialDisclosureKey;
        if (!key) continue;
        if (detail.open) financialOpenEvidence.add(key); else financialOpenEvidence.delete(key);
      }
      container.replaceChildren();
      const today = financialDate();
      const currentWeek = financialMonday(today);
      const days = financial?.days ?? [];
      const weeks = [...new Set([currentWeek, ...days.filter(day => day.day <= today)
        .map(day => financialMonday(day.day))])].sort().reverse();
      if (!weeks.includes(financialSelectedWeek)) financialSelectedWeek = currentWeek;
      const rows = financialWeek(days, financialSelectedWeek, today);
      const node = (tag, text, className) => {
        const result = document.createElement(tag);
        if (text !== undefined) result.textContent = text;
        if (className) result.className = className;
        return result;
      };
      const dateLabel = date => new Intl.DateTimeFormat("nl-NL", {
        day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
      }).format(new Date(date + "T12:00:00Z"));
      const navigation = node("div", undefined, "financial-week-nav");
      navigation.append(node("h3", "Je energieresultaat"));
      const select = node("select");
      select.setAttribute("aria-label", "Kies een week");
      for (const week of weeks) {
        const option = node("option", `${week === currentWeek ? "Deze week · " : ""}` +
          `${dateLabel(week)} – ${dateLabel(financialDateShift(week, 6))}`);
        option.value = week;
        select.append(option);
      }
      select.value = financialSelectedWeek;
      select.onchange = () => {
        financialSelectedWeek = select.value; renderFinancialResults(financial);
      };
      const navigate = (caption, offset) => {
        const button = node("button", caption);
        const index = weeks.indexOf(financialSelectedWeek) + offset;
        button.disabled = index < 0 || index >= weeks.length;
        button.onclick = () => {
          financialSelectedWeek = weeks[index]; renderFinancialResults(financial);
        };
        return button;
      };
      navigation.append(navigate("‹ Vorige", 1), select, navigate("Volgende ›", -1));
      container.append(navigation);
      const current = rows.find(row => row.date === today)?.record;
      const until = current?.financial_metrics?.ends_at ?? current?.ends_at;
      container.append(node("p", "Positief = opbrengst of voordeel · negatief = kosten. " +
        "De drie resultaten zijn niet bij elkaar op te tellen." +
        (rows.some(row => row.date === today) ? (until ? ` Vandaag tot ${formatTimestamp(until)}.` :
          " Vandaag is nog niet afgerond.") : ""), "muted"));
      if (current?.financial_metrics?.pending_period?.reason === "current_quarter_not_closed") {
        container.append(node("p", "Het lopende kwartier is nog niet afgerond. " +
          "Het resultaat van vandaag geldt tot het getoonde tijdstip.", "muted"));
      }
      const evidence = node("section");
      financialDisclosure(evidence, `week:${financialSelectedWeek}`);
      const special = rows.filter(row => !row.future && financialColumns.some(([, name, sign]) =>
        !["available", "estimated"].includes(
          financialMetric(row.record, name, sign).quality))).length;
      evidence.append(node("h3",
        `Onderbouwing en meetkwaliteit · ${special} dagen met bijzonderheden`));
      evidence.append(node("p",
        "Elk bedrag heeft een eigen meetcontrole. Netresultaat is gebaseerd op " +
        "netinkoop en teruglevering; batterij- en PicoT-voordeel vragen " +
        "aanvullende bronmetingen. " +
        "Historische bedragen zijn niet opnieuw beoordeeld. Exclusief Zonneplan-zonnebonus.",
        "muted"));
      const evidenceByDay = new Map();
      for (const row of rows.filter(row => !row.future)) {
        const detail = node("section");
        financialDisclosure(detail, `day:${row.date}`);
        detail.append(node("h3", dateLabel(row.date)));
        for (const [label, name, sign] of financialColumns) {
          const value = financialMetric(row.record, name, sign);
          detail.append(node("p",
            `${label}: ${value.value === null ? "—" : formatCurrency(value.value)} · ` +
            financialQuality[value.quality]));
        }
        if (row.record) {
          const extra = node("div");
          renderFinancialDayEvidence({today: row.record, days: []}, extra);
          detail.append(extra);
        } else detail.append(node("p", "Voor deze dag is geen dagrecord beschikbaar."));
        evidence.append(detail);
        evidenceByDay.set(row.date, detail);
      }
      const marker = (quality, day, label = "Bronverdeling") => {
        const button = node("button", quality === "historical" ? "◷" : "!",
          "financial-quality-marker");
        button.title = financialQuality[quality];
        button.setAttribute("aria-label", `${label}: ${day ? dateLabel(day) + ": " : ""}` +
          `${financialQuality[quality]}. Open onderbouwing`);
        button.onclick = () => {
          evidence.open = true;
          const target = evidenceByDay.get(day) ?? evidence;
          if (target !== evidence) target.open = true;
          const heading = target.querySelector("h3");
          heading?.setAttribute("tabindex", "-1");
          heading?.focus();
          target.scrollIntoView({block: "nearest"});
        };
        return button;
      };
      const cards = node("section", undefined, "financial-grid");
      for (const [label, name, sign] of financialColumns) {
        const total = financialWeekTotal(rows, name, sign);
        const card = node("div", undefined, "metric");
        card.append(node("span", label, "muted"));
        const value = node("div", total.value === null ? "—" : formatCurrency(total.value),
          "value");
        for (const quality of total.qualities.filter(item =>
          !["available", "estimated"].includes(item))) {
          value.append(marker(quality, undefined, label));
        }
        card.append(value, node("small",
          `${total.count < total.expected ? "Deeltotaal" : "Weektotaal"} · ` +
          `${total.count} van ${total.expected} dagen` + (current ?
            " · vandaag loopt nog" : ""), "muted"));
        cards.append(card);
      }
      container.append(cards);
      const table = node("table");
      const head = node("thead");
      const headers = node("tr");
      for (const label of ["Dag", ...financialColumns.map(item => item[0])]) {
        headers.append(node("th", label));
      }
      const storedHeader = node("th", "Geschatte batterijwaarde ⓘ");
      storedHeader.title = "Geschatte besparing bij eigen gebruik, na reserve en ontlaadverlies, " +
        "tegen de gemiddelde inkoopprijs komende 24 uur. Geen winst; niet optellen. " +
        "Per dag de laatst vastgelegde schatting; — = onbekend.";
      const storedHelp = node("button", "ⓘ", "financial-quality");
      storedHelp.type = "button";
      storedHelp.setAttribute("aria-label", "Toelichting geschatte batterijwaarde");
      storedHelp.setAttribute("aria-controls", "financial-stored-value-help");
      storedHelp.setAttribute("aria-expanded", "false");
      const storedExplanation = node("p", storedHeader.title, "muted");
      storedExplanation.id = "financial-stored-value-help";
      storedExplanation.hidden = true;
      storedHelp.onclick = () => {
        storedExplanation.hidden = !storedExplanation.hidden;
        storedHelp.setAttribute("aria-expanded", String(!storedExplanation.hidden));
      };
      storedHeader.textContent = "Geschatte batterijwaarde ";
      storedHeader.append(storedHelp);
      headers.append(storedHeader);
      head.append(headers); table.append(head);
      const body = node("tbody");
      for (const row of rows) {
        const tr = node("tr");
        tr.append(node("td", dateLabel(row.date) + (row.date === today ? " · vandaag" : "")));
        for (const [label, name, sign] of financialColumns) {
          const item = financialMetric(row.record, name, sign);
          const cell = node("td", row.future ? "·" : item.value === null ?
            "—" : formatCurrency(item.value));
          if (!row.future && !["available", "estimated"].includes(item.quality)) {
            cell.append(marker(item.quality, row.date, label));
          }
          tr.append(cell);
        }
        const stored = row.record?.estimated_battery_value;
        const storedValue = stored?.status === "estimated" &&
          typeof stored.value_eur === "number" && Number.isFinite(stored.value_eur)
          ? stored.value_eur : null;
        tr.append(node("td", row.future ? "·" : storedValue === null ? "—" :
          `≈ ${formatCurrency(storedValue)}`));
        body.append(tr);
      }
      table.append(body);
      const scroll = node("div"); scroll.style.overflowX = "auto"; scroll.append(table);
      container.append(scroll, storedExplanation);
      const chart = node("section", undefined, "timeline-panel financial-week-sources");
      chart.append(node("h3", "Waar komt je huisverbruik vandaan?"));
      const sourceMeta = [["PV", "#f5c542"], ["Net", "#ef6464"], ["Batterij", "#35a862"]];
      const legend = node("p");
      for (const [label, color] of sourceMeta) {
        const dot = node("span", "● "); dot.style.color = color;
        dot.setAttribute("aria-hidden", "true");
        legend.append(dot, node("span", `${label}   `));
      }
      chart.append(legend);
      const allocations = rows.map(row => row.future ? null : financialHouseSources(row.record));
      const maximum = Math.max(1, ...allocations.filter(Boolean).map(item => item.total));
      rows.forEach((row, index) => {
        const line = node("div", undefined, "financial-source-day");
        line.append(node("span", new Intl.DateTimeFormat("nl-NL", {weekday: "short",
          timeZone: "UTC"})
          .format(new Date(row.date + "T12:00:00Z"))));
        const allocation = allocations[index];
        const bar = node("div", undefined, "financial-source-bar");
        if (allocation) {
          const description = sourceMeta.map(([label], i) =>
            `${label}: ${formatDutchNumber(allocation.values[i])} kWh`).join(" · ");
          bar.setAttribute("role", "img"); bar.setAttribute("aria-label",
            `${dateLabel(row.date)}: ${description}`);
          bar.title = description;
          allocation.values.forEach((value, i) => {
            const segment = node("span"); segment.style.width = `${value / maximum * 100}%`;
            segment.style.background = sourceMeta[i][1]; bar.append(segment);
          });
          line.append(bar, node("span", `${formatDutchNumber(allocation.total)} kWh`));
          if (!["available", "estimated"].includes(allocation.quality))
            line.append(marker(allocation.quality, row.date));
        } else line.append(bar, node("span", row.future ? "·" : "Geen volledige verdeling",
          "muted"));
        chart.append(line);
      });
      chart.append(node("p", "Dagverbruik in kWh · gelijke schaal voor alle dagen. " +
        "Batterij is de directe bron; de eerdere laadbron wordt hier niet uitgesplitst. " +
        "Bronhoeveelheden staan ook in de onderbouwing.", "muted"));
      container.append(chart, evidence);
      const payback = node("section", undefined, "timeline-panel financial-week-sources");
      payback.append(node("h3", "Terugverdienen Zendure-batterij"));
      const estimate = financialPaybackEstimate(days, financial.cumulative, today);
      const duration = estimate.days === undefined ? null : estimate.days < 31 ?
        "minder dan een maand" :
        estimate.days < 365 ? `${Math.ceil(estimate.days / 30.4375)} maanden` :
          `${formatDutchNumber(estimate.days / 365.25)} jaar`;
      payback.append(node("p", estimate.completed ?
        "Aankoopbedrag terugverdiend volgens de geregistreerde resultaten." :
        duration ? `Geschatte resterende terugverdientijd: circa ${duration}` :
          "Geschatte resterende terugverdientijd: nog niet te bepalen.", "value"));
      const estimateEvidence = node("section");
      financialDisclosure(estimateEvidence, "payback-estimate");
      estimateEvidence.append(node("h3", "Onderbouwing van de tijdschatting"));
      estimateEvidence.append(node("p", (estimate.reason ? estimate.reason + " " : "") +
        "Resterend aankoopbedrag gedeeld door het gemiddelde netto batterijvoordeel " +
        "van de laatste 28 afgesloten dagen. " +
        "Alleen meetperioden van middernacht tot de volgende middernacht " +
        "in Amsterdam tellen mee. " +
        "Een kortere of onbekende meetperiode blokkeert de schatting. " +
        "Vandaag telt niet mee; ontbrekende dagen worden niet als nul of als " +
        "gemiddelde ingevuld. " +
        "De prognose houdt geen rekening met seizoenen, toekomstige tarieven of de zonnebonus. " +
        "Dit is een schatting, geen garantie." +
        (estimate.daily !== undefined ?
          ` Gebruikt daggemiddelde: ${formatCurrency(estimate.daily)}.` : "") +
        (estimate.estimated ? " Bevat afgeleide dagbedragen." : "") +
        (estimate.historical ? " Bevat historische, niet opnieuw beoordeelde dagbedragen." : "")));
      payback.append(estimateEvidence);
      const paybackBody = node("div");
      renderFinancialDayEvidence({days, cumulative: financial.cumulative ?? {},
        paybackOnly: true}, paybackBody);
      payback.append(paybackBody); container.append(payback);
    }

    function renderFinancialDayEvidence(financial, container) {
      container.replaceChildren();
      const today = financial?.today;
      const days = financial.days ?? [];
      const labels = {
        pv_generation: "PV-productie", household_load: "Huisverbruik",
        grid_import: "Netinkoop", grid_export: "Teruglevering",
        battery_charge: "Batterijladen", battery_discharge: "Batterijontladen",
      };
      const reasons = {
        measurement_coverage_incomplete: "Meetgegevens zijn onvolledig",
        missing_measured_series: "Een benodigde meetreeks ontbreekt",
        measurement_start_missing: "Beginwaarde ontbreekt",
        measurement_unavailable: "Bron tijdelijk niet beschikbaar",
        household_measurement_gap: "Onderbreking in huisverbruiksmetingen",
        household_measurement_tail_missing: "Recente huisverbruiksmetingen ontbreken",
        measurement_history_unavailable: "Meetgeschiedenis kon niet volledig worden gelezen",
        measurement_period_mismatch: "Meetperioden sluiten niet op elkaar aan",
        price_coverage_incomplete: "Niet alle prijzen zijn beschikbaar",
        storage_physical_state_missing: "Batterijgegevens ontbreken",
        financial_result_unavailable: "Resultaat nog niet te bepalen",
        financial_metric_evaluation_failed: "Financiële meetcontrole kon niet worden afgerond",
        financial_settings_changed_during_day: "Instellingen zijn tijdens de dag veranderd",
        financial_closing_soc_missing: "Batterijstand aan het einde van de meetperiode ontbreekt",
        financial_inference_stale: "De aanvullende berekening is meer dan 15 minuten achtergelopen",
      };
      const reasonText = reason => reasons[reason] ?? "Resultaat nog niet te bepalen";
      const metric = (day, name) => {
        if (day?.financial_metrics) return day.financial_metrics.values?.[name] ??
          {status: "incomplete", reason: day.financial_metrics.reason};
        return {status: day?.status, value_eur: day?.[name], reason: day?.reason};
      };
      const amount = item => ["available", "estimated"].includes(item.status) &&
        typeof item.value_eur === "number" && Number.isFinite(item.value_eur)
        ? item.value_eur : null;
      const money = (day, name, sign=1) => {
        const value = amount(metric(day, name));
        return value === null ? "—" :
          (metric(day, name).status === "estimated" ? "≈ " : "") + formatCurrency(sign * value);
      };
      const todayStatus = today?.financial_metrics?.status ?? today?.status;
      if (Object.hasOwn(financial, "today") &&
          (!today || !["available", "estimated"].includes(todayStatus))) {
        const empty = document.createElement("p");
        empty.className = "empty-panel";
        empty.textContent = today
          ? "Dagresultaat onvolledig. Beschikbare bedragen blijven zichtbaar."
          : "Nog geen volledige financiële meetperiode beschikbaar.";
        container.append(empty);
      }
      if (today) {
        const period = document.createElement("p");
        period.className = "muted";
        const measuredUntil = today.financial_metrics?.ends_at ?? today.ends_at;
        period.textContent = measuredUntil
          ? `Resultaat tot ${formatTimestamp(measuredUntil)}.` : `Dag: ${today.day ?? "onbekend"}.`;
        container.append(period);
        const cards = document.createElement("section");
        cards.className = "financial-grid";
        const values = [
          ["Netto energieresultaat in deze periode", "actual_energy_cost_eur", -1],
          ["Kosten netinkoop", "grid_import_cost_eur", -1],
          ["Opbrengst teruglevering", "grid_export_revenue_eur", 1],
          ["Totale energiebesparing netto", "net_total_energy_value_eur", 1],
          ["Bruto batterijvoordeel", "gross_battery_value_eur", 1],
          ["Slijtage batterij", "battery_wear_eur", -1],
          ["Netto batterijvoordeel", "net_battery_value_eur", 1],
          ["Bruto extra PicoT-resultaat", "gross_picot_value_eur", 1],
          ["Netto extra PicoT-resultaat", "net_picot_value_eur", 1],
        ];
        for (const [label, name, sign] of values) {
          const item = metric(today, name);
          const value = amount(item);
          const card = document.createElement("div");
          card.className = "metric";
          const title = document.createElement("span");
          title.className = "muted";
          title.textContent = label;
          const shownAmount = document.createElement("span");
          shownAmount.className = "value " +
            (value === null ? "muted" : financialValueClass(sign * value));
          shownAmount.textContent = money(today, name, sign);
          card.append(title, shownAmount);
          if (value === null) {
            const note = document.createElement("small");
            note.className = "muted";
            const sources = (item.missing_roles ?? []).map(role => labels[role] ?? role);
            note.textContent = reasonText(item.reason) +
              (sources.length ? `: ${sources.join(", ")}` : "");
            card.append(note);
          } else if (item.status === "estimated") {
            const note = document.createElement("small");
            note.className = "muted";
            note.textContent = "Afgeleid uit bronmetingen, nachtstatus of korte onderbrekingen.";
            card.append(note);
          }
          cards.append(card);
        }
        container.append(cards);
        const coverage = today.financial_metrics?.measurement_coverage ??
          today.coverage_by_role ?? {};
        const details = document.createElement("section");
        financialDisclosure(details, `day:${today.day}:gaps`);
        const detailsTitle = document.createElement("h3");
        detailsTitle.textContent = "Ontbrekende meetgegevens";
        details.style.overflowWrap = "anywhere";
        details.append(detailsTitle);
        let gapCount = 0;
        for (const [role, source] of Object.entries(coverage)) {
          const gaps = source.gaps ?? (source.start_anchor_available === false ? [{
            reason: "measurement_start_missing", starts_at: today.starts_at,
            ends_at: source.first_point_at ?? today.ends_at,
          }] : []);
          for (const gap of gaps) {
            const line = document.createElement("p");
            line.textContent = `${labels[role] ?? role}: ${reasonText(gap.reason)} · ` +
              `${formatTimestamp(gap.starts_at)} – ${formatTimestamp(gap.ends_at)}` +
              (source.source_entity_id ? ` · ${source.source_entity_id}` : "");
            details.append(line);
            gapCount += 1;
          }
          if (source.omitted_gap_count) {
            const more = document.createElement("p");
            more.textContent = `${labels[role] ?? role}: ` +
              `nog ${source.omitted_gap_count} onderbrekingen.`;
            details.append(more);
            gapCount += 1;
          }
        }
        if (gapCount) container.append(details);
        const solarStatus = today.financial_metrics?.solar_history_status;
        if (coverage.pv_generation?.gap_count && solarStatus && solarStatus !== "available") {
          const note = document.createElement("p");
          note.className = "muted";
          note.textContent = "Ontbrekende PV kan niet als nachtwaarde worden afgeleid: " +
            "zonhistorie is niet beschikbaar.";
          container.append(note);
        }
        const inferences = today.financial_metrics?.inferences ?? [];
        if (inferences.length) {
          const inferred = document.createElement("section");
          financialDisclosure(inferred, `day:${today.day}:inferences`);
          const title = document.createElement("h3");
          title.textContent = "Afgeleide meetgegevens";
          inferred.append(title);
          const kinds = {night_zero: "Nachtelijke PV als 0 W afgeleid",
            bounded_gap: "Korte onderbreking begrensd geschat",
            flow_balance: "Huisverbruik afgeleid uit volledige kwartierbalansen"};
          for (const item of inferences) {
            const line = document.createElement("p");
            line.textContent = `${labels[item.role] ?? item.role}: ` +
              `${kinds[item.kind] ?? "Afgeleid"} · ${formatTimestamp(item.starts_at)} – ` +
              `${formatTimestamp(item.ends_at)}`;
            inferred.append(line);
          }
          const uncertainty = document.createElement("p");
          uncertainty.textContent = "Maximale energieafwijking door korte brononderbrekingen: " +
            `${formatDutchNumber(today.financial_metrics.maximum_estimation_error_wh ?? 0)} Wh. ` +
            "Dit begrenst alleen korte brononderbrekingen. Nachtwaarden blijven een afleiding; " +
            "meet- en modelonzekerheid zijn niet meegerekend.";
          inferred.append(uncertainty);
          container.append(inferred);
        }
        if (today.financial_inference_status?.status === "unavailable") {
          const note = document.createElement("p");
          note.className = "muted";
          note.textContent = "Aanvullende financiële afleiding niet beschikbaar: " +
            reasonText(today.financial_inference_status.reason) + ".";
          container.append(note);
        }
        if (["available", "estimated"].includes(todayStatus)) {
          container.append(renderHouseholdEnergySources(today.household_energy_sources ?? {}));
        }
        if (["gross_battery_value_eur", "battery_wear_eur", "net_battery_value_eur"]
            .every(name => amount(metric(today, name)) !== null)) {
          const equation = document.createElement("section");
          equation.className = "timeline-panel financial-equation";
          equation.setAttribute(
            "aria-label",
            "Bruto batterijvoordeel − slijtage = netto batterijvoordeel"
          );
          for (const [label, name, symbol] of [
            ["Bruto batterijvoordeel", "gross_battery_value_eur", null],
            [null, null, "−"],
            ["Slijtage", "battery_wear_eur", null],
            [null, null, "="],
            ["Netto batterijvoordeel", "net_battery_value_eur", null],
          ]) {
            const part = document.createElement("div");
            if (symbol) {
              part.className = "financial-equation-symbol";
              part.textContent = symbol;
            } else {
              part.className = "financial-equation-part";
              const caption = document.createElement("span");
              caption.className = "muted";
              caption.textContent = label;
              const amount = document.createElement("strong");
              amount.className = "value";
              amount.textContent = money(today, name);
              part.append(caption, amount);
            }
            equation.append(part);
          }
          container.append(equation);
        }
      }
      if (!financial.cumulative) return;
      const cumulative = financial.cumulative;
      const payback = document.createElement("section");
      payback.className = financial.paybackOnly ? "" : "timeline-panel";
      const heading = document.createElement("h3");
      heading.textContent = "Terugverdienen batterij";
      const summary = document.createElement("p");
      const percentage = Math.max(0, Math.min(100,
        Number(cumulative.repaid_fraction ?? 0) * 100));
      const included = cumulative.included_battery_days ?? days.filter(
        day => amount(metric(day, "net_battery_value_eur")) !== null).length;
      const excluded = cumulative.excluded_battery_days ?? days.length - included;
      summary.textContent = included ? [
        `${formatCurrency(cumulative.net_battery_value_eur)} netto terugverdiend`,
        `${formatCurrency(cumulative.remaining_eur)} resterend`,
        `${formatDutchNumber(percentage)}% van ${formatCurrency(cumulative.battery_purchase_eur)}`,
      ].join(" · ") : "Nog geen batterijresultaten om op te tellen.";
      const coverageNote = document.createElement("p");
      coverageNote.className = "muted";
      coverageNote.textContent = `${included} dagresultaten meegeteld · ${excluded} onvolledig.`;
      if (cumulative.estimated_battery_days) {
        coverageNote.textContent +=
          ` Daarvan ${cumulative.estimated_battery_days} met afgeleide bedragen.`;
      }
      const track = document.createElement("div");
      track.className = "payback-track";
      const fill = document.createElement("div");
      fill.className = "payback-fill";
      fill.style.width = `${percentage}%`;
      track.append(fill);
      if (!financial.paybackOnly) payback.append(heading);
      payback.append(summary, coverageNote);
      if (included) payback.append(track);
      container.append(payback);
    }
    async function markPlannerStress() {
      const note = window.prompt(
        "Korte toelichting (optioneel)",
        "Batterij handmatig ontladen"
      );
      if (note === null) return;
      const response = await fetch("api/planner-comparison/stress", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({marker_id: crypto.randomUUID(), note}),
      });
      if (!response.ok) {
        window.alert("De stresstestmarkering kon niet worden opgeslagen.");
      } else {
        loadView();
      }
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
        const details = document.createElement("section");
        const incidentKey = [
          incident.incident_id,
          incident.event,
          incident.captured_at_utc,
          incident.run_id,
        ].map(displayValue).join("|");
        details.dataset.incidentKey = incidentKey;
        details.open = openIncidentKeys.has(incidentKey);
        const summary = document.createElement("h3");
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

    let routeChoiceRequestPending = false;

    function renderRouteChoices(state) {
      const choices = Array.isArray(state?.choices) ? state.choices : [];
      const panel = element("route-choice-panel");
      const container = element("route-choices");
      panel.hidden = choices.length === 0;
      container.replaceChildren();
      const statuses = {
        offered: "Alternatief met meer zonnestroom beschikbaar",
        pending: "PicoT controleert je keuze; het huidige plan blijft actief.",
        selected: "PV-route gekozen door gebruiker",
        declined: "PicoT kiest de route automatisch.",
        released: "PicoT heeft de regie terug; de route wordt opnieuw beoordeeld.",
        rejected: "Je keuze kon niet worden toegepast. Het huidige plan blijft actief.",
        expired: "Deze keuze is verlopen. Het huidige plan blijft actief.",
        completed: "Deze laadopdracht is afgerond; je voorkeur is vervallen.",
      };
      const number = (value, digits = 2) => typeof value === "number" && Number.isFinite(value)
        ? value.toLocaleString("nl-NL", {maximumFractionDigits: digits}) : "—";
      for (const choice of choices) {
        const card = document.createElement("div");
        card.className = "strategy-rule";
        const title = document.createElement("strong");
        title.textContent = statuses[choice.status] ?? "Routekeuze wordt bijgewerkt.";
        card.appendChild(title);
        const offer = choice.offer ?? {};
        if (choice.status === "offered" && !offer.alternative) {
          title.textContent = "Automatisch laadplan; geen haalbaar PV-alternatief beschikbaar";
        }
        if (choice.last_notice?.message) {
          const notice = document.createElement("p");
          notice.textContent = choice.last_notice.message;
          card.appendChild(notice);
        }
        const dateText = offer.delivery_date ?? choice.delivery_date;
        if (dateText) {
          const date = document.createElement("p");
          date.textContent = `Laadopdracht ${dateText}`;
          card.appendChild(date);
        }
        if (["offered", "pending", "selected"].includes(choice.status)) {
          for (const [key, fallback] of [["automatic", "Automatische route"],
                                         ["alternative", "PV-alternatief"]]) {
            const route = offer[key];
            if (!route) continue;
            const summary = document.createElement("p");
            summary.textContent = `${route.label || fallback}: ` +
              `netinkoop ${number(route.grid_import_kwh)} kWh · ` +
              `PV-opslag ${number(route.pv_storage_kwh)} kWh · ` +
              `SOC einde ${number(route.terminal_soc, 1)}% · ` +
              `vergelijkingsprijs € ${number(route.acquisition_eur_per_stored_kwh, 3)}` +
              "/kWh opgeslagen";
            card.appendChild(summary);
          }
          const note = document.createElement("p");
          note.className = "muted";
          note.textContent = "Verwachtingen bij het voorstel. De vergelijkingsprijs is geen " +
            "totale besparing. Je voorkeur geldt alleen voor deze laadopdracht; " +
            "noodzakelijk herstel blijft mogelijk.";
          card.appendChild(note);
        }
        const obsolete = choice.status === "offered" && (
          (choice.current_plan_id != null && choice.plan_id !== choice.current_plan_id) ||
          (choice.current_revision != null && choice.revision !== choice.current_revision));
        if (["offered", "pending", "selected"].includes(choice.status)) {
          const comparison = document.createElement("section");
          comparison.className = "route-comparison";
          appendPlanComparison(comparison, offer.automatic, offer.alternative,
            offer.alternative ? ["Automatisch plan bij voorstel", "PV-alternatief bij voorstel"]
              : ["Automatisch plan bij voorstel"]);
          card.appendChild(comparison);
          if (obsolete) {
            title.textContent = "Voorstel verouderd: het actieve plan is gewijzigd";
            const warning = document.createElement("p");
            warning.textContent = "Dit voorstel hoort bij een ouder plan. " +
              "Het actieve plan is inmiddels " +
              "gewijzigd; wacht op een nieuw voorstel. Deze keuze kan niet meer worden toegepast.";
            card.appendChild(warning);
          }
        }
        const action = (label, payload) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = label;
          button.disabled = routeChoiceRequestPending;
          button.addEventListener("click", () => submitRouteChoice(payload));
          card.appendChild(button);
        };
        const expires = Date.parse(choice.expires_at);
        if (choice.status === "offered" && !obsolete &&
            Number.isFinite(expires) && expires > Date.now()) {
          if (offer.alternative) {
            action("Kies PV-route", {token: choice.token, action: "pv"});
          } else {
            const unavailable = document.createElement("p");
            unavailable.textContent =
              "Er is op dit moment geen haalbaar PV-alternatief beschikbaar.";
            card.appendChild(unavailable);
          }
          action("Behoud automatisch plan", {token: choice.token, action: "automatic"});
        } else if (choice.status === "selected") {
          action("Laat PicoT weer kiezen",
            {assignment_id: choice.assignment_id, action: "release"});
        }
        container.appendChild(card);
      }
    }

    async function submitRouteChoice(payload) {
      if (routeChoiceRequestPending) return;
      routeChoiceRequestPending = true;
      const feedback = element("route-choice-feedback");
      feedback.textContent = "Keuze verzenden. Het huidige plan blijft actief tot bevestiging.";
      element("route-choices").querySelectorAll("button").forEach(button => button.disabled = true);
      try {
        const response = await fetch("api/route-choice", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({...payload, request_id: storageModeResetId()}),
        });
        if (!response.ok) throw new Error("Keuze niet beschikbaar of niet opgeslagen");
        const result = await response.json();
        if (result.route_choices) renderRouteChoices(result.route_choices);
        feedback.textContent = "Verzoek ontvangen. De actuele status verschijnt zodra PicoT " +
          "de keuze heeft verwerkt.";
      } catch (_) {
        feedback.textContent = "De keuze is niet bevestigd. Controleer de actuele status en " +
          "probeer opnieuw als de optie nog beschikbaar is.";
      } finally {
        routeChoiceRequestPending = false;
        element("route-choices").querySelectorAll("button")
          .forEach(button => button.disabled = false);
      }
    }

    function renderUserRules(rules) {
      const form = element("user-rules-form");
      if (form.dataset.dirty === "true" || form.contains(document.activeElement)) return;
      element("rule-preserve-pv").checked =
        rules.preserve_pv_during_grid_charge !== false;
      element("rule-trading-soc").value = Number.isFinite(
        Number(rules.maximum_trading_soc_percent)
      ) ? Number(rules.maximum_trading_soc_percent) : 25;
      element("rule-saldering-tax").checked =
        rules.saldering_energy_tax_credit_enabled !== false;
      element("rule-market-spread").value = rules.market_minimum_spread_eur_per_kwh ?? "";
      element("rule-market-recovery").checked = rules.market_recovery_required === true;
      element("rule-market-margin").value = rules.market_minimum_net_margin_eur_per_kwh ?? 0.05;
      element("user-rules-status").textContent = rules.revision
        ? `Actieve revisie ${rules.revision}`
        : "Wachten op de actieve gebruikersregels…";
    }

    async function saveUserRules(event) {
      event.preventDefault();
      const status = element("user-rules-status");
      const button = element("save-user-rules");
      if (button.disabled) return;
      const form = element("user-rules-form");
      const submittedRevision = form.dataset.editRevision ?? "0";
      const maximumTradingSoc = Number(element("rule-trading-soc").value);
      if (!Number.isFinite(maximumTradingSoc) || maximumTradingSoc < 0 || maximumTradingSoc > 100) {
        status.textContent = "Kies een waarde tussen 0 en 100%.";
        return;
      }
      button.disabled = true;
      status.textContent = "Regels opslaan en planning opnieuw beoordelen…";
      try {
        const response = await fetch("api/user-rules", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            preserve_pv_during_grid_charge: element("rule-preserve-pv").checked,
            maximum_trading_soc_percent: maximumTradingSoc,
            market_minimum_spread_eur_per_kwh: element("rule-market-spread").value === ""
              ? null : Number(element("rule-market-spread").value),
            market_recovery_required: element("rule-market-recovery").checked,
            market_minimum_net_margin_eur_per_kwh: Number(element("rule-market-margin").value),
            saldering_energy_tax_credit_enabled:
              element("rule-saldering-tax").checked,
          }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        if ((form.dataset.editRevision ?? "0") === submittedRevision) {
          form.dataset.dirty = "false";
          renderUserRules(result.user_rules ?? {});
          status.textContent = "Regels opgeslagen; lopende opdrachten blijven behouden.";
        } else {
          status.textContent = "Verstuurde regels opgeslagen. Je nieuwe wijzigingen zijn " +
            "nog niet opgeslagen.";
        }
      } catch (error) {
        status.textContent = `Opslaan mislukt: ${error.message}`;
      } finally {
        button.disabled = false;
      }
    }

    function renderEnergyDevices(catalog, placementView) {
      const status = element("energy-device-catalog-status");
      const cards = Array.isArray(catalog?.cards) ? catalog.cards : [];
      status.dataset.state = catalog?.status === "available" ? "ready" : "waiting";
      status.textContent = catalog?.status === "available"
        ? `${cards.length} kaart(en) beschikbaar · uitsluitend na jouw selectie`
        : "Apparaatcatalogus niet beschikbaar; nieuwe kaarten kunnen niet worden opgehaald.";

      const cardContainer = element("energy-device-cards");
      const select = element("energy-device-card-select");
      const selectedCardId = select.value;
      cardContainer.replaceChildren();
      select.replaceChildren();
      for (const card of cards) {
        const article = document.createElement("article");
        article.className = "energy-device-card";
        article.dataset.selected = String(card.card_id === selectedCardId);
        const heading = document.createElement("h3");
        heading.textContent = card.name;
        const state = document.createElement("p");
        state.className = "muted";
        state.textContent = card.profile_status === "ready"
          ? `${card.completed_session_count} sessies · confidence ` +
            formatConfidence(card.confidence)
          : "Profiel wordt nog geleerd";
        const energy = document.createElement("p");
        energy.textContent = [
          formatMeasurement(card.expected_power_w, "W"),
          formatMeasurement(card.expected_energy_wh, "Wh"),
          Number.isFinite(Number(card.expected_duration_seconds))
            ? `${Math.round(Number(card.expected_duration_seconds) / 60)} minuten`
            : "duur nog onbekend",
        ].join(" · ");
        article.append(heading, state, energy);
        cardContainer.append(article);

        const option = document.createElement("option");
        option.value = card.card_id;
        option.textContent = card.name;
        option.dataset.durationSeconds = card.expected_duration_seconds ?? "";
        select.append(option);
      }
      if (selectedCardId && cards.some((card) => card.card_id === selectedCardId)) {
        select.value = selectedCardId;
      }
      if (!cards.length) {
        cardContainer.textContent =
          "Nog geen kaarten gevonden. Voeg eerst een meetpunt toe in " +
          "PicoT Energy Devices.";
        const option = document.createElement("option");
        option.textContent = "Geen kaarten beschikbaar";
        option.value = "";
        select.append(option);
      }

      const placements = Array.isArray(placementView?.placements)
        ? placementView.placements : [];
      const placementContainer = element("energy-device-placements");
      placementContainer.replaceChildren();
      for (const placement of placements) {
        const row = document.createElement("div");
        row.className = "strategy-rule strategy-rule-line";
        const label = document.createElement("span");
        label.textContent = `${placement.name}: ` +
          `${formatTimestamp(placement.starts_at)} – ` +
          formatTimestamp(placement.ends_at);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Verwijderen";
        remove.addEventListener("click", () => updateEnergyDevicePlacement({
          action: "remove", placement_id: placement.placement_id,
        }));
        row.append(label, remove);
        placementContainer.append(row);
      }
      if (!placements.length) {
        placementContainer.textContent = "Nog geen apparaatkaarten op de tijdlijn geplaatst.";
      }
    }

    async function updateEnergyDevicePlacement(payload) {
      const status = element("energy-device-placement-status");
      try {
        const response = await fetch("api/energy-device-placements", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        status.textContent = "Tijdlijn bijgewerkt; het actieve MEP-plan is ongewijzigd.";
        renderEnergyDevices(
          result.energy_device_catalog ?? {},
          result.energy_device_placements ?? {},
        );
      } catch (error) {
        status.textContent = `Tijdlijn wijzigen mislukt: ${error.message}`;
      }
    }

    function addEnergyDevicePlacement(event) {
      event.preventDefault();
      const cardId = element("energy-device-card-select").value;
      const startsAt = new Date(element("energy-device-start").value);
      const durationMinutes = Number(element("energy-device-duration").value);
      if (
        !cardId || Number.isNaN(startsAt.getTime()) ||
        !Number.isFinite(durationMinutes) || durationMinutes <= 0
      ) {
        element("energy-device-placement-status").textContent =
          "Kies een kaart, starttijd en geldige duur.";
        return;
      }
      updateEnergyDevicePlacement({
        action: "add",
        card_id: cardId,
        starts_at: startsAt.toISOString(),
        ends_at: new Date(startsAt.getTime() + durationMinutes * 60000).toISOString(),
      });
    }

    function renderDashboardStatus(status) {
      const notice = element("dashboard-status");
      notice.hidden = status?.status !== "details_limited";
      notice.textContent = status?.message_nl ?? "";
    }

    function renderPlanNarrative(narrative, paragraph, now = new Date()) {
      if (!narrative) return;
      const finite = value => typeof value === "number" && Number.isFinite(value);
      const dayKey = date => new Intl.DateTimeFormat("sv-SE", {
        timeZone: "Europe/Amsterdam", year: "numeric", month: "2-digit", day: "2-digit",
      }).format(date);
      const today = dayKey(now);
      const tomorrow = dayKey(new Date(Date.parse(today + "T12:00:00Z") + 86400000));
      const stamp = value => new Intl.DateTimeFormat("nl-NL", {
        timeZone: "Europe/Amsterdam", day: "numeric", month: "long",
        hour: "2-digit", minute: "2-digit",
      }).format(new Date(value));
      const energy = value => `${formatDutchNumber(value)} kWh`;
      const days = (narrative.days ?? []).filter(day => day.date >= today);
      const windows = (narrative.windows ?? []).filter(w => Date.parse(w.ends_at) > now.getTime());
      if (!days.length && !windows.length) return;
      paragraph("Wat het actieve plan gaat doen", "h2");
      const cost = narrative.cost_projection;
      if (cost && Date.parse(cost.ends_at) > now.getTime() &&
          [cost.total_cost_eur, cost.import_cost_eur, cost.export_revenue_eur].every(finite)) {
        const money = value => new Intl.NumberFormat("nl-NL", {
          style: "currency", currency: "EUR", minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }).format(value);
        paragraph(`Verwachte totale stroomkosten: ${money(cost.total_cost_eur)}. ` +
          `Netinkoop ${money(cost.import_cost_eur)} min terugleveropbrengst ` +
          `${money(cost.export_revenue_eur)}.`);
        paragraph(`Kostenprognose van ${stamp(cost.starts_at)} tot ${stamp(cost.ends_at)} uur, ` +
          "inclusief het verwachte huisverbruik, de verwerkte autolaadsessie en de batterij. " +
          "Exclusief vaste kosten; dit is een prognose, geen gemeten dagtotaal.");
      } else {
        paragraph("Voor dit actieve plan is nog geen volledige kostenprognose beschikbaar.");
      }
      for (const day of days) {
        const date = new Intl.DateTimeFormat("nl-NL", {
          timeZone: "Europe/Amsterdam", day: "numeric", month: "long",
        }).format(new Date(day.date + "T12:00:00Z"));
        const label = day.date === today ? `Vandaag (${date})` :
          day.date === tomorrow ? `Morgen (${date})` : `Op ${date}`;
        if (day.starts_at && day.ends_at) {
          paragraph(`Prognoseperiode: ${stamp(day.starts_at)} tot ${stamp(day.ends_at)} uur.`);
        }
        if (finite(day.pv_charge_kwh) && finite(day.pv_other_kwh)) {
          paragraph(`${label} wordt de batterij volgens het plan met ` +
            `${energy(day.pv_charge_kwh)} zonne-energie geladen (vóór laadverliezen). ` +
            `${energy(day.pv_other_kwh)} zonne-energie is beschikbaar voor ` +
            "direct huisverbruik of teruglevering.");
        }
        if (finite(day.grid_charge_kwh)) {
          paragraph(`${label} gaat naar verwachting ${energy(day.grid_charge_kwh)} ` +
            "vanuit het net naar de batterij (vóór laadverliezen).");
        }
        if (day.full_at && Date.parse(day.full_at) > now.getTime()) {
          paragraph(`De batterij bereikt naar verwachting op ${stamp(day.full_at)} uur 100%.`);
        }
      }
      for (const window of windows) {
        const period = `Van ${stamp(window.starts_at)} tot ${stamp(window.ends_at)} uur`;
        if (window.kind === "grid_charge") {
          paragraph(`${period} is aanvullend laden via het net gepland.`);
        } else if (window.kind === "standby") {
          paragraph(`${period} blijft de batterij in stand-by. ` +
            "De batterij ondersteunt het huis dan niet; zon en net voorzien in het huisverbruik.");
        }
      }
      if (!narrative.energy_available) {
        paragraph("De laadhoeveelheden zijn voor dit actieve plan nog niet vastgelegd. " +
          "De beschikbare geplande tijden staan hierboven.");
      } else {
        paragraph("Verwachting volgens de planberekening van " +
          `${stamp(narrative.projected_at)} uur. ` +
          "Hoeveelheden gelden voor de vastgelegde prognoseperiode; het zijn geen metingen.");
      }
      if (!days.some(day => day.full_at && Date.parse(day.full_at) > now.getTime())) {
        paragraph("Er is geen toekomstig moment waarop 100% wordt bereikt vastgelegd " +
          "in deze planprognose.");
      }
    }

    function renderPlanDecision(decision) {
      const target = element("plan-decision");
      target.replaceChildren();
      const paragraph = (text, tag = "p") => {
        const node = document.createElement(tag);
        node.textContent = text;
        target.append(node);
      };
      renderPlanNarrative(decision?.narrative, paragraph);
      const labels = {retained: "Bestaand plan behouden", replaced: "Plan aangepast",
        selected: "Plan gekozen", publication_failed: "Bestaand plan blijft actief",
        failed: "Bestaand plan blijft actief", fallback: "Veilige terugval actief"};
      paragraph(labels[decision?.status] ?? "Waarom dit plan?", "h2");
      paragraph(decision?.reason || "Nog geen onderbouwde planuitleg beschikbaar.");
      if (!decision) return;
      if (decision.assessed_at) {
        paragraph(`Laatste beoordeling: ${formatTimestamp(decision.assessed_at)}.` +
          (decision.evidence_retained
            ? " Laatste vergelijking voor dit plan; niet opnieuw berekend." : ""));
      }
      const finite = value => typeof value === "number" && Number.isFinite(value);
      const money = value => new Intl.NumberFormat("nl-NL", {
        style: "currency", currency: "EUR", minimumFractionDigits: 3, maximumFractionDigits: 3,
      }).format(value);
      const comparable = decision.horizon_start && decision.horizon_end &&
        [decision.incumbent_cost_eur, decision.alternative_cost_eur, decision.improvement_eur]
          .every(finite);
      const standby = decision.standby_comparison;
      if (comparable && standby && finite(standby.benefit_eur) && standby.benefit_eur > 0) {
        paragraph(`Stand-by van ${formatTimestamp(standby.starts_at)} tot ` +
          `${formatTimestamp(standby.ends_at)} is volgens deze volledige routevergelijking ` +
          `${money(standby.benefit_eur)} voordeliger dan batterijondersteuning. ` +
          "Dit is het verschil over de hele vergelijkingsperiode, inclusief laadverliezen.");
      } else if (decision.narrative?.windows?.some(w => w.kind === "standby")) {
        paragraph("Voor stand-by tegenover batterijondersteuning is geen afzonderlijk, " +
          "vergelijkbaar financieel voordeel vastgelegd.");
      }
      if (comparable) {
        paragraph(`Vergelijking: ${formatTimestamp(decision.horizon_start)} tot ` +
          `${formatTimestamp(decision.horizon_end)}. Vergelijkbare verwachte nettokosten.`);
        paragraph(`Bestaande route: ${money(decision.incumbent_cost_eur)}. ` +
          `Alternatief: ${money(decision.alternative_cost_eur)}. ` +
          `Voordeel alternatief: ${money(decision.improvement_eur)}.`);
        if (finite(decision.minimum_improvement_eur)) {
          paragraph(`Minimaal voordeel voor een optionele wijziging: ` +
            `${money(decision.minimum_improvement_eur)}.`);
        }
      } else {
        paragraph("Geen vergelijkbare totale kosten vastgelegd.");
      }
      const assumptions = [];
      if (finite(decision.initial_soc) && decision.initial_soc >= 0 && decision.initial_soc <= 1) {
        assumptions.push("Acculading bij beoordeling: " +
          `${formatDutchNumber(decision.initial_soc * 100)}%`);
      }
      if (decision.solcast_basis) assumptions.push(`Zonneprognose: ${decision.solcast_basis}`);
      if (decision.household_assumption) assumptions.push(decision.household_assumption);
      if (decision.ev_assumption) assumptions.push(decision.ev_assumption);
      if (assumptions.length) paragraph(`Uitgangspunten: ` +
        `${assumptions.map(value => value.replace(/[.]+$/, "")).join(". ")}.`);
    }

    function renderTodaySummary(view) {
      view = {...view, zendure_now: currentStorageStatus(view.zendure_now)};
      const target = element("today-summary");
      target.replaceChildren();
      const actual = view.grid_charge_review?.actual_soc ?? {};
      const last = (actual.points ?? []).filter(p => Date.parse(p.at) <= Date.now()).at(-1);
      const fresh = actual.ends_at && Date.now() - Date.parse(actual.ends_at) <= 900000 &&
        Date.parse(actual.ends_at) <= Date.now() && actual.status !== "unavailable";
      const rawSoc = last?.soc_percent;
      const soc = fresh && typeof rawSoc === "number" && Number.isFinite(rawSoc) &&
        rawSoc >= 0 && rawSoc <= 100 ? rawSoc : null;
      const price = (view.price_timeline?.points ?? []).find(p =>
        Date.parse(p.starts_at) <= Date.now() && Date.parse(p.ends_at) > Date.now());
      for (const [label, value, note] of [
        ["Zendure", soc == null ? "—" : `${formatDutchNumber(soc)}%`,
          soc == null ? "Geen actuele SOC-meting" : "Gemeten batterijvulling"],
        ["Actieve modus", view.zendure_now?.active_mode ?? "—",
          modeFreshness(view.zendure_now).label],
        ["Stroomprijs nu", price?.value_eur_per_kwh == null ? "—" :
          formatPrice(price.value_eur_per_kwh), "Actuele inkoopprijs"]
      ]) {
        const card = document.createElement("div"); card.className = "metric";
        const title = document.createElement("span"); title.textContent = label;
        const amount = document.createElement("strong"); amount.textContent = value;
        const caption = document.createElement("small"); caption.textContent = note;
        card.append(title, amount, caption); target.append(card);
      }
    }

    function renderView(view) {
      const dashboardState = captureDashboardState();
      renderTodaySummary(view);
      renderPlanDecision(view.planning_status?.plan_decision);
      renderDashboardFaults(view);
      renderDashboardStatus(view.dashboard_status);
      renderPlanningRecalculation(view.planning_recalculation);
      element("version").textContent = displayValue(view.picot_version);
      element("run-id").textContent = displayValue(view.run_id);
      element("captured-at").textContent = displayValue(view.captured_at);
      const pipeline = Array.isArray(view.pipeline) ? view.pipeline : [];
      const planningInput = pipeline.find((item) => item.stage === 1);
      const primitiveBoundary = pipeline.find((item) => item.stage === 7);
      const reserveStatus = element("soc-reserve-status");
      reserveStatus.hidden = primitiveBoundary?.attributes?.execution_reason
        !== "execution_soc_minimum_reached";
      reserveStatus.textContent = reserveStatus.hidden ? "" :
        "SOC-ondergrens bereikt: standby gevraagd om verder ontladen te voorkomen. " +
        "Het geplande laadvenster blijft ongewijzigd.";
      const evWarning = element("ev-storage-warning");
      evWarning.hidden = primitiveBoundary?.attributes?.execution_reason
        !== "ev_storage_support_prohibited";
      evWarning.textContent = evWarning.hidden ? "" :
        "EV-beveiliging actief: de batterij wordt naar standby gestuurd omdat EV-verbruik " +
        "is gemeten en de P1-correctie niet bevestigd beschikbaar is. Dit wijkt af van " +
        "het getoonde plan. Controleer P1-correctie in Energy Devices.";
      const execution = pipeline.find((item) => item.stage === 6);
      const observerOnly = execution?.attributes?.observer_only !== false;
      document.body.dataset.observerOnly = String(observerOnly);
      element("execution-mode").textContent = observerOnly
        ? "Alleen meekijken"
        : "Live uitvoering";

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
      renderFinancialResults(view.financial_results ?? {});

      renderUserRules(view.user_rules ?? {});
      renderRouteChoices(view.route_choices ?? {});
      renderEnergyDevices(
        view.energy_device_catalog ?? {},
        view.energy_device_placements ?? {},
      );
      loadPlanningIncidentHistory();
      loadPlanHistory();
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
        view.captured_at,
        selectedExecutionPlanWindows(view),
        view.planning_status?.soc_display_timeline ?? view.planning_status?.soc_timeline ?? [],
        view.grid_charge_review?.actual_soc ?? {},
        view.original_price_plan ?? {}
      );





      renderStorageModeOverride(primitiveBoundary);
      restoreDashboardState(dashboardState);
    }

    // Startup progress reflects backend phases, not an artificial countdown.
    let firstViewRendered = false;
    let startupFailed = false;
    function renderStartup(progress) {
      if (firstViewRendered) return;
      startupFailed = progress.state === "failed";
      const bar = element("execution-mode");
      const percent = Math.min(99, Math.max(0, Number(progress.percent) || 0));
      const elapsed = Math.max(0, Math.floor(Number(progress.elapsed_seconds) || 0));
      const elapsedText = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;
      const label = progress.state === "ready" ? "Dashboardgegevens weergeven" : progress.label;
      bar.style.background = `linear-gradient(to right, #b8e2c5 ${percent}%, #edf1f5 ${percent}%)`;
      bar.style.color = "#173d26";
      bar.setAttribute("role", "progressbar");
      bar.setAttribute("aria-valuemin", "0");
      bar.setAttribute("aria-valuemax", "100");
      bar.setAttribute("aria-valuenow", String(percent));
      bar.setAttribute("aria-valuetext", `${label || "Opstarten"}; ${elapsedText} verstreken`);
      bar.textContent = `${label || "Opstarten"} · ${elapsedText} verstreken`;
      if (progress.state === "failed") {
        element("central-health").hidden = false;
        element("central-health").dataset.health = "fault";
        element("central-health").textContent = `PicoT opstarten mislukt: ${progress.label}`;
        element("status").dataset.state = "error";
        element("status").textContent = `Opstarten mislukt: ${progress.label}`;
      }
    }
    function finishStartup() {
      firstViewRendered = true;
      const bar = element("execution-mode");
      bar.style.removeProperty("background");
      bar.style.removeProperty("color");
      for (const name of [
        "role", "aria-valuemin", "aria-valuemax", "aria-valuenow", "aria-valuetext",
      ]) {
        bar.removeAttribute(name);
      }
    }
    async function pollStartup() {
      while (!firstViewRendered && !updateWatcherStopped) {
        try {
          const response = await fetch("api/startup", { cache: "no-store" });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          renderStartup(await response.json());
        } catch (error) {
          // View requests own connection errors; progress must not hide them.
        }
        if (!firstViewRendered && !updateWatcherStopped) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }
    }
    async function isWaitingForFirstRun(response) {
      if (response.status !== 503) return false;
      const body = await response.json();
      if (body.status !== "waiting_for_first_run") return false;
      if (!firstViewRendered && !startupFailed) {
        element("central-health").hidden = false;
        element("central-health").dataset.health = "waiting";
        element("central-health").textContent = "PicoT · bezig met opstarten";
        element("status").dataset.state = "waiting";
        element("status").textContent = "Verbonden · wachten op de eerste berekening.";
      }
      return true;
    }

    function applyView(view) {
      const status = element("status");
      refreshLiveStatus(view);
      renderDashboardFaults(view);
      renderStorageModeOverride(view.pipeline?.find(item => item.stage === 7));
      if (shouldDeferRenderForSelection()) {
        pendingView = view;
        status.dataset.state = "ready";
        status.textContent =
          "Verbonden · status bijgewerkt; overige data wacht op einde invoer of selectie";
        return;
      }
      pendingView = null;
      renderView(view);
      finishStartup();
      status.dataset.state = "ready";
      status.textContent = "Verbonden · meetouderdom staat bij de actieve modus";
    }

    async function loadView() {
      const status = element("status");
      try {
        const response = await fetch("api/view", { cache: "no-store" });
        if (await isWaitingForFirstRun(response)) return false;
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        applyView(await response.json());
        return true;
      } catch (error) {
        status.dataset.state = "error";
        status.textContent = `Dashboarddata niet beschikbaar: ${error.message}`;
        element("central-health").hidden = false;
        element("central-health").dataset.health = "fault";
        element("central-health").textContent =
          `Dashboardverbinding niet beschikbaar: ${error.message}. ` +
          "De getoonde gegevens kunnen verouderd zijn; PicoT probeert opnieuw verbinding te maken.";
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
          if (await isWaitingForFirstRun(response)) {
            await new Promise((resolve) => setTimeout(resolve, 2000));
            continue;
          }
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
          element("central-health").hidden = false;
          element("central-health").dataset.health = "fault";
          element("central-health").textContent =
            `Realtime verbinding onderbroken: ${error.message}. ` +
            "De getoonde gegevens kunnen verouderd zijn; opnieuw verbinden wordt geprobeerd.";
          await new Promise((resolve) => setTimeout(resolve, 5000));
        }
      }
    }

    function flushPendingView() {
      if (!shouldDeferRenderForSelection() && pendingView !== null) {
        const newestView = pendingView;
        pendingView = null;
        applyView(newestView);
      }
    }
    document.addEventListener("selectionchange", flushPendingView);
    document.addEventListener("focusout", () => setTimeout(flushPendingView, 0));
    function markUserRulesEdited() {
      const form = element("user-rules-form");
      form.dataset.dirty = "true";
      form.dataset.editRevision = String(Number(form.dataset.editRevision ?? 0) + 1);
    }
    element("user-rules-form").addEventListener("input", markUserRulesEdited);
    element("user-rules-form").addEventListener("change", markUserRulesEdited);

    element("reset-storage-mode-override").addEventListener(
      "click",
      resetStorageModeOverride
    );
    element("reset-planning").addEventListener("click", resetPlanning);
    element("user-rules-form").addEventListener("submit", saveUserRules);
    element("energy-device-placement-form").addEventListener(
      "submit", addEnergyDevicePlacement
    );
    element("energy-device-card-select").addEventListener("change", (event) => {
      const seconds = Number(event.target.selectedOptions[0]?.dataset.durationSeconds);
      if (Number.isFinite(seconds) && seconds > 0) {
        element("energy-device-duration").value = String(Math.max(1, Math.round(seconds / 60)));
      }
    });
    element("plan-history-select").addEventListener("change", (event) => {
      planHistorySelectionId = event.target.value;
      renderPlanHistory();
      loadPlanHistory();
    });
    initializeTabs();
    pollStartup();
    loadView().finally(watchViewUpdates);
    loadStorageStatus();
    setInterval(loadStorageStatus, 10000);
    setInterval(loadView, 60000);
    setInterval(loadHouseholdCalendar, 60000);
  
    (() => {
      const button = document.getElementById("diagnostic-export");
      const status = document.getElementById("diagnostic-export-status");
      const progress = document.getElementById("diagnostic-export-progress");
      async function request(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 30000);
        try {
          const response = await fetch(url, {
            ...options, cache: "no-store", signal: controller.signal,
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return await response.json();
        } finally { clearTimeout(timer); }
      }
      button.addEventListener("click", async () => {
        button.disabled = true;
        progress.hidden = false;
        progress.removeAttribute("value");
        status.textContent = "Verzoek versturen — nog geen ontvangstbevestiging.";
        let downloadController;
        let downloadTimer;
        try {
          let job = await request("api/diagnostics/export", {method: "POST"});
          const jobId = job.job_id;
          while (job.status === "building") {
            status.textContent = `Opdracht ontvangen door PicoT. ${job.message}`;
            if (job.total > 0) {
              progress.max = job.total; progress.value = job.completed;
              status.textContent += ` — ${Math.round(100 * job.completed / job.total)}%`;
            } else { progress.removeAttribute("value"); }
            await new Promise(resolve => setTimeout(resolve, 1000));
            job = await request("api/diagnostics/export");
            if (job.job_id !== jobId) throw new Error("Deze export is vervangen. Probeer opnieuw.");
          }
          if (job.status !== "ready") throw new Error(job.error || "Diagnose maken mislukt.");
          status.textContent = "Diagnose gereed. Download starten…";
          progress.removeAttribute("value");
          downloadController = new AbortController();
          const armTimeout = () => {
            clearTimeout(downloadTimer);
            downloadTimer = setTimeout(() => downloadController.abort(), 30000);
          };
          armTimeout();
          const downloadUrl = `api/diagnostics/export/download?job_id=${encodeURIComponent(jobId)}`;
          const response = await fetch(downloadUrl, {
            cache: "no-store", signal: downloadController.signal,
          });
          if (!response.ok) throw new Error(`Download mislukt: HTTP ${response.status}`);
          const total = Number(response.headers.get("Content-Length")) || job.size_bytes;
          const chunks = [];
          let received = 0;
          if (response.body) {
            const reader = response.body.getReader();
            while (true) {
              const {done, value} = await reader.read();
              if (done) break;
              armTimeout();
              chunks.push(value);
              received += value.length;
              if (total > 0) { progress.max = total; progress.value = received; }
              status.textContent = `Downloaden: ${(received / 1048576).toFixed(1)} `
                + `van ${(total / 1048576).toFixed(1)} MB`;
            }
            if (total > 0 && received !== total) {
              throw new Error("Download onvolledig ontvangen.");
            }
          } else { chunks.push(await response.blob()); }
          const url = URL.createObjectURL(new Blob(chunks, {type: "application/zip"}));
          const link = document.createElement("a");
          link.href = url;
          link.download = job.filename;
          document.body.appendChild(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(url), 60000);
          progress.max = 1; progress.value = 1;
          status.textContent = "Bestand ontvangen en aan de browser aangeboden. "
            + "Controleer je downloads.";
        } catch (error) {
          status.textContent = error.name === "AbortError"
            ? "Geen antwoord of downloadgegevens ontvangen binnen 30 seconden. Probeer opnieuw."
            : `Diagnose mislukt: ${error.message} Probeer opnieuw.`;
          progress.hidden = true;
        } finally {
          clearTimeout(downloadTimer);
          if (downloadController) downloadController.abort();
          button.disabled = false;
        }
      });
    })();
</script>
</body>
</html>
"""


def _bounded_dashboard_view(view: dict[str, object]) -> dict[str, object]:
    """Reserve room for the current plan before optional observer detail (ADR-028)."""
    essential = {
        "schema_version", "observer_only", "picot_version", "run_id", "snapshot_id",
        "captured_at", "pipeline_health", "zendure_now",
    }
    bounded = {key: value for key, value in view.items() if key in essential}
    optional = {key: value for key, value in view.items()
                if key not in essential | {"planning_status", "pipeline", "dashboard_status"}}
    planning = view.get("planning_status")
    if isinstance(planning, dict):
        detail_keys = {"alternatives", "market_revision_comparison", "soc_timeline",
                       "soc_expectation"}
        bounded["planning_status"] = {
            key: value for key, value in planning.items() if key not in detail_keys
        }
        optional.update({f"planning_status.{key}": value
                         for key, value in planning.items() if key in detail_keys})
    pipeline = view.get("pipeline")
    if isinstance(pipeline, list):
        bounded["pipeline"] = [
            {**card, "attributes": {
                key: value for key, value in card.get("attributes", {}).items()
                if not isinstance(value, (dict, list, tuple)) or key == "blockers"
            }} for card in pipeline
        ]
        optional["pipeline"] = pipeline
    prior_status = view.get("dashboard_status")
    omitted = set(prior_status.get("omitted_sections", ())
                  if isinstance(prior_status, dict) else ())
    omitted.update(optional)
    notice: dict[str, object] = {
        "status": "details_limited", "reason": "dashboard_payload_limit",
        "message_nl": "Een deel van de extra scherminformatie is te groot en wordt niet getoond. "
                      "De plan- en uitvoeringsstatus blijven zichtbaar. "
                      "Volledige onderbouwing staat in de diagnose.",
        "omitted_sections": sorted(omitted),
    }
    bounded["dashboard_status"] = notice
    # Small sections first prevents one large detail section displacing every other tab.
    for section in sorted(optional, key=lambda key: len(json.dumps(optional[key]))):
        parent, _, key = section.partition(".")
        target = bounded.get(parent) if key else bounded
        assert isinstance(target, dict)
        key = key or parent
        previous = target.get(key)
        existed = key in target
        target[key] = optional[section]
        notice["omitted_sections"] = sorted(omitted - {section})
        if len(json.dumps(bounded, separators=(",", ":"))) <= MAX_WEB_VIEW_CHARACTERS:
            omitted.discard(section)
        elif existed:
            target[key] = previous
        else:
            target.pop(key)
        notice["omitted_sections"] = sorted(omitted)
    return bounded


class WebViewStore:
    """Thread-safe in-memory store for the latest serialized web view."""

    def __init__(
        self, *, soc_cache: SOCProjectionCache | None = None,
        price_reference: PricePlanReference | None = None,
    ) -> None:
        self.startup_progress = StartupProgress()
        self._soc_cache = soc_cache
        self._plan_decision_cache = (
            PlanDecisionCache(soc_cache.path.with_suffix(".plan-decision.json"))
            if soc_cache is not None else None
        )
        self._soc_display = SOCDisplayHistory()
        self._price_reference = price_reference
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._latest_json: str | None = None
        self._fast_grid_power_source: dict[str, object] | None = None
        self._retired_comparison_history: dict[str, object] | None = None
        self._financial_results: dict[str, object] | None = None
        self._grid_charge_review: dict[str, object] | None = None
        self._user_rules: dict[str, object] | None = None
        self._route_choices: dict[str, object] | None = None
        self._update_route_choice: Callable[[dict[str, object]], dict[str, object]] | None = None
        self._planning_recalculation: dict[str, object] | None = None
        self._energy_device_catalog: dict[str, object] | None = None
        self._energy_device_placements: dict[str, object] | None = None
        self._soc_expectation: dict[str, object] | None = None
        self._storage_mode_transitions: list[dict[str, object]] | None = None
        self._storage_status: dict[str, object] | None = None
        self._plan_history_reader: Callable[[], dict[str, object]] | None = None
        self._revision = 0
        self._reset_storage_mode_override: Callable[[str], dict[str, object]] | None = None
        self._reset_planning: Callable[[str], dict[str, object]] | None = None
        self._mark_planner_stress: Callable[[str, str], dict[str, object]] | None = None
        self._update_user_rules: (
            Callable[[dict[str, object]], dict[str, object]] | None
        ) = None
        self._update_energy_device_placements: (
            Callable[[dict[str, object]], dict[str, object]] | None
        ) = None
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
                if isinstance(candidate, dict) and candidate.get("semantic_role") == "grid_power":
                    sources[index] = dict(source)
                    return

    def _replace_latest_locked(
        self,
        view: dict[str, object],
    ) -> None:
        self._overlay_fast_grid_power_source(view)
        if self._storage_status is not None:
            old = view.get("zendure_now")
            previous = old if isinstance(old, dict) else {}
            previous_at = previous.get("observed_at")
            try:
                previous_time = (
                    datetime.fromisoformat(previous_at)
                    if isinstance(previous_at, str) else None
                )
            except ValueError:
                previous_time = None
            status_time = datetime.fromisoformat(str(self._storage_status["observed_at"]))
            if (previous_time is None or previous_time.utcoffset() is None
                    or status_time >= previous_time):
                # An observation is not a planner command or its confirmation.
                view["zendure_now"] = {**previous, **self._storage_status}
        if self._storage_mode_transitions is not None:
            view["storage_mode_transition_history"] = self._storage_mode_transitions
        if self._retired_comparison_history is not None:
            view["retired_comparison_history"] = dict(self._retired_comparison_history)
        if self._financial_results is not None:
            view["financial_results"] = dict(self._financial_results)
        if self._grid_charge_review is not None:
            view["grid_charge_review"] = dict(self._grid_charge_review)
        if self._user_rules is not None:
            view["user_rules"] = dict(self._user_rules)
        if self._route_choices is not None:
            view["route_choices"] = dict(self._route_choices)
        if self._planning_recalculation is not None:
            view["planning_recalculation"] = dict(self._planning_recalculation)
        if self._energy_device_catalog is not None:
            view["energy_device_catalog"] = dict(self._energy_device_catalog)
        if self._energy_device_placements is not None:
            view["energy_device_placements"] = dict(self._energy_device_placements)
        serialized = json.dumps(view, separators=(",", ":"))
        if len(serialized) > MAX_WEB_VIEW_CHARACTERS:
            bounded = _bounded_dashboard_view(view)
            serialized = json.dumps(bounded, separators=(",", ":"))
        if len(serialized) > MAX_WEB_VIEW_CHARACTERS:
            serialized = json.dumps(
                {
                    "status": "view_too_large",
                    "error": "dashboard_payload_limit",
                    "run_id": view.get("run_id"),
                },
                separators=(",", ":"),
            )
        self._latest_json = serialized
        self._revision += 1
        self._condition.notify_all()

    def publish(self, view: dict[str, object]) -> None:
        """Serialize completely before atomically replacing the snapshot."""
        with self._condition:
            previous = json.loads(self._latest_json) if self._latest_json is not None else {}
            incoming_transitions = view.get("storage_mode_transition_history")
            if isinstance(incoming_transitions, list):
                rows = {row["event_id"]: row for row in (self._storage_mode_transitions or [])}
                rows.update({row["event_id"]: row for row in incoming_transitions})
                self._storage_mode_transitions = sorted(
                    rows.values(), key=lambda row: str(row["occurred_at"])
                )[-200:]
            current_status = view.get("planning_status")
            if isinstance(current_status, dict) and self._soc_expectation is not None:
                current_status = self._overlay_soc_expectation(
                    current_status, self._soc_expectation
                )
                view = {**view, "planning_status": current_status}
            previous_status = previous.get("planning_status")
            if isinstance(current_status, dict) and isinstance(previous_status, dict):
                current_plan = current_status.get("chosen_plan") or {}
                previous_plan = previous_status.get("chosen_plan") or {}
                decision = current_status.get("decision") or {}
                if (
                    decision.get("status") == "plan_retained"
                    and current_plan.get("plan_id") is not None
                    and current_plan.get("plan_id") == previous_plan.get("plan_id")
                    and current_plan.get("energy_path_id") == previous_plan.get("energy_path_id")
                    and not current_status.get("soc_timeline")
                    and not current_status.get("soc_expectation")
                    and previous_status.get("soc_timeline")
                ):
                    # Display the original canonical projection, never a new
                    # UI simulation or an observation of actual battery energy.
                    current_status = dict(current_status)
                    current_status["soc_timeline"] = previous_status["soc_timeline"]
                    current_status["soc_projection_captured_at"] = previous_status.get(
                        "soc_projection_captured_at", previous_status.get("captured_at")
                    )
                    current_status["soc_projection_retained"] = True
                    view = {**view, "planning_status": current_status}
                carried = self._retain_market_comparison(current_status, previous_status)
                if carried is not current_status:
                    current_status = carried
                    view = {**view, "planning_status": current_status}
                carried = self._retain_plan_decision(current_status, previous_status)
                if carried is not current_status:
                    current_status = carried
                    view = {**view, "planning_status": current_status}
            status = view.get("planning_status")
            if isinstance(status, dict) and self._plan_decision_cache is not None:
                status = self._plan_decision_cache.apply(status)
                view = {**view, "planning_status": status}
            if self._soc_cache is not None and isinstance(status, dict):
                decision = status.get("decision") or {}
                if (decision.get("status") == "plan_retained" and not status.get("soc_timeline")
                        and not status.get("soc_expectation")):
                    restored = self._soc_cache.restore(status)
                    if restored is not None:
                        status = restored
                elif decision.get("status") == "winner_selected" and status.get("soc_timeline"):
                    self._soc_cache.remember(status)
                view = {**view, "planning_status": {
                    **status, "soc_projection_cache_status": self._soc_cache.status,
                }}
            status = view.get("planning_status")
            if isinstance(status, dict):
                displayed = (self._soc_cache.display(status) if self._soc_cache is not None
                             else self._soc_display.apply(status))
                if self._soc_cache is not None:
                    displayed = {**displayed,
                                 "soc_projection_cache_status": self._soc_cache.status}
                view = {**view, "planning_status": displayed}
            if self._price_reference is not None:
                view = {**view, "original_price_plan": self._price_reference.read()}
            self._replace_latest_locked(view)

    @staticmethod
    def _retain_plan_decision(
        current: dict[str, object], previous: dict[str, object],
    ) -> dict[str, object]:
        """Keep dated comparison evidence only for the same admitted plans."""
        return retain_plan_decision(current, previous)

    @staticmethod
    def _retain_market_comparison(
        current: dict[str, object], previous: dict[str, object],
    ) -> dict[str, object]:
        """Carry original evidence only while its exact execution plans still govern."""
        decision = current.get("decision")
        comparison = previous.get("market_revision_comparison")
        if (current.get("market_revision_comparison") is not None
                or not isinstance(decision, dict)
                or decision.get("status") != "plan_retained"
                or not isinstance(comparison, dict)
                or comparison.get("status") not in {"winner_selected", "plan_retained"}):
            return current

        def identities(value: object) -> set[tuple[str, str]] | None:
            if not isinstance(value, list) or not value:
                return None
            result = set()
            for row in value:
                if not isinstance(row, dict):
                    return None
                plan_id, path_id = row.get("plan_id"), row.get("energy_path_id")
                if not isinstance(plan_id, str) or not isinstance(path_id, str):
                    return None
                if not plan_id or not path_id:
                    return None
                result.add((plan_id, path_id))
            return result if len(result) == len(value) else None

        governed = identities(comparison.get("execution_plans"))
        if governed is None or governed != identities(current.get("execution_plans")):
            return current
        return {**current, "market_revision_comparison": {**comparison, "retained": True}}

    @staticmethod
    def _overlay_soc_expectation(
        status: dict[str, object], patch: dict[str, object],
    ) -> dict[str, object]:
        plan, expected = status.get("chosen_plan"), patch.get("chosen_plan")
        decision = status.get("decision")
        if (not isinstance(plan, dict) or not isinstance(expected, dict)
                or not isinstance(decision, dict)
                or decision.get("status") not in {"winner_selected", "plan_retained"}
                or any(not expected.get(key) or plan.get(key) != expected.get(key)
                       for key in ("plan_id", "energy_path_id"))):
            return status
        try:
            captured = datetime.fromisoformat(str(patch.get("soc_projection_captured_at")))
            previous_raw = status.get("soc_projection_captured_at")
            previous = datetime.fromisoformat(str(previous_raw)) if previous_raw else None
            if captured.utcoffset() is None or (previous is not None and captured < previous):
                return status
        except (ValueError, TypeError):
            return status
        return {**status, **{key: patch[key] for key in (
            "soc_timeline", "soc_projection_captured_at", "soc_projection_retained",
            "soc_expectation", "captured_at",
        ) if key in patch}}

    def publish_soc_expectation(self, status_patch: dict[str, object]) -> None:
        """Render the simulation owner's fresh view of the same committed plan."""
        copied = json.loads(json.dumps(status_patch, allow_nan=False))
        with self._condition:
            if self._latest_json is None:
                return
            latest = json.loads(self._latest_json)
            status = latest.get("planning_status")
            if not isinstance(status, dict):
                return
            updated = self._overlay_soc_expectation(status, copied)
            if updated is status:
                return
            self._soc_expectation = copied
            if self._soc_cache is not None:
                if updated.get("soc_timeline"):
                    self._soc_cache.remember(updated)
                updated = self._soc_cache.display(updated)
            else:
                updated = self._soc_display.apply(updated)
            latest["planning_status"] = updated
            self._replace_latest_locked(latest)

    def publish_soc_expectation_unavailable(self, captured_at: datetime, reason: str) -> None:
        """Expire a future curve when no current committed-route input is available."""
        with self._condition:
            if self._latest_json is None:
                return
            latest = json.loads(self._latest_json)
            status = latest.get("planning_status")
            if not isinstance(status, dict):
                return
            plan = status.get("chosen_plan")
        self.publish_soc_expectation({
            "chosen_plan": plan, "captured_at": captured_at.isoformat(),
            "soc_projection_captured_at": captured_at.isoformat(),
            "soc_projection_retained": False, "soc_timeline": [],
            "soc_expectation": {"status": "unavailable", "reason": reason},
        })

    def publish_storage_mode_transition_history(
        self, events: tuple[StorageModeTransitionEvent, ...],
    ) -> None:
        """Publish persisted clock transitions without requiring a Planner Run."""
        rows = _transition_history_view(events)
        with self._condition:
            self._storage_mode_transitions = rows
            if self._latest_json is not None:
                self._replace_latest_locked(json.loads(self._latest_json))

    def set_plan_history_reader(self, reader: Callable[[], dict[str, object]]) -> None:
        with self._lock:
            self._plan_history_reader = reader

    def plan_history(self) -> dict[str, object]:
        with self._lock:
            reader = self._plan_history_reader
        # File reading must never hold the current-view publication lock.
        if reader is None:
            return {"status": "unavailable", "plans": []}
        try:
            return reader()
        except (OSError, ValueError, TypeError, KeyError):
            return {"status": "unavailable", "plans": []}

    def publish_storage_status(self, status: dict[str, object]) -> None:
        """Keep a small read-only observation; never wake/rebuild the planner view."""
        at = status.get("observed_at")
        if not isinstance(at, str):
            raise ValueError("storage observation requires a timestamp")
        captured = datetime.fromisoformat(at)
        if captured.utcoffset() is None:
            raise ValueError("storage observation must be timezone aware")
        copied = dict(status, origin="unknown", set_at=None)
        with self._condition:
            if self._storage_status is not None:
                prior = self._storage_status.get("observed_at")
                if isinstance(prior, str) and datetime.fromisoformat(prior) > captured:
                    return
            self._storage_status = copied

    def storage_status(self) -> dict[str, object]:
        with self._condition:
            return dict(self._storage_status or {
                "active_mode": None, "observed_at": None, "availability": "unavailable",
                "origin": "unknown", "set_at": None, "error": "waiting_for_observation",
            })

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

    def publish_planning_input_sources(
        self,
        sources: list[dict[str, object]],
    ) -> None:
        """Overlay fresh source evidence without replacing the active plan."""
        copied: object = json.loads(json.dumps(sources))
        if not isinstance(copied, list):
            raise TypeError("planning input sources must serialize to a list")
        with self._condition:
            if self._latest_json is None:
                return
            latest: object = json.loads(self._latest_json)
            if not isinstance(latest, dict):
                raise TypeError("latest web view must be an object")
            pipeline = latest.get("pipeline")
            if not isinstance(pipeline, list):
                return
            for card in pipeline:
                if not isinstance(card, dict) or card.get("stage") != 1:
                    continue
                attributes = card.get("attributes")
                if not isinstance(attributes, dict):
                    return
                attributes["sources"] = copied
                attributes["source_count"] = len(copied)
                attributes["source_available_count"] = sum(
                    isinstance(source, dict) and source.get("availability") == "available"
                    for source in copied
                )
                break
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

    def publish_retired_comparison_history(
        self,
        comparison: dict[str, object],
    ) -> None:
        """Overlay persistent replay evidence without planner authority."""
        copied: object = json.loads(json.dumps(comparison))
        if not isinstance(copied, dict):
            raise TypeError("planner comparison history must be an object")
        if (
            copied.get("observer_only") is not True
            or copied.get("selection_permitted") is not False
            or copied.get("commitment_permitted") is not False
        ):
            raise ValueError("planner comparison history must remain passive")
        with self._condition:
            self._retired_comparison_history = copied
            if self._latest_json is None:
                return
            latest: object = json.loads(self._latest_json)
            if isinstance(latest, dict):
                self._replace_latest_locked(latest)

    def publish_grid_charge_review(self, review: dict[str, object]) -> None:
        """Overlay passive observations without touching canonical projection identities."""
        copied = json.loads(json.dumps(review, allow_nan=False))
        with self._condition:
            self._grid_charge_review = copied
            if self._latest_json is not None:
                latest = json.loads(self._latest_json)
                if isinstance(latest, dict):
                    self._replace_latest_locked(latest)

    def publish_financial_results(
        self,
        financial_results: dict[str, object],
    ) -> None:
        """Overlay measured settlement without granting planner authority."""
        copied: object = json.loads(json.dumps(financial_results))
        if not isinstance(copied, dict):
            raise TypeError("financial results must be an object")
        if (
            copied.get("observer_only") is not True
            or copied.get("selection_permitted") is not False
            or copied.get("commitment_permitted") is not False
        ):
            raise ValueError("financial results must remain passive")
        with self._condition:
            self._financial_results = copied
            if self._latest_json is None:
                return
            latest: object = json.loads(self._latest_json)
            if isinstance(latest, dict):
                self._replace_latest_locked(latest)

    def publish_planning_recalculation(self, status: dict[str, object]) -> None:
        copied = json.loads(json.dumps(status))
        with self._condition:
            if copied == self._planning_recalculation:
                return
            self._planning_recalculation = copied
            if self._latest_json is not None:
                self._replace_latest_locked(json.loads(self._latest_json))

    def publish_route_choices(self, status: dict[str, object]) -> None:
        copied = json.loads(json.dumps(status))
        if not isinstance(copied, dict) or not isinstance(copied.get("choices"), list):
            raise ValueError("route choices require an explicit choices list")
        with self._condition:
            if copied == self._route_choices:
                return
            self._route_choices = copied
            if self._latest_json is not None:
                self._replace_latest_locked(json.loads(self._latest_json))

    def set_route_choice_update(
        self, update: Callable[[dict[str, object]], dict[str, object]],
    ) -> None:
        with self._lock:
            self._update_route_choice = update

    def route_choice_update(self) -> Callable[[dict[str, object]], dict[str, object]] | None:
        with self._lock:
            return self._update_route_choice

    def publish_user_rules(self, user_rules: dict[str, object]) -> None:
        copied = json.loads(json.dumps(user_rules))
        if not isinstance(copied, dict):
            raise TypeError("user rules must serialize to an object")
        with self._condition:
            self._user_rules = copied
            if self._latest_json is None:
                return
            latest = json.loads(self._latest_json)
            if isinstance(latest, dict):
                self._replace_latest_locked(latest)

    def set_user_rule_update(
        self,
        update: Callable[[dict[str, object]], dict[str, object]],
    ) -> None:
        with self._lock:
            self._update_user_rules = update

    def user_rule_update(
        self,
    ) -> Callable[[dict[str, object]], dict[str, object]] | None:
        with self._lock:
            return self._update_user_rules

    def publish_energy_device_catalog(self, catalog: dict[str, object]) -> None:
        """Expose optional cards without touching planning input or a plan."""
        copied = json.loads(json.dumps(catalog))
        if not isinstance(copied, dict):
            raise TypeError("energy-device catalog must serialize to an object")
        if copied.get("observer_only") is not True or copied.get("planning_authority") is not False:
            raise ValueError("energy-device catalog must remain observer-only")
        with self._condition:
            self._energy_device_catalog = copied
            if self._latest_json is not None:
                latest = json.loads(self._latest_json)
                if isinstance(latest, dict):
                    self._replace_latest_locked(latest)

    def energy_device_catalog(self) -> dict[str, object] | None:
        with self._lock:
            return (
                json.loads(json.dumps(self._energy_device_catalog))
                if self._energy_device_catalog is not None
                else None
            )

    def publish_energy_device_placements(self, placements: dict[str, object]) -> None:
        copied = json.loads(json.dumps(placements))
        if not isinstance(copied, dict):
            raise TypeError("energy-device placements must serialize to an object")
        if copied.get("observer_only") is not True or copied.get("planning_authority") is not False:
            raise ValueError("energy-device placements must remain observer-only")
        with self._condition:
            self._energy_device_placements = copied
            if self._latest_json is not None:
                latest = json.loads(self._latest_json)
                if isinstance(latest, dict):
                    self._replace_latest_locked(latest)

    def set_energy_device_placement_update(
        self,
        update: Callable[[dict[str, object]], dict[str, object]],
    ) -> None:
        with self._lock:
            self._update_energy_device_placements = update

    def energy_device_placement_update(
        self,
    ) -> Callable[[dict[str, object]], dict[str, object]] | None:
        with self._lock:
            return self._update_energy_device_placements

    def set_planner_stress_marker(
        self,
        marker: Callable[[str, str], dict[str, object]],
    ) -> None:
        with self._lock:
            self._mark_planner_stress = marker

    def planner_stress_marker(
        self,
    ) -> Callable[[str, str], dict[str, object]] | None:
        with self._lock:
            return self._mark_planner_stress

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
    reset_storage_mode_override: (Callable[[str], dict[str, object]] | None) = None,
    reset_planning: Callable[[str], dict[str, object]] | None = None,
) -> ThreadingHTTPServer:
    """Create, but do not start, the read-only observer HTTP server."""

    export_job = DiagnosticExportJob()

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
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed_url = urlsplit(self.path)
            path = parsed_url.path
            if path == "/api/plan-history":
                self._send_json(HTTPStatus.OK, json.dumps(store.plan_history()))
                return
            if path == "/api/storage-status":
                self._send_json(HTTPStatus.OK, json.dumps(store.storage_status()))
                return
            if path == "/api/startup":
                self._send_json(HTTPStatus.OK, json.dumps(store.startup_progress.snapshot()))
                return
            if path == "/api/diagnostics/export":
                self._send_json(HTTPStatus.OK, json.dumps(export_job.status()))
                return
            if path == "/api/diagnostics/export/download":
                job_id = parse_qs(parsed_url.query).get("job_id", [""])[0]
                result = export_job.download(job_id)
                if result is None:
                    self._send_json(HTTPStatus.NOT_FOUND, '{"error":"Export niet beschikbaar"}')
                else:
                    body, filename = result
                    self._send_download(body, content_type="application/zip", filename=filename)
                return
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
                    ('{"revision":' + str(current_revision) + ',"view":' + latest + "}"),
                )
                return

            if path == "/api/diagnostics/incidents":
                incident_path = store.incident_history_path()
                overview = incident_overview(incident_path) if incident_path is not None else []
                self._send_json(
                    HTTPStatus.OK,
                    json.dumps(overview, separators=(",", ":")),
                )
                return

            if path == "/api/household-calendar":
                report_path = next((p for p in store.diagnostic_paths()
                                    if p.name == CALENDAR_REPORT_PATH.name), None)
                self._send_json(HTTPStatus.OK, json.dumps(
                    calendar_dashboard_view(report_path), separators=(",", ":"),
                ))
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
            if path == "/api/diagnostics/export":
                result = export_job.start(
                    lambda progress: diagnostic_zip(store.diagnostic_paths(), progress=progress),
                    "picot-diagnostics.zip",
                )
                self._send_json(HTTPStatus.ACCEPTED, json.dumps(result))
                return
            if path not in {
                "/api/storage-mode-override/reset",
                "/api/planning/reset",
                "/api/planner-comparison/stress",
                "/api/user-rules",
                "/api/route-choice",
                "/api/energy-device-placements",
            }:
                self._reject_write()
                return
            if path == "/api/route-choice":
                update = store.route_choice_update()
                if update is None:
                    self._send_json(HTTPStatus.CONFLICT, '{"status":"route_choice_unavailable"}')
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 4096:
                        raise ValueError
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError
                    action = payload.get("action")
                    required = (
                        ("assignment_id", "request_id") if action == "release" else ("token",)
                    )
                    if action not in {"pv", "automatic", "release"} or any(
                        not isinstance(payload.get(key), str) or not payload[key].strip()
                        for key in required
                    ):
                        raise ValueError
                    result = update(payload)
                except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                    self._send_json(HTTPStatus.BAD_REQUEST,
                                    '{"status":"route_choice_not_available"}')
                    return
                except OSError:
                    self._send_json(HTTPStatus.SERVICE_UNAVAILABLE,
                                    '{"status":"route_choice_not_saved"}')
                    return
                self._send_json(HTTPStatus.OK, json.dumps(result, separators=(",", ":")))
                return
            if path == "/api/energy-device-placements":
                update = store.energy_device_placement_update()
                if update is None:
                    self._send_json(
                        HTTPStatus.CONFLICT,
                        '{"status":"energy_device_placements_unavailable"}',
                    )
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 8192:
                        raise ValueError
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError
                    result = update(payload)
                except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        '{"status":"invalid_energy_device_placement"}',
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    json.dumps(result, separators=(",", ":")),
                )
                return
            if path == "/api/user-rules":
                update = store.user_rule_update()
                if update is None:
                    self._send_json(
                        HTTPStatus.CONFLICT,
                        '{"status":"user_rules_unavailable"}',
                    )
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 4096:
                        raise ValueError
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError
                    result = update(payload)
                except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        '{"status":"invalid_user_rules"}',
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    json.dumps(result, separators=(",", ":")),
                )
                return
            reset = (
                reset_planning or store.planning_reset()
                if path == "/api/planning/reset"
                else reset_storage_mode_override or store.storage_mode_override_reset()
            )
            stress = (
                store.planner_stress_marker() if path == "/api/planner-comparison/stress" else None
            )
            if stress is not None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length))
                    marker_id = payload.get("marker_id") if isinstance(payload, dict) else None
                    note = payload.get("note", "") if isinstance(payload, dict) else ""
                    if not isinstance(marker_id, str) or not isinstance(note, str):
                        raise ValueError
                    result = stress(marker_id, note)
                except (json.JSONDecodeError, TypeError, ValueError):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        '{"status":"invalid_stress_marker"}',
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    json.dumps(result, separators=(",", ":")),
                )
                return
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
                if not isinstance(reset_id, str) or not reset_id.strip():
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
    recovery = recovery_details(attributes)
    if recovery:
        return recovery
    if state == "mode_feedback_timeout":
        return "De HA-keuzestand bevestigde de aangevraagde modus niet binnen de wachttijd."
    if stage == 1:
        if pipeline_stage_health(stage=stage, state=state, attributes=attributes) == "fault":
            error = attributes.get("error")
            if error:
                return f"Planningsinvoer niet bruikbaar: {error}"
            sources = attributes.get("sources")
            missing = [
                str(source.get("entity_id") or source.get("category") or "onbekende bron")
                for source in sources if isinstance(source, dict)
                and (source.get("availability") == "unavailable" or source.get("error"))
            ] if isinstance(sources, (list, tuple)) else []
            return "Planningsinvoer niet bruikbaar: " + (
                ", ".join(missing) if missing else state.replace("_", " ")
            )
        return "De planningsgegevens zijn compleet en klaar voor beoordeling."
    if stage == 2:
        count = _result_count(attributes, "opportunity_count")
        return f"Er zijn {count} mogelijke energiekansen gevonden."
    if stage == 3:
        count = _result_count(attributes, "candidate_count")
        return f"Er zijn {count} mogelijke plannen opgebouwd."
    if stage == 4:
        if attributes.get("decisive_step") == "tie_break:grid_charge_duration":
            return "Bij gelijke kosten is het haalbare plan met de kortste netlaadduur gekozen."
        if state == "plan_retained":
            if attributes.get("winning_candidate_id"):
                return "Het bestaande plan is na vergelijking behouden."
            return "Het bestaande plan is behouden; er is geen nieuwe winnaar gekozen."
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
        if state == "plan_retained":
            return "Het bestaande uitvoeringsplan is behouden."
        if state == "blocked":
            return "Er is geen uitvoeringsplan beschikbaar; de planopbouw is geblokkeerd."
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
        if isinstance(blockers, (list, tuple)) and "manual_override_active" in blockers:
            return "Uitvoering is geblokkeerd omdat een handmatige instelling actief is."
        normal_result = attributes.get("normal_result")
        if isinstance(normal_result, str) and normal_result.strip():
            return normal_result
        if state == "already_active":
            return "De teruggelezen modus komt al overeen; er is geen nieuwe opdracht nodig."
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
    if stage == 5 and state == "blocked":
        return "fault"
    unhealthy_markers = ("error", "failed", "invalid", "unavailable", "rejected", "timeout")
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
    return f"{start:%d-%m-%Y %H:%M} tot {end:%d-%m-%Y %H:%M}"


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
                    f"{period}: € {price}/kWh, zekerheid {confidence}%. Relevant omdat {reason}."
                ),
            }
        )
    opportunity_groups = [
        {
            "label_nl": label,
            "count": len(items),
            "summary_nl": (f"{len(items)}× {label.lower()}: {group_reasons[label]}."),
            "items": items,
        }
        for label, items in sorted(grouped.items())
    ]

    outcomes_by_candidate = {outcome.candidate_id: outcome for outcome in run.outcomes.outcomes}
    paths_by_id = {path.path_id: path for path in run.candidate_set.energy_paths}
    pv_candidate_count = sum(
        candidate.family == "pv_charge_only" for candidate in run.candidate_set.candidates
    )
    local_capture_date = run.planning_input.captured_at.astimezone(
        ZoneInfo("Europe/Amsterdam")
    ).date()
    plans: list[dict[str, object]] = []
    winning_confidence: float | None = None
    for candidate in run.candidate_set.candidates:
        selected = candidate.candidate_id == run.evaluation.winning_candidate_id
        outcome = outcomes_by_candidate.get(candidate.candidate_id)
        path = paths_by_id[candidate.energy_path_id]
        if candidate.family == "pv_charge_only" and isinstance(
            outcome,
            DelegatedStorageCandidateOutcome,
        ):
            local_timezone = ZoneInfo("Europe/Amsterdam")
            segments_by_date: dict[date, list[PathSegment]] = {}
            for segment in path.segments:
                segment_date = segment.starts_at.astimezone(local_timezone).date()
                segments_by_date.setdefault(segment_date, []).append(segment)
            phase_dates = tuple(segments_by_date)
            phases: list[dict[str, object]] = []
            for phase_index, phase_date in enumerate(phase_dates):
                phase_segments = segments_by_date[phase_date]
                phase_start = min(segment.starts_at for segment in phase_segments)
                phase_end = max(segment.ends_at for segment in phase_segments)
                if phase_date == local_capture_date:
                    phase_label = (
                        "Nu laden met PV"
                        if phase_start <= run.planning_input.captured_at
                        else "Vandaag laden met PV"
                    )
                elif phase_date == local_capture_date + timedelta(days=1):
                    phase_label = (
                        "Morgen aanvullen met PV" if phase_index > 0 else "Morgen laden met PV"
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
            window_date = outcome.charge_window_starts_at.astimezone(local_timezone).date()
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
                label = "Vandaag en morgen laden met verwachte zonne-energie"
            period = _period_nl(
                outcome.charge_window_starts_at,
                outcome.charge_window_ends_at,
            )
            energy = (
                "Verwachte toevoeging aan batterij: "
                f"{_number_nl(outcome.pv_storage_contribution_wh / 1000)} kWh"
            )
            grid_energy = (
                f"Verwacht netladen: {_number_nl(outcome.grid_storage_contribution_wh / 1000)} kWh"
            )
            remaining_to_target_kwh = (
                max(
                    0.0,
                    outcome.required_energy_wh - outcome.storage_energy_at_requirement_wh,
                )
                / 1000
            )
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
            if selected and candidate.family == "reserve_first":
                winning_confidence = min(
                    (state.confidence for state in run.planning_input.current_storage_states),
                    default=None,
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
            if winning_outcome is not None and winning_outcome.requirement_satisfied
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

    if run.evaluation.status == "plan_retained" and run.execution_plan_set.plans:
        decision_summary = "Het bestaande uitvoeringsplan is behouden."
        decision_reason = "De uitvoeringsstatus volgt het bestaande plan."

    # Projection reports execution authority; a missing/rounded score is not a veto.
    boundary = run.primitive_boundary
    vendor = run.vendor_result
    blockers = list(boundary.blockers)
    if vendor.failure_reason:
        blockers.append(vendor.failure_reason)
    blocked = bool(blockers) or boundary.status in {"blocked", "dry_run_blocked"} or (
        vendor.status in {"dispatch_failed", "mode_feedback_timeout", "rejected"}
    )
    readiness_status = "blocked" if blocked else boundary.status
    warning = None
    if blocked:
        reason = "; ".join(dict.fromkeys(blockers)) or (
            boundary.execution_reason or vendor.status
        )
        warning = "; ".join(
            recovery_message(item) or f"Uitvoering geblokkeerd: {item}."
            for item in dict.fromkeys(blockers or [reason])
        )
    confidence_percent = (
        round(winning_confidence * 100) if winning_confidence is not None else None
    )
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
            "status": readiness_status,
            "primitive_status": boundary.status,
            "vendor_status": vendor.status,
            "warning_nl": warning,
            "blockers": list(dict.fromkeys(blockers)),
        },
    }


def _build_planning_status(run: CanonicalPipelineRun) -> dict[str, object]:
    """Expose one pipeline run as facts without deriving new conclusions."""
    plan_decision = build_plan_decision(run)
    plan_decision["narrative"] = build_plan_narrative(run)
    plan_decision["standby_comparison"] = standby_comparison(run, plan_decision)
    candidates_by_id = {
        candidate.candidate_id: candidate for candidate in run.candidate_set.candidates
    }
    outcomes_by_candidate = {outcome.candidate_id: outcome for outcome in run.outcomes.outcomes}
    energy_paths_by_id = {path.path_id: path for path in run.candidate_set.energy_paths}
    winning_candidate_id = run.evaluation.winning_candidate_id
    winning_candidate = (
        candidates_by_id.get(winning_candidate_id) if winning_candidate_id is not None else None
    )
    winning_outcome = (
        outcomes_by_candidate.get(winning_candidate_id)
        if winning_candidate_id is not None
        else None
    )
    winning_energy_path = (
        energy_paths_by_id.get(run.evaluation.winning_energy_path_id)
        if run.evaluation.winning_energy_path_id is not None
        else None
    )
    winning_execution_plans = tuple(
        sorted(
            (
                plan
                for plan in run.execution_plan_set.plans
                if plan.winning_candidate_id == winning_candidate_id
                or run.evaluation.status == "plan_retained"
            ),
            key=lambda plan: (plan.valid_from, plan.valid_until, plan.plan_id),
        )
    )
    winning_execution_plan = (
        winning_execution_plans[0] if len(winning_execution_plans) == 1 else None
    )
    if (run.evaluation.status == "plan_retained" and winning_execution_plan is not None
            and winning_candidate_id != run.evaluation.incumbent_candidate_id
            and winning_candidate_id != winning_execution_plan.winning_candidate_id):
        # Evaluation may have selected a replacement that Builder/Store could
        # not publish. Its comparison remains evidence, not the retained plan's SOC path.
        winning_candidate = None
        winning_outcome = None
        winning_energy_path = None
    winning_commitment = (
        next(
            (
                commitment
                for commitment in run.planning_input.active_plan_commitments
                if commitment.plan_id == winning_execution_plan.plan_id
                and commitment.execution_scope_id == winning_execution_plan.execution_scope_id
            ),
            None,
        )
        if winning_execution_plan is not None
        else None
    )
    charge_segments = tuple(
        segment
        for plan in winning_execution_plans
        for segment in plan.segments
        if segment.primitive.value == "charge_at_power"
        or (
            segment.primitive.value == "balance_bidirectional"
            and segment.main_assignment_id is not None
        )
    )
    requirement = next(
        iter(run.candidate_set.storage_requirements),
        None,
    )
    storage_states_by_id = {
        state.storage_state_id: state for state in run.planning_input.current_storage_states
    }
    initial_storage_state = (
        storage_states_by_id.get(requirement.storage_state_id)
        if requirement is not None
        else next(
            (
                state
                for state in run.planning_input.current_storage_states
                if winning_execution_plan is not None
                and state.execution_scope_id == winning_execution_plan.execution_scope_id
            ),
            None,
        )
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
    soc_timeline: list[dict[str, object]] = []
    if initial_storage_state is not None and winning_energy_path is not None:
        soc_timeline.append(
            {
                "at": run.planning_input.captured_at.isoformat(),
                "soc_percent": round(initial_storage_state.current_soc * 100, 2),
                "primitive": "actual",
            }
        )
        for state in winning_energy_path.projected_states:
            if state.at <= run.planning_input.captured_at or state.battery_soc is None:
                continue
            segment = next(
                (
                    item
                    for item in winning_energy_path.segments
                    if item.starts_at < state.at <= item.ends_at
                ),
                None,
            )
            soc_timeline.append(
                {
                    "at": state.at.isoformat(),
                    "soc_percent": round(state.battery_soc * 100, 2),
                    "primitive": (segment.primitive.value if segment is not None else "projected"),
                }
            )
    return {
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "captured_at": run.planning_input.captured_at.isoformat(),
        "initial_soc": (
            initial_storage_state.current_soc if initial_storage_state is not None else None
        ),
        "soc_timeline": soc_timeline if not fallback_active else [],
        "soc_projection_captured_at": (
            run.planning_input.captured_at.isoformat() if soc_timeline and not fallback_active
            else None
        ),
        "soc_projection_retained": False,
        "valid_until": (
            run.planning_input.horizon_end.isoformat()
            if run.planning_input.horizon_end is not None
            else None
        ),
        "attention": {
            "required": fallback_active,
            "code": ("fallback_no_actionable_plan" if fallback_active else None),
            "title": ("Geen uitvoerbaar plan beschikbaar" if fallback_active else None),
            "message": (
                "De veilige terugvalmodus blijft actief; aandacht vereist."
                if fallback_active
                else None
            ),
        },
        "strategy": {
            "status": regime.regime if regime is not None else "not_available",
            "reason": regime.reason if regime is not None else "not_available",
            "objective_order": (list(regime.objective_order) if regime is not None else []),
            "forecast_confidence": (regime.forecast_confidence if regime is not None else None),
            "forecast_confidence_available": (
                regime.forecast_confidence_available if regime is not None else False
            ),
            "forecast_confidence_method_version": (
                regime.forecast_confidence_method_version if regime is not None else None
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
            "confidence": (winning_outcome.confidence if winning_outcome is not None else None),
        },
        "market_revision_comparison": project_market_revision_comparison(run),
        "plan_decision": plan_decision,
        "storage_target": {
            "required_energy_wh": (
                requirement.required_energy_wh if requirement is not None else None
            ),
            "required_soc": (requirement.required_soc if requirement is not None else None),
            "required_by": (
                requirement.required_by.isoformat() if requirement is not None else None
            ),
            "reason": requirement.reason if requirement is not None else None,
            "confidence": (requirement.confidence if requirement is not None else None),
            "requirement_satisfied": (
                winning_outcome.requirement_satisfied if winning_outcome is not None else None
            ),
            "projected_energy_wh": (
                winning_outcome.storage_energy_at_requirement_wh
                if winning_outcome is not None
                else None
            ),
            "pv_contribution_wh": (
                winning_outcome.pv_storage_contribution_wh if winning_outcome is not None else None
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
                "active"
                if due_plan is not None
                else "scheduled"
                if next_plan is not None
                else "not_available"
            ),
            "valid_from": (
                applicable_plan.valid_from.isoformat() if applicable_plan is not None else None
            ),
            "valid_until": (
                applicable_plan.valid_until.isoformat() if applicable_plan is not None else None
            ),
            "planned_primitive": (
                applicable_plan.planned_primitive.value if applicable_plan is not None else None
            ),
            "planned_vendor_mode": (
                applicable_plan.planned_vendor_mode if applicable_plan is not None else None
            ),
            "primitive_status": run.primitive_boundary.status,
            "execution_reason": run.primitive_boundary.execution_reason,
            "blockers": list(run.primitive_boundary.blockers),
        },
        "execution_plans": [
            {
                "plan_id": plan.plan_id,
                "energy_path_id": plan.winning_energy_path_id,
                "execution_scope_id": plan.execution_scope_id,
                "valid_from": plan.valid_from.isoformat(),
                "valid_until": plan.valid_until.isoformat(),
                "planned_primitive": plan.planned_primitive.value,
                "planned_vendor_mode": plan.planned_vendor_mode,
                "lifecycle_status": plan.lifecycle_status,
                "observer_only": plan.observer_only,
                "segments": [
                    {
                        "starts_at": segment.starts_at.isoformat(),
                        "ends_at": segment.ends_at.isoformat(),
                        "primitive": segment.primitive.value,
                        "purpose": segment.purpose,
                        "requested_power_w": segment.requested_power_w,
                        "charge_source_policy": (
                            segment.charge_source_policy.value
                            if segment.charge_source_policy is not None
                            else None
                        ),
                    }
                    for segment in plan.segments
                ],
            }
            for plan in winning_execution_plans
        ]
        if not fallback_active
        else [],
        "chosen_plan": {
            "plan_id": (
                winning_execution_plan.plan_id
                if winning_execution_plan is not None and not fallback_active
                else None
            ),
            "plan_revision": (
                winning_commitment.plan_revision
                if winning_commitment is not None and not fallback_active
                else None
            ),
            "execution_scope_id": (
                winning_execution_plan.execution_scope_id
                if winning_execution_plan is not None and not fallback_active
                else None
            ),
            "valid_from": (
                winning_execution_plan.valid_from.isoformat()
                if winning_execution_plan is not None and not fallback_active
                else None
            ),
            "valid_until": (
                winning_execution_plan.valid_until.isoformat()
                if winning_execution_plan is not None and not fallback_active
                else None
            ),
            "source_policy": (
                winning_commitment.source_policy
                if winning_commitment is not None and not fallback_active
                else (
                    charge_segments[0].charge_source_policy.value
                    if len(charge_segments) == 1
                    and charge_segments[0].charge_source_policy is not None
                    and not fallback_active
                    else None
                )
            ),
            "average_charge_window_price_eur_per_kwh": (
                winning_commitment.average_charge_window_price_eur_per_kwh
                if winning_commitment is not None and not fallback_active
                else None
            ),
            "worst_case_financial_result_eur": (
                winning_commitment.worst_case_financial_result_eur
                if winning_commitment is not None and not fallback_active
                else None
            ),
            "minimum_storage_energy_at_horizon_end_wh": (
                winning_commitment.minimum_storage_energy_at_horizon_end_wh
                if winning_commitment is not None and not fallback_active
                else None
            ),
            "reserve_respected_across_scenarios": (
                winning_commitment.reserve_respected_across_scenarios
                if winning_commitment is not None and not fallback_active
                else None
            ),
            "target_held_across_scenarios": (
                winning_commitment.target_held_across_scenarios
                if winning_commitment is not None and not fallback_active
                else None
            ),
            "candidate_id": (
                winning_candidate.candidate_id
                if winning_candidate is not None and not fallback_active
                else winning_execution_plan.winning_candidate_id
                if winning_execution_plan is not None and not fallback_active
                else None
            ),
            "energy_path_id": (
                winning_candidate.energy_path_id
                if winning_candidate is not None and not fallback_active
                else winning_execution_plan.winning_energy_path_id
                if winning_execution_plan is not None and not fallback_active
                else None
            ),
            "family": (
                winning_candidate.family
                if winning_candidate is not None and not fallback_active
                else None
            ),
            "decisive_step": (run.evaluation.decisive_step if not fallback_active else None),
            "reason": run.evaluation.reason if not fallback_active else None,
            "charge_window_starts_at": (
                winning_outcome.charge_window_starts_at.isoformat()
                if winning_outcome is not None and not fallback_active
                else (
                    charge_segments[0].starts_at.isoformat()
                    if charge_segments and not fallback_active
                    else None
                )
            ),
            "charge_window_ends_at": (
                winning_outcome.charge_window_ends_at.isoformat()
                if winning_outcome is not None and not fallback_active
                else (
                    charge_segments[-1].ends_at.isoformat()
                    if charge_segments and not fallback_active
                    else None
                )
            ),
            "required_energy_wh": (
                winning_outcome.required_energy_wh
                if winning_outcome is not None and not fallback_active
                else (
                    winning_commitment.target_energy_wh
                    if winning_commitment is not None and not fallback_active
                    else None
                )
            ),
            "initial_storage_energy_wh": (
                initial_storage_energy_wh if not fallback_active else None
            ),
            "energy_to_target_wh": (energy_to_target_wh if not fallback_active else None),
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
                winning_candidate.pv_forecast_basis
                if run.planning_input.daily_charge_context is not None
                and winning_candidate is not None and not fallback_active
                else winning_outcome.pv_forecast_basis
                if winning_outcome is not None and not fallback_active
                else (
                    winning_candidate.pv_forecast_basis
                    if winning_candidate is not None and not fallback_active
                    else None
                )
            ),
            "effective_maximum_storage_energy_wh": (
                winning_outcome.effective_maximum_storage_energy_wh
                if isinstance(winning_outcome, MepCandidateOutcome)
                and not fallback_active
                else None
            ),
            "confidence_weighted_peak_storage_energy_wh": (
                winning_outcome.confidence_weighted_peak_storage_energy_wh
                if isinstance(winning_outcome, MepCandidateOutcome)
                and not fallback_active
                else None
            ),
            "confidence_weighted_peak_at": (
                winning_outcome.confidence_weighted_peak_at.isoformat()
                if isinstance(winning_outcome, MepCandidateOutcome)
                and not fallback_active
                else None
            ),
            "effective_maximum_required_by": (
                winning_outcome.effective_maximum_required_by.isoformat()
                if isinstance(winning_outcome, MepCandidateOutcome)
                and winning_outcome.effective_maximum_required_by is not None
                and not fallback_active
                else None
            ),
            "effective_maximum_reached": (
                winning_outcome.effective_maximum_reached
                if isinstance(winning_outcome, MepCandidateOutcome)
                and not fallback_active
                else None
            ),
            "effective_maximum_reached_at": (
                winning_outcome.effective_maximum_reached_at.isoformat()
                if isinstance(winning_outcome, MepCandidateOutcome)
                and winning_outcome.effective_maximum_reached_at is not None
                and not fallback_active
                else None
            ),
            "effective_maximum_basis_confidence": (
                winning_outcome.effective_maximum_basis_confidence
                if isinstance(winning_outcome, MepCandidateOutcome)
                and not fallback_active
                else None
            ),
            "effective_maximum_reason": (
                winning_outcome.effective_maximum_reason
                if isinstance(winning_outcome, MepCandidateOutcome)
                and not fallback_active
                else None
            ),
            "effective_maximum_evidence_id": (
                winning_outcome.effective_maximum_evidence_id
                if isinstance(winning_outcome, MepCandidateOutcome)
                and not fallback_active
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
                else (
                    winning_commitment.target_held_across_scenarios
                    if winning_commitment is not None and not fallback_active
                    else None
                )
            ),
            "reserve_satisfied": (
                winning_outcome.reserve_satisfied
                if winning_outcome is not None and not fallback_active
                else (
                    winning_commitment.reserve_respected_across_scenarios
                    if winning_commitment is not None and not fallback_active
                    else None
                )
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
                else (
                    winning_commitment.minimum_confidence
                    if winning_commitment is not None and not fallback_active
                    else None
                )
            ),
            "requirement_confidence": (
                requirement.confidence if requirement is not None and not fallback_active else None
            ),
            "confidence_assessment": (
                {
                    "result": winning_outcome.confidence_assessment.result,
                    "limiting_component": (
                        winning_outcome.confidence_assessment.limiting_component
                    ),
                    "method_version": (winning_outcome.confidence_assessment.method_version),
                    "components": [
                        {
                            "name": component.name,
                            "value": component.value,
                            "method_version": component.method_version,
                            "evidence_ids": list(component.evidence_ids),
                        }
                        for component in (winning_outcome.confidence_assessment.components)
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
            ]
            if not fallback_active
            else [],
        },
        "alternatives": [
            {
                "candidate_id": candidate.candidate_id,
                "energy_path_id": candidate.energy_path_id,
                "family": candidate.family,
                "selected": (
                    not fallback_active
                    and candidate.candidate_id == run.evaluation.winning_candidate_id
                ),
                "charge_window_starts_at": (
                    outcome.charge_window_starts_at.isoformat() if outcome is not None else None
                ),
                "charge_window_ends_at": (
                    outcome.charge_window_ends_at.isoformat() if outcome is not None else None
                ),
                "storage_energy_at_window_end_wh": (
                    outcome.storage_energy_at_window_end_wh if outcome is not None else None
                ),
                "storage_energy_at_requirement_wh": (
                    outcome.storage_energy_at_requirement_wh if outcome is not None else None
                ),
                "requirement_satisfied": (
                    outcome.requirement_satisfied if outcome is not None else None
                ),
                "charge_target_satisfied": (
                    outcome.charge_target_satisfied if outcome is not None else None
                ),
                "reserve_satisfied": (outcome.reserve_satisfied if outcome is not None else None),
                "recoverability": (outcome.recoverability if outcome is not None else None),
                "confidence": (outcome.confidence if outcome is not None else None),
                "pv_contribution_wh": (
                    outcome.pv_storage_contribution_wh if outcome is not None else None
                ),
                "grid_contribution_wh": (
                    outcome.grid_storage_contribution_wh if outcome is not None else None
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
    household_intervals = household_forecast.intervals if household_forecast is not None else ()
    market_timezone = ZoneInfo("Europe/Amsterdam")
    display_starts_at = planning_input.captured_at.astimezone(market_timezone).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    display_ends_at = display_starts_at + timedelta(days=2)
    selected_display_price_points = (
        planning_input.price_points if display_price_points is None else display_price_points
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
    intervals = timeline.intervals if timeline is not None else ()

    pipeline: list[dict[str, object]] = [
        {
            "stage": stage,
            "entity_id": card.entity_id,
            "state": card.state,
            "attributes": dict(card.attributes),
            "fault_explanation_nl": recovery_details(card.attributes),
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
    # The comparison belongs to planning_status in the web payload. Keep its
    # lineage on the technical card without serializing every alternative twice.
    for card in pipeline:
        attributes = card["attributes"]
        assert isinstance(attributes, dict)
        comparison = attributes.get("market_revision_comparison")
        if isinstance(comparison, dict):
            attributes["market_revision_comparison"] = {
                key: value for key, value in comparison.items()
                if key not in {"alternatives", "evidence_dictionary"}
            } | {
                "details_reference": "planning_status.market_revision_comparison",
                "alternative_count": len(comparison.get("alternatives", ())),
            }
    healthy_count = sum(item["health"] == "healthy" for item in pipeline)
    pipeline_health = {
        "healthy": healthy_count == len(pipeline),
        "healthy_count": healthy_count,
        "total_count": len(pipeline),
        "summary_nl": (
            f"Geen technische fouten gemeld – {healthy_count}/{len(pipeline)} stappen groen."
            if healthy_count == len(pipeline)
            else (f"Technische fout gemeld – {len(pipeline) - healthy_count} stap(pen) rood.")
        ),
    }
    execution_attributes = pipeline[5]["attributes"]
    assert isinstance(execution_attributes, dict)
    observer_only = execution_attributes.get("observer_only", True)
    pv_energy_timeline: dict[str, object] = {
        "available": timeline is not None,
        "timeline_id": (timeline.timeline_id if timeline is not None else None),
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "interval_count": len(intervals),
        "total_wh": sum(interval.pv_energy_wh for interval in intervals),
        "starts_at": (intervals[0].starts_at.isoformat() if intervals else None),
        "ends_at": (intervals[-1].ends_at.isoformat() if intervals else None),
        "intervals": [
            {
                "interval_id": interval.interval_id,
                "starts_at": interval.starts_at.isoformat(),
                "ends_at": interval.ends_at.isoformat(),
                "pv_energy_wh": interval.pv_energy_wh,
                "forecast_lower_energy_wh": (interval.forecast_lower_energy_wh),
                "forecast_central_energy_wh": (interval.forecast_central_energy_wh),
                "forecast_upper_energy_wh": (interval.forecast_upper_energy_wh),
                "forecast_range_status": interval.forecast_range_status,
                "evidence_type": interval.evidence_type,
                "confidence": interval.confidence,
                "actual_evidence_ids": list(interval.actual_evidence_ids),
                "forecast_evidence_ids": list(interval.forecast_evidence_ids),
                "conversion_method_version": (interval.conversion_method_version),
            }
            for interval in intervals
        ],
    }

    household_load_forecast: dict[str, object] = {
        "available": household_forecast is not None,
        "forecast_id": (household_forecast.forecast_id if household_forecast is not None else None),
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "interval_count": len(household_intervals),
        "total_wh": sum(interval.expected_energy_wh for interval in household_intervals),
        "average_confidence": (
            sum(interval.confidence for interval in household_intervals) / len(household_intervals)
            if household_intervals
            else 0.0
        ),
        "starts_at": (
            household_intervals[0].starts_at.isoformat() if household_intervals else None
        ),
        "ends_at": (household_intervals[-1].ends_at.isoformat() if household_intervals else None),
        "fallback_active": (
            household_forecast.fallback_active if household_forecast is not None else False
        ),
        "fallback_reason": (
            household_forecast.fallback_reason if household_forecast is not None else None
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
                    "duration_seconds": (opportunity.metrics.duration_seconds),
                    "average_price_eur_per_kwh": (opportunity.metrics.average_price_eur_per_kwh),
                    "minimum_price_eur_per_kwh": (opportunity.metrics.minimum_price_eur_per_kwh),
                    "maximum_price_eur_per_kwh": (opportunity.metrics.maximum_price_eur_per_kwh),
                    "boundary_eur_per_kwh": (opportunity.metrics.boundary_eur_per_kwh),
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
        "storage_mode_transition_history": _transition_history_view(storage_mode_transitions),
    }


def _transition_history_view(
    events: tuple[StorageModeTransitionEvent, ...],
) -> list[dict[str, object]]:
    return [
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
        for event in events
    ]
