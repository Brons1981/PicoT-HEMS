from __future__ import annotations

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
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import (
    CurrentStorageState,
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
    PlanningInputSnapshot,
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
) -> PlanningInputSnapshot:
    storage = CurrentStorageState(
        storage_state_id="storage",
        execution_scope_id="battery",
        capability_id="battery-capability",
        current_soc=0.5,
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
        maximum_power_w=2400.0,
        minimum_soc=0.1,
        maximum_soc=1.0,
    )
    pv_intervals = tuple(
        PVEnergyTimelineInterval(
            interval_id=f"pv-{index}",
            starts_at=START + index * 2 * QUARTER,
            ends_at=START + (index + 1) * 2 * QUARTER,
            pv_energy_wh=1000.0,
            evidence_type="FORECAST",
            confidence=0.8,
            actual_evidence_ids=(),
            forecast_evidence_ids=(f"solcast-{index}",),
            conversion_method_version="solcast:v1",
            forecast_lower_energy_wh=800.0 if complete_range else None,
            forecast_central_energy_wh=1000.0 if complete_range else None,
            forecast_upper_energy_wh=1200.0 if complete_range else None,
            forecast_range_status="available" if complete_range else "unavailable",
            forecast_range_source_fields=("p10", "p50", "p90") if complete_range else (),
            forecast_range_method_version="range:v1" if complete_range else None,
        )
        for index in range(2)
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
        for index in range(4)
    )
    return PlanningInputSnapshot(
        run_id="run",
        snapshot_id="snapshot",
        captured_at=START,
        picot_version="2.0.0-dev.140",
        architecture_baseline_commit="baseline",
        pipeline_contract_version=1,
        strategy_id="strategy",
        horizon_end=START + 4 * QUARTER,
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
    )


def _conversion() -> StorageConversionModel:
    return StorageConversionModel(
        model_id="conversion",
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        evidence_ids=("conversion-evidence",),
        method_version="test:v1",
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
    assert all(len(item.intervals) == 4 for item in result.trajectories)


def test_adapter_blocks_when_any_pv_uncertainty_range_is_missing() -> None:
    with pytest.raises(DailyReferenceInputError, match="pv_range_incomplete"):
        IndependentDailyReferenceAdapter().simulate(
            snapshot=_snapshot(complete_range=False),
            conversion_model=_conversion(),
        )


def test_adapter_blocks_capability_data_from_another_snapshot() -> None:
    with pytest.raises(DailyReferenceInputError, match="capability_lineage_mismatch"):
        IndependentDailyReferenceAdapter().simulate(
            snapshot=_snapshot(capability_snapshot_id="other-snapshot"),
            conversion_model=_conversion(),
        )


def test_adapter_does_not_import_current_pipeline_selection_types() -> None:
    from picot.v2 import independent_daily_reference_adapter as adapter_module

    imported_names = set(vars(adapter_module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
