"""Bounded live coupling of actual PV energy into Planning Input."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from time import perf_counter

from picot.v2.contracts import PVEnergyTimelineInterval
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.pv_actual_history import PVHistoryReadResult
from picot.v2.pv_actual_intervals import (
    PVActualIntervalDiagnosis,
    diagnose_actual_pv_interval,
)


@dataclass(frozen=True, slots=True)
class LivePVActualDiagnostics:
    history_status: str
    interval_status: str
    cache_hit: bool
    entity_id: str
    starts_at: datetime | None
    ends_at: datetime | None
    lookup_starts_at: datetime | None
    error: str | None
    conversion_method_version: str | None
    actual_evidence_ids: tuple[str, ...]
    processing_ms: float
    gap_reason: str | None = None
    observation_count: int = 0
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    maximum_observed_gap_seconds: float | None = None
    allowed_gap_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class _CachedResult:
    history_status: str
    error: str | None
    interval: PVEnergyTimelineInterval | None
    diagnosis: PVActualIntervalDiagnosis | None


class LivePVActualCache:
    """Keep each bounded actual-PV history result for the runtime lifetime."""

    def __init__(self) -> None:
        self._results: dict[
            tuple[str, datetime, datetime],
            _CachedResult,
        ] = {}

    def get(
        self,
        key: tuple[str, datetime, datetime],
    ) -> _CachedResult | None:
        return self._results.get(key)

    def store(
        self,
        key: tuple[str, datetime, datetime],
        result: _CachedResult,
    ) -> None:
        self._results[key] = result


HistoryReader = Callable[
    ...,
    PVHistoryReadResult,
]


def apply_latest_closed_actual_pv(
    bundle: PlanningInputBundle,
    *,
    entity_id: str,
    history_reader: HistoryReader,
    cache: LivePVActualCache,
    telemetry_interval_seconds: int,
) -> tuple[PlanningInputBundle, LivePVActualDiagnostics]:
    """Replace only the latest closed forecast interval with actual PV."""
    started = perf_counter()
    timeline = bundle.snapshot.pv_energy_timeline

    if timeline is None:
        return bundle, _diagnostics(
            started=started,
            history_status="not_requested",
            interval_status="no_timeline",
            cache_hit=False,
            entity_id=entity_id,
        )

    closed_forecasts = tuple(
        interval
        for interval in timeline.intervals
        if (
            interval.evidence_type == "FORECAST"
            and interval.ends_at <= bundle.snapshot.captured_at
        )
    )
    if not closed_forecasts:
        return bundle, _diagnostics(
            started=started,
            history_status="not_requested",
            interval_status="no_closed_forecast",
            cache_hit=False,
            entity_id=entity_id,
        )

    selected = max(
        closed_forecasts,
        key=lambda interval: (
            interval.ends_at,
            interval.starts_at,
            interval.interval_id,
        ),
    )
    key = (
        entity_id,
        selected.starts_at,
        selected.ends_at,
    )
    cached = cache.get(key)
    cache_hit = cached is not None

    lookup_starts_at = selected.starts_at - timedelta(
        seconds=max(30, telemetry_interval_seconds * 3)
    )

    if cached is None:
        history = history_reader(
            entity_id=entity_id,
            starts_at=lookup_starts_at,
            ends_at=selected.ends_at,
        )
        diagnosis = None
        if history.status == "available":
            diagnosis = diagnose_actual_pv_interval(
                interval_id=(
                    "pv-actual-"
                    f"{selected.starts_at.isoformat()}"
                ),
                starts_at=selected.starts_at,
                ends_at=selected.ends_at,
                captured_at=bundle.snapshot.captured_at,
                observations=history.observations,
                telemetry_interval_seconds=(
                    telemetry_interval_seconds
                ),
            )
        cached = _CachedResult(
            history_status=history.status,
            error=history.error,
            interval=(
                diagnosis.interval
                if diagnosis is not None
                else None
            ),
            diagnosis=diagnosis,
        )
        cache.store(key, cached)

    actual = cached.interval
    diagnosis = cached.diagnosis
    interval_status = "actual" if actual is not None else "gap"
    enriched = bundle

    if actual is not None:
        intervals = tuple(
            actual if interval is selected else interval
            for interval in timeline.intervals
        )
        enriched = replace(
            bundle,
            snapshot=replace(
                bundle.snapshot,
                pv_energy_timeline=replace(
                    timeline,
                    intervals=intervals,
                ),
            ),
        )

    diagnostics = _diagnostics(
        started=started,
        history_status=(
            "cached" if cache_hit else cached.history_status
        ),
        interval_status=interval_status,
        cache_hit=cache_hit,
        entity_id=entity_id,
        starts_at=selected.starts_at,
        ends_at=selected.ends_at,
        lookup_starts_at=lookup_starts_at,
        error=cached.error,
        conversion_method_version=(
            actual.conversion_method_version
            if actual is not None
            else None
        ),
        actual_evidence_ids=(
            actual.actual_evidence_ids
            if actual is not None
            else ()
        ),
        gap_reason=(
            diagnosis.reason
            if diagnosis is not None
            else None
        ),
        observation_count=(
            diagnosis.observation_count
            if diagnosis is not None
            else 0
        ),
        first_observed_at=(
            diagnosis.first_observed_at
            if diagnosis is not None
            else None
        ),
        last_observed_at=(
            diagnosis.last_observed_at
            if diagnosis is not None
            else None
        ),
        maximum_observed_gap_seconds=(
            diagnosis.maximum_observed_gap_seconds
            if diagnosis is not None
            else None
        ),
        allowed_gap_seconds=(
            diagnosis.allowed_gap_seconds
            if diagnosis is not None
            else None
        ),
    )
    return enriched, diagnostics


def _diagnostics(
    *,
    started: float,
    history_status: str,
    interval_status: str,
    cache_hit: bool,
    entity_id: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    lookup_starts_at: datetime | None = None,
    error: str | None = None,
    conversion_method_version: str | None = None,
    actual_evidence_ids: tuple[str, ...] = (),
    gap_reason: str | None = None,
    observation_count: int = 0,
    first_observed_at: datetime | None = None,
    last_observed_at: datetime | None = None,
    maximum_observed_gap_seconds: float | None = None,
    allowed_gap_seconds: float | None = None,
) -> LivePVActualDiagnostics:
    return LivePVActualDiagnostics(
        history_status=history_status,
        interval_status=interval_status,
        cache_hit=cache_hit,
        entity_id=entity_id,
        starts_at=starts_at,
        ends_at=ends_at,
        lookup_starts_at=lookup_starts_at,
        error=error,
        conversion_method_version=conversion_method_version,
        actual_evidence_ids=actual_evidence_ids,
        processing_ms=round(
            (perf_counter() - started) * 1000.0,
            3,
        ),
        gap_reason=gap_reason,
        observation_count=observation_count,
        first_observed_at=first_observed_at,
        last_observed_at=last_observed_at,
        maximum_observed_gap_seconds=(
            maximum_observed_gap_seconds
        ),
        allowed_gap_seconds=allowed_gap_seconds,
    )
