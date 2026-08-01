from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries, ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import OpportunityKind, OpportunityMetricKind
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.planner.opportunity_engine import OpportunityEngine

BASE = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def _point(hour: int, value: float, confidence: float = 0.9) -> ForecastPoint:
    return ForecastPoint(
        starts_at=BASE + timedelta(hours=hour),
        ends_at=BASE + timedelta(hours=hour + 1),
        value=value,
        confidence=confidence,
    )


def _series(
    forecast_id: str,
    kind: ForecastKind,
    points: tuple[ForecastPoint, ...],
    *,
    unit: str = "W",
) -> ForecastSeries:
    return ForecastSeries(
        forecast_id=forecast_id,
        kind=kind,
        source=f"source-{forecast_id}",
        created_at=BASE - timedelta(minutes=5),
        expires_at=BASE + timedelta(hours=6),
        unit=unit,
        points=points,
    )


def _snapshot(pv: ForecastSeries, load: ForecastSeries) -> PlanningInputSnapshot:
    return PlanningInputSnapshot(
        snapshot_id="snapshot-pv-surplus-1",
        captured_at=BASE,
        horizon_end=BASE + timedelta(hours=4),
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="objective-map-v1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=(pv, load)),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("forecast_changed",),
    )


def test_engine_detects_and_merges_contiguous_pv_surplus_points() -> None:
    pv = _series(
        "pv-v1",
        ForecastKind.PV_POWER,
        (_point(0, 1200.0), _point(1, 4200.0, 0.95), _point(2, 3000.0, 0.85)),
    )
    load = _series(
        "load-v1",
        ForecastKind.HOUSEHOLD_LOAD,
        (_point(0, 1500.0), _point(1, 1400.0, 0.90), _point(2, 1800.0, 0.80)),
    )

    result = OpportunityEngine().detect(_snapshot(pv, load))

    assert len(result.opportunities) == 1
    opportunity = result.opportunities[0]
    assert opportunity.kind is OpportunityKind.PV_SURPLUS_WINDOW
    assert opportunity.starts_at == BASE + timedelta(hours=1)
    assert opportunity.ends_at == BASE + timedelta(hours=3)
    assert opportunity.confidence == 0.80
    assert opportunity.evidence[0].source_id == "pv-v1"
    assert opportunity.evidence[0].point_indexes == (1, 2)
    assert opportunity.evidence[1].source_id == "load-v1"
    assert opportunity.evidence[1].point_indexes == (1, 2)
    assert opportunity.metrics[0].kind is OpportunityMetricKind.MINIMUM_EXPECTED_POWER_W
    assert opportunity.metrics[0].value == 1200.0


def test_engine_returns_no_pv_surplus_when_load_exceeds_generation() -> None:
    pv = _series("pv-v1", ForecastKind.PV_POWER, (_point(0, 1000.0),))
    load = _series("load-v1", ForecastKind.HOUSEHOLD_LOAD, (_point(0, 1500.0),))

    result = OpportunityEngine().detect(_snapshot(pv, load))

    assert result.opportunities == ()


def test_engine_ignores_pv_surplus_series_with_non_power_units() -> None:
    pv = _series("pv-v1", ForecastKind.PV_POWER, (_point(0, 4.0),), unit="kW")
    load = _series("load-v1", ForecastKind.HOUSEHOLD_LOAD, (_point(0, 1.0),), unit="kW")

    result = OpportunityEngine().detect(_snapshot(pv, load))

    assert result.opportunities == ()
