from __future__ import annotations

from dataclasses import replace

import pytest

from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.planner.independent_daily_financial_settlement import (
    IndependentDailyFinancialSettlement,
)
from test_independent_daily_simulator import _simulate


def _tariffs(snapshot_id: str = "snapshot-incident") -> DailyReferenceTariffSchedule:
    simulation = _simulate()
    intervals = simulation.trajectories[0].intervals
    return DailyReferenceTariffSchedule(
        schedule_id="tariffs",
        snapshot_id=snapshot_id,
        horizon_start=intervals[0].starts_at,
        horizon_end=intervals[-1].ends_at,
        intervals=tuple(
            DailyReferenceTariffInterval(
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                import_eur_per_kwh=0.20 + index * 0.01,
                export_eur_per_kwh=0.10 + index * 0.005,
                confidence=0.95,
                evidence_ids=(f"tariff-{index}",),
            )
            for index, item in enumerate(intervals)
        ),
        method_version="test:v1",
    )


def test_settlement_values_all_paths_without_ranking() -> None:
    result = IndependentDailyFinancialSettlement().settle(
        simulation=_simulate(),
        tariffs=_tariffs(),
    )

    assert result.observer_only is True
    assert result.selection_permitted is False
    assert len(result.paths) == 3
    assert all(len(item.intervals) == 9 for item in result.paths)
    assert all(item.pv_storage_opportunity_cost_eur > 0.0 for item in result.paths)
    assert all(item.evidence_ids for item in result.paths)


def test_average_prices_are_duration_weighted_and_traceable() -> None:
    result = IndependentDailyFinancialSettlement().settle(
        simulation=_simulate(),
        tariffs=_tariffs(),
    )

    for path in result.paths:
        assert path.average_import_eur_per_kwh == pytest.approx(0.24)
        assert path.average_export_eur_per_kwh == pytest.approx(0.12)
        assert path.confidence == pytest.approx(0.422)


def test_settlement_fails_closed_for_an_interval_without_tariff() -> None:
    tariffs = _tariffs()
    incomplete = replace(tariffs)
    object.__setattr__(incomplete, "intervals", tariffs.intervals[:-1])

    with pytest.raises(ValueError, match="exact interval tariff"):
        IndependentDailyFinancialSettlement().settle(
            simulation=_simulate(),
            tariffs=incomplete,
        )


def test_settlement_fails_closed_for_different_snapshot() -> None:
    with pytest.raises(ValueError, match="snapshots must match"):
        IndependentDailyFinancialSettlement().settle(
            simulation=_simulate(),
            tariffs=_tariffs(snapshot_id="other-snapshot"),
        )


def test_settlement_does_not_import_current_evaluation_or_commitment() -> None:
    from picot.planner import independent_daily_financial_settlement as module

    imported_names = set(vars(module))
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
