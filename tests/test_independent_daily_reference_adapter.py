from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import (
    CurrentStorageState,
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PlanningInputSnapshot,
    PriceForecastPoint,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
    StoragePhysicalLimits,
)
from picot.v2.independent_daily_reference_adapter import (
    DailyReferenceInputError,
    IndependentDailyReferenceAdapter,
)

START = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
QUARTER = timedelta(minutes=15)


def _snapshot(
    *,
    complete_range: bool = True,
    capability_snapshot_id: str = "snapshot",
    maximum_soc: float = 1.0,
    current_soc: float = 0.5,
) -> PlanningInputSnapshot:
    storage = CurrentStorageState(
        storage_state_id="storage",
        execution_scope_id="battery",
        capability_id="battery-capability",
        current_soc=current_soc,
        usable_capacity_wh=8160.0,
        measured_at=START,
        confidence=1.0,
        evidence_ids=("storage-evidence",),
    )
    capability = LogicalCapabilitySnapshot(
        capability_id="battery-capability",
        execution_scope_id="battery",
        supported_primitives=(ExecutionPrimitive.BALANCE_BIDIRECTIONAL,),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=START,
        confidence=1.0,
        source_mapping_id="mapping",
        adapter_contract_version="test:v1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.BIDIRECTIONAL,),
        minimum_soc=0.1,
    )
    pv_intervals = tuple(
        PVEnergyTimelineInterval(
            interval_id=f"pv-{index}",
            starts_at=START + index * 2 * QUARTER,
            ends_at=START + (index + 1) * 2 * QUARTER,
            pv_energy_wh=1000.0 if index < 2 else 0.0,
            evidence_type="FORECAST",
            confidence=0.8,
            actual_evidence_ids=(),
            forecast_evidence_ids=(f"solcast-{index}",),
            conversion_method_version="solcast:v1",
            forecast_lower_energy_wh=(800.0 if index < 2 else 0.0)
            if complete_range
            else None,
            forecast_central_energy_wh=(1000.0 if index < 2 else 0.0)
            if complete_range
            else None,
            forecast_upper_energy_wh=(1200.0 if index < 2 else 0.0)
            if complete_range
            else None,
            forecast_range_status="available" if complete_range else "unavailable",
            forecast_range_source_fields=("p10", "p50", "p90") if complete_range else (),
            forecast_range_method_version="range:v1" if complete_range else None,
        )
        for index in range(48)
    )
    household_intervals = tuple(
        HouseholdLoadForecastInterval(
            interval_id=f"load-{index}",
            starts_at=START + index * QUARTER,
            ends_at=START + (index + 1) * QUARTER,
            expected_energy_wh=100.0,
            confidence=0.9,
            source_reference="history",
            method_version="household:v1",
        )
        for index in range(96)
    )
    return PlanningInputSnapshot(
        run_id="run",
        snapshot_id="snapshot",
        captured_at=START,
        picot_version="2.0.0-dev.140",
        architecture_baseline_commit="baseline",
        pipeline_contract_version=1,
        strategy_id="strategy",
        horizon_end=START + timedelta(hours=36),
        price_points=(
            PriceForecastPoint(
                point_id="price",
                starts_at=START,
                ends_at=START + timedelta(hours=24),
                value_eur_per_kwh=0.30,
                confidence=0.95,
                evidence_id="nordpool",
            ),
        ),
        current_storage_states=(storage,),
        pv_energy_timeline=PVEnergyTimeline(
            timeline_id="pv-timeline",
            run_id="run",
            snapshot_id="snapshot",
            intervals=pv_intervals,
        ),
        household_load_forecast=HouseholdLoadForecast(
            forecast_id="household",
            run_id="run",
            snapshot_id="snapshot",
            intervals=household_intervals,
            fallback_active=False,
            fallback_reason=None,
        ),
        capability_snapshot_set=CapabilitySnapshotSet(
            snapshot_id=capability_snapshot_id,
            mapping_version=1,
            captured_at=START,
            capabilities=(capability,),
        ),
        storage_physical_limits=(
            StoragePhysicalLimits(
                execution_scope_id="battery",
                capability_id="battery-capability",
                minimum_soc=0.1,
                maximum_soc=maximum_soc,
                maximum_charge_input_power_w=2400.0,
                maximum_discharge_output_power_w=2400.0,
                evidence_ids=("configured-limits",),
                method_version="test-limits:v1",
            ),
        ),
    )


def _conversion() -> StorageConversionModel:
    return StorageConversionModel(
        model_id="conversion",
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        evidence_ids=("conversion-evidence",),
        method_version="test:v1",
    )


def _tariffs(*, snapshot_id: str = "snapshot") -> DailyReferenceTariffSchedule:
    return DailyReferenceTariffSchedule(
        schedule_id="tariffs",
        snapshot_id=snapshot_id,
        horizon_start=START,
        horizon_end=START + timedelta(hours=24),
        intervals=tuple(
            DailyReferenceTariffInterval(
                starts_at=START + index * QUARTER,
                ends_at=START + (index + 1) * QUARTER,
                import_eur_per_kwh=0.25,
                export_eur_per_kwh=0.10,
                confidence=0.95,
                evidence_ids=(f"tariff-{index}",),
            )
            for index in range(96)
        ),
        method_version="test-tariff:v1",
    )


