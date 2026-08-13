from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.candidate import CandidateFamily
from picot.domain.energy_path import EnergyPath, ProjectedEnergyState
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries, ForecastSet
from picot.domain.objectives import ObjectiveKind
from picot.planner.financial_candidate_outcome import FinancialCandidateOutcomeDeriver

BASE = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)


def _path() -> EnergyPath:
    return EnergyPath(
        path_id="path-financial",
        snapshot_id="snapshot-financial",
        family=CandidateFamily.PV_FIRST,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(minutes=30),
        segments=(),
        projected_states=(
            ProjectedEnergyState(
                at=BASE + timedelta(minutes=15),
                confidence=0.9,
                household_import_w=1000.0,
                household_export_w=0.0,
            ),
            ProjectedEnergyState(
                at=BASE + timedelta(minutes=30),
                confidence=0.8,
                household_import_w=0.0,
                household_export_w=2000.0,
            ),
        ),
        opportunity_ids=(),
        constraint_ids=(),
        capability_ids=(),
        strategy_version=1,
        mapping_version=1,
        assumptions=("financial test",),
        confidence=0.9,
    )


def _series(kind: ForecastKind, values: tuple[float, float]) -> ForecastSeries:
    return ForecastSeries(
        forecast_id=f"{kind.value}-forecast",
        kind=kind,
        source=f"test-{kind.value}",
        created_at=BASE,
        expires_at=BASE + timedelta(minutes=30),
        unit="EUR/kWh",
        points=(
            ForecastPoint(
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=15),
                value=values[0],
                confidence=1.0,
            ),
            ForecastPoint(
                starts_at=BASE + timedelta(minutes=15),
                ends_at=BASE + timedelta(minutes=30),
                value=values[1],
                confidence=0.95,
            ),
        ),
    )


def test_financial_result_accounts_for_import_cost_and_export_revenue() -> None:
    forecasts = ForecastSet(
        series=(
            _series(ForecastKind.ENERGY_PRICE, (0.20, 0.10)),
            _series(ForecastKind.GRID_EXPORT_PRICE, (0.08, 0.12)),
        )
    )

    result = FinancialCandidateOutcomeDeriver().derive(path=_path(), forecasts=forecasts)

    assert result is not None
    assert result.objective is ObjectiveKind.FINANCIAL_RESULT
    assert result.unit == "EUR"
    assert result.value == pytest.approx((0.25 * 0.20) - (0.50 * 0.12))
    assert result.confidence == pytest.approx(0.8)


def test_financial_result_is_unavailable_without_explicit_export_settlement() -> None:
    forecasts = ForecastSet(series=(_series(ForecastKind.ENERGY_PRICE, (0.20, 0.10)),))

    result = FinancialCandidateOutcomeDeriver().derive(path=_path(), forecasts=forecasts)

    assert result is None


def test_financial_result_is_unavailable_when_settlement_coverage_is_incomplete() -> None:
    import_forecast = _series(ForecastKind.ENERGY_PRICE, (0.20, 0.10))
    export_forecast = ForecastSeries(
        forecast_id="export-short",
        kind=ForecastKind.GRID_EXPORT_PRICE,
        source="test-export",
        created_at=BASE,
        expires_at=BASE + timedelta(minutes=15),
        unit="EUR/kWh",
        points=(
            ForecastPoint(
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=15),
                value=0.08,
                confidence=1.0,
            ),
        ),
    )

    result = FinancialCandidateOutcomeDeriver().derive(
        path=_path(),
        forecasts=ForecastSet(series=(import_forecast, export_forecast)),
    )

    assert result is None
