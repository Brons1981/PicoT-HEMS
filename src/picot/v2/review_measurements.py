"""Evidence retention and coverage diagnostics for the passive review only.

No repair, interpolation or replacement of missing sensor values is performed.
State-held Recorder series and sampled household observations have different
coverage rules; an unchanged Recorder value is not a missing heartbeat.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

from picot.v2.power_history import PowerHistorySnapshot

REVIEW_ROLES = (
    "pv_generation", "household_load", "grid_import", "grid_export",
    "battery_charge", "battery_discharge", "storage_soc",
)
MAX_REPORTED_GAPS = 20


def measurement_coverage(history: PowerHistorySnapshot) -> dict[str, Any]:
    """Report exact failing spans, including anchors and every required role."""
    result: dict[str, Any] = {}
    raw = {series.role: series for series in history.series}
    for role in REVIEW_ROLES:
        series = raw.get(role)
        points = sorted(series.points, key=lambda p: p.sampled_at) if series else []
        points = [p for p in points if p.sampled_at <= history.ends_at]
        gaps: list[dict[str, Any]] = []
        count = 0

        def gap(
            reason: str, start: datetime, end: datetime,
            gaps: list[dict[str, Any]] = gaps,
        ) -> None:
            nonlocal count
            start, end = max(start, history.starts_at), min(end, history.ends_at)
            if end < start:
                return
            count += 1
            if len(gaps) < MAX_REPORTED_GAPS:
                gaps.append({"reason": reason, "starts_at": start.isoformat(),
                             "ends_at": end.isoformat(),
                             "duration_seconds": (end - start).total_seconds()})

        if not points:
            gap("missing_measured_series", history.starts_at, history.ends_at)
        else:
            if points[0].sampled_at > history.starts_at:
                gap("measurement_start_missing", history.starts_at, points[0].sampled_at)
            for index, point in enumerate(points):
                following = points[index + 1] if index + 1 < len(points) else None
                end = following.sampled_at if following else history.ends_at
                invalid = not isfinite(point.power_w) or point.power_w < 0
                invalid |= role == "storage_soc" and point.power_w > 100
                if invalid:
                    gap("measurement_unavailable", point.sampled_at, end)
                if series is not None and series.history_semantics == "sampled_linear":
                    if following and end - point.sampled_at > timedelta(minutes=5):
                        gap("household_measurement_gap", point.sampled_at, end)
                    elif not following and end - point.sampled_at > timedelta(minutes=2):
                        gap("household_measurement_tail_missing", point.sampled_at, end)
        result[role] = {
            "source_entity_id": series.source_entity_id if series else None,
            "history_semantics": series.history_semantics if series else None,
            "point_count": len(points),
            "first_point_at": points[0].sampled_at.isoformat() if points else None,
            "last_point_at": points[-1].sampled_at.isoformat() if points else None,
            "gap_count": count, "gaps": gaps,
            "omitted_gap_count": max(0, count - len(gaps)),
        }
    return result


def measurement_archive_paths(review_path: Path) -> tuple[Path, Path]:
    return (review_path.with_name(f"{review_path.stem}_measurements_today.json.gz"),
            review_path.with_name(f"{review_path.stem}_measurements_yesterday.json.gz"))


def save_measurements(
    path: Path, history: PowerHistorySnapshot, *, alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically retain raw review inputs, preserving gaps as JSON null.

The observer calls this for today/yesterday only. A transport failure must not
replace the last readable snapshot. No extra Home Assistant requests are made.
"""
    if history.status != "available" or history.error is not None:
        return {"status": "unavailable", "reason": history.error or history.status,
                "file": path.name}
    payload = {
        "schema_version": 1, "observer_only": True,
        "starts_at": history.starts_at.isoformat(), "ends_at": history.ends_at.isoformat(),
        "status": history.status, "error": history.error,
        "method_version": history.method_version,
        "series": [{
            "series_id": s.series_id, "role": s.role,
            "source_entity_id": s.source_entity_id, "transform": s.transform,
            "history_semantics": s.history_semantics,
            "points": [{"sampled_at": p.sampled_at.isoformat(),
                        "power_w": p.power_w if isfinite(p.power_w) else None,
                        "evidence_id": p.evidence_id} for p in s.points],
        } for s in history.series],
    }
    if alignment is not None:
        payload["aligned_measurements"] = alignment
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".writing")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=1) as stream:
            json.dump(payload, stream, allow_nan=False, separators=(",", ":"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "available", "file": path.name,
            "starts_at": history.starts_at.isoformat(), "ends_at": history.ends_at.isoformat()}