def test_adapter_builds_three_quarter_hour_trajectories_from_shared_snapshot() -> None:
    result = IndependentDailyReferenceAdapter().simulate(
        snapshot=_snapshot(),
        conversion_model=_conversion(),
    )

    assert result.snapshot_id == "snapshot"
    assert result.observer_only is True
    assert {item.scenario for item in result.trajectories} == set(PVScenario)
    totals = {
        item.scenario: sum(interval.usable_pv_wh for interval in item.intervals)
        for item in result.trajectories
    }
    assert totals == {
        PVScenario.LOWER: pytest.approx(1600.0),
        PVScenario.CENTRAL: pytest.approx(2000.0),
        PVScenario.UPPER: pytest.approx(2400.0),
    }
    assert all(len(item.intervals) == 96 for item in result.trajectories)
    assert all(
        item.horizon_end == START + timedelta(hours=24)
        for item in result.trajectories
    )


def test_adapter_rebins_off_quarter_household_input_to_market_quarters() -> None:
    snapshot = _snapshot()
    offset = timedelta(minutes=7, seconds=17)
    shifted = replace(
        snapshot.household_load_forecast,
        intervals=tuple(
            replace(
                item,
                starts_at=item.starts_at + offset,
                ends_at=item.ends_at + offset,
            )
            for item in snapshot.household_load_forecast.intervals
        ),
    )

    result = IndependentDailyReferenceAdapter._household(
        shifted,
        captured_at=START + offset,
        horizon_end=START + offset + timedelta(hours=24),
    )

    assert len(result.intervals) == 97
    assert result.intervals[0].starts_at == START + offset
    assert result.intervals[0].ends_at.minute % 15 == 0
    assert result.intervals[0].ends_at.second == 0
    assert result.intervals[-1].ends_at == START + offset + timedelta(hours=24)
    assert all(
        interval.starts_at.minute % 15 == 0
        and interval.starts_at.second == 0
        and interval.ends_at.minute % 15 == 0
        and interval.ends_at.second == 0
        for interval in result.intervals[1:-1]
    )
    assert sum(item.expected_energy_wh for item in result.intervals) == pytest.approx(
        sum(item.expected_energy_wh for item in shifted.intervals)
    )


def test_observer_waits_when_next_day_prices_do_not_cover_24_hours() -> None:
    snapshot = _snapshot(maximum_soc=0.7)
    short_price = replace(
        snapshot.price_points[0],
        ends_at=START + timedelta(hours=20),
    )

    with pytest.raises(
        ValueError,
        match="daily_tariff_price_coverage_incomplete",
    ):
        IndependentDailyReferenceAdapter().observe(
            snapshot=replace(snapshot, price_points=(short_price,)),
            conversion_model=_conversion(),
        )


def test_adapter_blocks_when_any_pv_uncertainty_range_is_missing() -> None:
    with pytest.raises(DailyReferenceInputError, match="pv_range_incomplete"):
        IndependentDailyReferenceAdapter().simulate(
            snapshot=_snapshot(complete_range=False),
            conversion_model=_conversion(),
        )


def test_adapter_blocks_without_separate_physical_limit_contract() -> None:
    snapshot = replace(_snapshot(), storage_physical_limits=())

    with pytest.raises(
        DailyReferenceInputError,
        match="daily_reference_physical_limits_missing",
    ):
        IndependentDailyReferenceAdapter().simulate(
            snapshot=snapshot,
            conversion_model=_conversion(),
        )


def test_adapter_runs_complete_observer_chain_from_one_shared_snapshot() -> None:
    result = IndependentDailyReferenceAdapter().observe(
        snapshot=_snapshot(maximum_soc=0.7),
        conversion_model=_conversion(),
        tariffs=_tariffs(),
    )

    assert result.snapshot_id == "snapshot"
    assert result.strategy_space.snapshot_id == "snapshot"
    assert result.observer_result.snapshot_id == "snapshot"
    assert result.observer_only is True
    assert result.selection_permitted is False
    assert result.commitment_permitted is False
    assert result.strategy_space.source_charge_window_set_id == (
        "daily-charge-windows:snapshot"
    )
    assert result.observer_result.best_observation_ids


def test_adapter_derives_tariffs_automatically_from_shared_snapshot() -> None:
    IndependentDailyReferenceAdapter().observe(
        snapshot=_snapshot(maximum_soc=0.7),
        conversion_model=_conversion(),
    )


def test_adapter_observes_baseline_when_storage_already_meets_target() -> None:
    result = IndependentDailyReferenceAdapter().observe(
        snapshot=_snapshot(current_soc=1.0),
        conversion_model=_conversion(),
    )

    assert result.strategy_space.charge_requirement_status == "not_required"
    assert len(result.strategy_space.schedules) == 1
    assert len(result.observer_result.evaluation.records) == 1

    strategy_results = result.observer_result.portfolio.strategy_results
    assert strategy_results
    assert all(item.run.financial.snapshot_id == "snapshot" for item in strategy_results)
    assert all(
        path.tariff_schedule_id == "daily-tariffs:snapshot"
        for item in strategy_results
        for path in item.run.financial.paths
    )


def test_complete_observer_chain_blocks_tariffs_from_another_snapshot() -> None:
    with pytest.raises(DailyReferenceInputError, match="tariff_lineage_mismatch"):
        IndependentDailyReferenceAdapter().observe(
            snapshot=_snapshot(maximum_soc=0.7),
            conversion_model=_conversion(),
            tariffs=_tariffs(snapshot_id="other-snapshot"),
        )


def test_shared_snapshot_contract_blocks_capability_data_from_another_snapshot() -> None:
    with pytest.raises(ValueError, match="lineage must match planning input"):
        _snapshot(capability_snapshot_id="other-snapshot")


def test_adapter_does_not_import_current_pipeline_selection_types() -> None:
    from picot.v2 import independent_daily_reference_adapter as adapter_module

    imported_names = set(vars(adapter_module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
