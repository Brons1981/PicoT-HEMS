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
from picot.v2.pv_deviation import (
    PVDeviationResult,
    evaluate_pv_energy_deviation,
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
    history_semantics: str | None = None
    interruption_state: str | None = None
    interrupted_at: datetime | None = None
    deviation_result: PVDeviationResult | None = None
    deviation_results: tuple[PVDeviationResult, ...] = ()
    closed_forecast_count: int = 0
    actual_interval_count: int = 0
    gap_interval_count: int = 0


@dataclass(frozen=True, slots=True)
class _CachedResult:
    history_status: str
    error: str | None
    diagnoses: tuple[PVActualIntervalDiagnosis, ...]


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
    """Replace every valid closed forecast using one bounded history read."""
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
        sorted(
            (
                interval
                for interval in timeline.intervals
                if (
                    interval.evidence_type == "FORECAST"
                    and interval.ends_at <= bundle.snapshot.captured_at
                )
            ),
            key=lambda interval: (
                interval.starts_at,
                interval.ends_at,
                interval.interval_id,
            ),
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

    first = closed_forecasts[0]
    last = closed_forecasts[-1]
    key = (entity_id, first.starts_at, last.ends_at)
    cached = cache.get(key)
    cache_hit = cached is not None
    lookup_starts_at = first.starts_at - timedelta(
        seconds=max(30, telemetry_interval_seconds * 3)
    )

    if cached is None:
        history = history_reader(
            entity_id=entity_id,
            starts_at=lookup_starts_at,
            ends_at=last.ends_at,
        )
        diagnoses: tuple[PVActualIntervalDiagnosis, ...] = ()
        if history.status == "available":
            diagnoses = tuple(
                diagnose_actual_pv_interval(
                    interval_id=(
                        "pv-actual-"
                        f"{forecast.starts_at.isoformat()}"
                    ),
                    starts_at=forecast.starts_at,
                    ends_at=forecast.ends_at,
                    captured_at=bundle.snapshot.captured_at,
                    observations=history.observations,
                    telemetry_interval_seconds=(
                        telemetry_interval_seconds
                    ),
                )
                for forecast in closed_forecasts
            )
        cached = _CachedResult(
            history_status=history.status,
            error=history.error,
            diagnoses=diagnoses,
        )
        cache.store(key, cached)

    actual_by_forecast_id: dict[str, PVEnergyTimelineInterval] = {}
    deviation_results: list[PVDeviationResult] = []
    actual_intervals: list[PVEnergyTimelineInterval] = []
    for forecast, diagnosis in zip(
        closed_forecasts,
        cached.diagnoses,
        strict=True,
    ):
        actual = diagnosis.interval
        if actual is None:
            continue
        actual = replace(
            actual,
            forecast_evidence_ids=forecast.forecast_evidence_ids,
        )
        actual_by_forecast_id[forecast.interval_id] = actual
        actual_intervals.append(actual)
        deviation_results.append(
            evaluate_pv_energy_deviation(
                forecast=forecast,
                actual=actual,
                evaluated_at=bundle.snapshot.captured_at,
            )
        )

    enriched = bundle
    if actual_by_forecast_id:
        intervals = tuple(
            actual_by_forecast_id.get(interval.interval_id, interval)
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

    actual_count = len(actual_intervals)
    gap_count = len(closed_forecasts) - actual_count
    if actual_count == len(closed_forecasts):
        interval_status = "actual"
    elif actual_count:
        interval_status = "partial"
    else:
        interval_status = "gap"

    latest_diagnosis = (
        cached.diagnoses[-1] if cached.diagnoses else None
    )
    latest_actual = (
        actual_by_forecast_id.get(last.interval_id)
    )
    evidence_ids = tuple(dict.fromkeys(
        evidence_id
        for actual in actual_intervals
        for evidence_id in actual.actual_evidence_ids
    ))
    deviations = tuple(deviation_results)

    diagnostics = _diagnostics(
        started=started,
        history_status=(
            "cached" if cache_hit else cached.history_status
        ),
        interval_status=interval_status,
        cache_hit=cache_hit,
        entity_id=entity_id,
        starts_at=first.starts_at,
        ends_at=last.ends_at,
        lookup_starts_at=lookup_starts_at,
        error=cached.error,
        conversion_method_version=(
            actual_intervals[0].conversion_method_version
            if actual_intervals
            else None
        ),
        actual_evidence_ids=evidence_ids,
        gap_reason=(
            latest_diagnosis.reason
            if latest_diagnosis is not None
            else None
        ),
        observation_count=(
            latest_diagnosis.observation_count
            if latest_diagnosis is not None
            else 0
        ),
        first_observed_at=(
            latest_diagnosis.first_observed_at
            if latest_diagnosis is not None
            else None
        ),
        last_observed_at=(
            latest_diagnosis.last_observed_at
            if latest_diagnosis is not None
            else None
        ),
        maximum_observed_gap_seconds=(
            latest_diagnosis.maximum_observed_gap_seconds
            if latest_diagnosis is not None
            else None
        ),
        allowed_gap_seconds=(
            latest_diagnosis.allowed_gap_seconds
            if latest_diagnosis is not None
            else None
        ),
        history_semantics=(
            latest_diagnosis.history_semantics
            if latest_diagnosis is not None
            else None
        ),
        interruption_state=(
            latest_diagnosis.interruption_state
            if latest_diagnosis is not None
            else None
        ),
        interrupted_at=(
            latest_diagnosis.interrupted_at
            if latest_diagnosis is not None
            else None
        ),
        deviation_result=(
            deviations[-1] if deviations else None
        ),
        deviation_results=deviations,
        closed_forecast_count=len(closed_forecasts),
        actual_interval_count=actual_count,
        gap_interval_count=gap_count,
    )
    del latest_actual
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
    history_semantics: str | None = None,
    interruption_state: str | None = None,
    interrupted_at: datetime | None = None,
    deviation_result: PVDeviationResult | None = None,
    deviation_results: tuple[PVDeviationResult, ...] = (),
    closed_forecast_count: int = 0,
    actual_interval_count: int = 0,
    gap_interval_count: int = 0,
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
        history_semantics=history_semantics,
        interruption_state=interruption_state,
        interrupted_at=interrupted_at,
        deviation_result=deviation_result,
        deviation_results=deviation_results,
        closed_forecast_count=closed_forecast_count,
        actual_interval_count=actual_interval_count,
        gap_interval_count=gap_interval_count,
    )
