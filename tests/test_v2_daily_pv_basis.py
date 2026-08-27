from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from picot.v2.contracts import (
    PlanningInputSnapshot,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.daily_pv_basis import apply_daily_measured_pv_basis
from picot.v2.live_pv_actual import LivePVActualDiagnostics
from picot.v2.pv_cumulative_evidence import build_pv_cumulative_evidence
from picot.v2.pv_deviation import evaluate_pv_energy_deviation

CAPTURED_AT = datetime(2026, 8, 26, 12, 33, tzinfo=UTC)
LOCAL_TIMEZONE = ZoneInfo("Europe/Amsterdam")


def _interval(
    interval_id: str,
    starts_at: datetime,
    *,
    lower_wh: float,
    central_wh: float,
    actual_wh: float | None = None,
) -> PVEnergyTimelineInterval:
    return PVEnergyTimelineInterval(
        interval_id=interval_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        pv_energy_wh=central_wh if actual_wh is None else actual_wh,
        evidence_type="FORECAST" if actual_wh is None else "ACTUAL",
        confidence=0.8 if actual_wh is None else 1.0,
        actual_evidence_ids=() if actual_wh is None else (f"actual-{interval_id}",),
        forecast_evidence_ids=(f"forecast-{interval_id}",),
        conversion_method_version="test:v1",
        forecast_lower_energy_wh=lower_wh,
        forecast_central_energy_wh=central_wh,
        forecast_upper_energy_wh=central_wh * 1.1,
        forecast_range_status="available",
        forecast_range_source_fields=("lower", "central", "upper"),
        forecast_range_method_version="test-range:v1",
    )


def _diagnostics(actual_ratio: float) -> LivePVActualDiagnostics:
    deviations = []
    start = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    for index in range(4):
        forecast = _interval(
            f"closed-{index}",
            start + timedelta(minutes=30 * index),
            lower_wh=350.0,
            central_wh=500.0,
        )
        actual = replace(
            forecast,
            interval_id=f"actual-{index}",
            pv_energy_wh=500.0 * actual_ratio,
            evidence_type="ACTUAL",
            actual_evidence_ids=(f"goodwe-{index}",),
            forecast_lower_energy_wh=None,
            forecast_central_energy_wh=None,
            forecast_upper_energy_wh=None,
            forecast_range_status="unavailable",
            forecast_range_source_fields=(),
            forecast_range_method_version=None,
        )
        deviations.append(
            evaluate_pv_energy_deviation(
                forecast=forecast,
                actual=actual,
                evaluated_at=CAPTURED_AT,
            )
        )
    evidence = build_pv_cumulative_evidence(
        tuple(deviations),
        closed_interval_count=4,
        evaluated_at=CAPTURED_AT,
    )
    return LivePVActualDiagnostics(
        history_status="available",
        interval_status="actual",
        cache_hit=False,
        entity_id="sensor.goodwe",
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        lookup_starts_at=start,
        error=None,
        conversion_method_version="test:v1",
        actual_evidence_ids=("goodwe",),
        processing_ms=1.0,
        deviation_results=tuple(deviations),
        cumulative_evidence=evidence,
        closed_forecast_count=4,
        actual_interval_count=4,
    )


def _snapshot() -> PlanningInputSnapshot:
    today = _interval(
        "today-future",
        datetime(2026, 8, 26, 13, 0, tzinfo=UTC),
        lower_wh=300.0,
        central_wh=600.0,
    )
    tomorrow = _interval(
        "tomorrow-future",
        datetime(2026, 8, 27, 10, 0, tzinfo=UTC),
        lower_wh=200.0,
        central_wh=500.0,
    )
    return PlanningInputSnapshot(
        run_id="run",
        snapshot_id="snapshot",
        captured_at=CAPTURED_AT,
        picot_version="test",
        architecture_baseline_commit="test",
        pipeline_contract_version="test",
        strategy_id="test",
        horizon_end=tomorrow.ends_at,
        pv_energy_timeline=PVEnergyTimeline(
            timeline_id="timeline",
            run_id="run",
            snapshot_id="snapshot",
            intervals=(today, tomorrow),
        ),
    )


def test_daily_observer_promotes_today_to_central_and_keeps_tomorrow_midpoint() -> None:
    snapshot, decision = apply_daily_measured_pv_basis(
        _snapshot(),
        diagnostics=_diagnostics(actual_ratio=1.02),
        local_timezone=LOCAL_TIMEZONE,
    )

    assert decision.basis == "central"
    assert decision.reason == "actual_tracking_supports_central"
    assert decision.tracking_ratio == 1.02
    assert decision.adjusted_interval_count == 2
    assert snapshot.pv_energy_timeline is not None
    today, tomorrow = snapshot.pv_energy_timeline.intervals
    assert today.forecast_lower_energy_wh == today.forecast_central_energy_wh == 600.0
    assert tomorrow.forecast_lower_energy_wh == 350.0
    assert tomorrow.forecast_central_energy_wh == 500.0


def test_daily_observer_keeps_lower_when_actual_underperforms() -> None:
    original = _snapshot()
    snapshot, decision = apply_daily_measured_pv_basis(
        original,
        diagnostics=_diagnostics(actual_ratio=0.75),
        local_timezone=LOCAL_TIMEZONE,
    )

    assert snapshot != original
    assert decision.basis == "lower"
    assert decision.reason == "actual_tracking_below_midpoint"
    assert decision.adjusted_interval_count == 1
    assert snapshot.pv_energy_timeline is not None
    today, tomorrow = snapshot.pv_energy_timeline.intervals
    assert today.forecast_lower_energy_wh == 300.0
    assert tomorrow.forecast_lower_energy_wh == 350.0


def test_daily_observer_requires_sufficient_closed_actual_evidence() -> None:
    diagnostics = replace(
        _diagnostics(actual_ratio=1.1),
        actual_interval_count=3,
        closed_forecast_count=4,
    )

    snapshot, decision = apply_daily_measured_pv_basis(
        _snapshot(),
        diagnostics=diagnostics,
        local_timezone=LOCAL_TIMEZONE,
    )

    assert snapshot != _snapshot()
    assert decision.basis == "midpoint"
    assert decision.reason == "actual_coverage_incomplete"
    assert snapshot.pv_energy_timeline is not None
    today, tomorrow = snapshot.pv_energy_timeline.intervals
    assert today.forecast_lower_energy_wh == 450.0
    assert tomorrow.forecast_lower_energy_wh == 350.0


def test_daily_observer_uses_midpoint_before_actual_evidence_exists() -> None:
    snapshot, decision = apply_daily_measured_pv_basis(
        _snapshot(),
        diagnostics=None,
        local_timezone=LOCAL_TIMEZONE,
    )

    assert decision.basis == "midpoint"
    assert decision.reason == "actual_evidence_unavailable"
    assert snapshot.pv_energy_timeline is not None
    today, tomorrow = snapshot.pv_energy_timeline.intervals
    assert today.forecast_lower_energy_wh == 450.0
    assert tomorrow.forecast_lower_energy_wh == 350.0


def test_daily_observer_keeps_midpoint_when_actual_tracks_between_it_and_central() -> None:
    snapshot, decision = apply_daily_measured_pv_basis(
        _snapshot(),
        diagnostics=_diagnostics(actual_ratio=0.85),
        local_timezone=LOCAL_TIMEZONE,
    )

    assert decision.basis == "midpoint"
    assert decision.reason == "actual_tracking_supports_midpoint"
    assert snapshot.pv_energy_timeline is not None
    today, tomorrow = snapshot.pv_energy_timeline.intervals
    assert today.forecast_lower_energy_wh == 450.0
    assert tomorrow.forecast_lower_energy_wh == 350.0
