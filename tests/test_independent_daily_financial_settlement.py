from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from test_independent_daily_simulator import _simulate

from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.planner.independent_daily_financial_settlement import (
    IndependentDailyFinancialSettlement,
)


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


def _split_tariffs() -> DailyReferenceTariffSchedule:
    simulation = _simulate()
    physical_intervals = simulation.trajectories[0].intervals
    return DailyReferenceTariffSchedule(
        schedule_id="split-tariffs",
        snapshot_id=simulation.snapshot_id,
        horizon_start=physical_intervals[0].starts_at,
        horizon_end=physical_intervals[-1].ends_at,
        intervals=tuple(
            tariff
            for index, physical in enumerate(physical_intervals)
            for tariff in (
                DailyReferenceTariffInterval(
                    starts_at=physical.starts_at,
                    ends_at=physical.starts_at + timedelta(minutes=15),
                    import_eur_per_kwh=0.20,
                    export_eur_per_kwh=0.10,
                    confidence=0.95,
                    evidence_ids=(f"split-tariff-{index}-a",),
                ),
                DailyReferenceTariffInterval(
                    starts_at=physical.starts_at + timedelta(minutes=15),
                    ends_at=physical.ends_at,
                    import_eur_per_kwh=0.40,
                    export_eur_per_kwh=0.20,
                    confidence=0.95,
                    evidence_ids=(f"split-tariff-{index}-b",),
                ),
            )
        ),
        method_version="split-test:v1",
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


def test_pv_storage_opportunity_cost_is_explanatory_not_double_charged() -> None:
    result = IndependentDailyFinancialSettlement().settle(
        simulation=_simulate(),
        tariffs=_tariffs(),
    )

    for path in result.paths:
        assert path.net_financial_result_eur == pytest.approx(
            path.grid_export_result_eur
            + path.avoided_import_value_eur
            - path.grid_import_cost_eur
        )


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

    with pytest.raises(ValueError, match="complete interval tariff coverage"):
        IndependentDailyFinancialSettlement().settle(
            simulation=_simulate(),
            tariffs=incomplete,
        )


def test_settlement_splits_physical_energy_at_tariff_boundaries() -> None:
    simulation = _simulate()
    weighted_tariffs = replace(
        _tariffs(),
        intervals=tuple(
            replace(
                tariff,
                import_eur_per_kwh=0.30,
                export_eur_per_kwh=0.15,
            )
            for tariff in _tariffs().intervals
        ),
    )

    split = IndependentDailyFinancialSettlement().settle(
        simulation=simulation,
        tariffs=_split_tariffs(),
    )
    weighted = IndependentDailyFinancialSettlement().settle(
        simulation=simulation,
        tariffs=weighted_tariffs,
    )

    assert all(len(path.intervals) == 18 for path in split.paths)
    for split_path, weighted_path in zip(
        split.paths,
        weighted.paths,
        strict=True,
    ):
        assert split_path.grid_import_cost_eur == pytest.approx(
            weighted_path.grid_import_cost_eur
        )
        assert split_path.grid_export_result_eur == pytest.approx(
            weighted_path.grid_export_result_eur
        )
        assert split_path.net_financial_result_eur == pytest.approx(
            weighted_path.net_financial_result_eur
        )


def test_financial_interval_rejects_non_positive_duration() -> None:
    result = IndependentDailyFinancialSettlement().settle(
        simulation=_simulate(),
        tariffs=_tariffs(),
    )
    interval = result.paths[0].intervals[0]

    with pytest.raises(ValueError, match="positive duration"):
        replace(interval, ends_at=interval.starts_at)


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


def test_2026_cross_quarter_energy_tax_credit_is_capped_by_grid_import() -> None:
    source = _simulate()
    trajectories = []
    for trajectory in source.trajectories:
        energy_wh = 1000.0
        intervals = []
        for index, interval in enumerate(trajectory.intervals):
            grid_input_wh = 1000.0 if index == 0 else 0.0
            storage_export_wh = 1200.0 if index == 1 else 0.0
            end_energy_wh = energy_wh + grid_input_wh - storage_export_wh
            intervals.append(replace(
                interval,
                household_demand_wh=0.0,
                usable_pv_wh=0.0,
                pv_to_household_wh=0.0,
                pv_to_storage_input_wh=0.0,
                pv_to_grid_wh=0.0,
                grid_to_household_wh=0.0,
                grid_to_storage_input_wh=grid_input_wh,
                storage_to_household_output_wh=0.0,
                storage_to_grid_output_wh=storage_export_wh,
                storage_charge_loss_wh=0.0,
                storage_discharge_loss_wh=0.0,
                storage_energy_at_start_wh=energy_wh,
                storage_energy_at_end_wh=end_energy_wh,
            ))
            energy_wh = end_energy_wh
        trajectories.append(replace(trajectory, intervals=tuple(intervals)))
    simulation = replace(source, trajectories=tuple(trajectories))
    tariffs = replace(
        _tariffs(),
        intervals=tuple(
            replace(
                tariff,
                import_eur_per_kwh=0.10,
                export_eur_per_kwh=0.41,
                same_interval_offset_eur_per_kwh=0.10,
                cross_interval_export_eur_per_kwh=0.30,
                saldering_tax_eur_per_kwh=0.11,
            )
            for tariff in _tariffs().intervals
        ),
    )

    result = IndependentDailyFinancialSettlement().settle(
        simulation=simulation,
        tariffs=tariffs,
    )

    for path in result.paths:
        # 1.2 kWh export receives bare price + addition; only the 1.0 kWh
        # proven grid import receives the energy-tax saldering credit.
        assert path.grid_import_cost_eur == pytest.approx(0.10)
        assert path.grid_export_result_eur == pytest.approx(1.2 * 0.30 + 1.0 * 0.11)
        assert path.net_financial_result_eur == pytest.approx(0.37)
