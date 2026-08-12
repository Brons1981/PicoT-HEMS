from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.addon.live_adr037_readiness import detect_live_price_opportunities
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries, ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import OpportunityKind
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)

BASE = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)


def _snapshot(*, include_price: bool = True) -> PlanningInputSnapshot:
    forecast = ForecastSeries(
        forecast_id="live-price",
        kind=ForecastKind.ENERGY_PRICE,
        source="sensor.nordpool",
        created_at=BASE,
        expires_at=BASE + timedelta(hours=1),
        unit="EUR/kWh",
        points=(
            ForecastPoint(
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=15),
                value=0.20,
                confidence=1.0,
            ),
            ForecastPoint(
                starts_at=BASE + timedelta(minutes=15),
                ends_at=BASE + timedelta(minutes=30),
                value=0.10,
                confidence=1.0,
            ),
            ForecastPoint(
                starts_at=BASE + timedelta(minutes=30),
                ends_at=BASE + timedelta(minutes=45),
                value=0.11,
                confidence=1.0,
            ),
            ForecastPoint(
                starts_at=BASE + timedelta(minutes=45),
                ends_at=BASE + timedelta(hours=1),
                value=0.21,
                confidence=1.0,
            ),
        ),
    )
    return PlanningInputSnapshot(
        snapshot_id="live-price-snapshot",
        captured_at=BASE,
        horizon_end=BASE + timedelta(hours=1),
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="live",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=((forecast,) if include_price else ())),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("live",),
    )


def test_live_opportunities_resolve_to_same_snapshot_price_evidence() -> None:
    result = detect_live_price_opportunities(
        _snapshot(),
        price_margin_eur_per_kwh=0.04,
    )

    assert result is not None
    assert result.snapshot_id == "live-price-snapshot"
    low = next(
        item
        for item in result.opportunities
        if item.kind is OpportunityKind.LOWEST_PRICE_WINDOW
    )
    assert low.snapshot_id == "live-price-snapshot"
    assert low.evidence[0].source_id == "live-price"
    assert low.evidence[0].point_indexes


def test_missing_live_price_forecast_fails_closed() -> None:
    result = detect_live_price_opportunities(
        _snapshot(include_price=False),
        price_margin_eur_per_kwh=0.04,
    )

    assert result is None
