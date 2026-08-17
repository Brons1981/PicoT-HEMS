from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import (
    CurrentStorageState,
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PlanningInputSnapshot,
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
    StorageEnergyRequirement,
)

BASE = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
WINDOW_END = BASE + timedelta(hours=1)
REQUIRED_BY = BASE + timedelta(hours=2)
RUN_ID = "run-delegated-storage-test"
SNAPSHOT_ID = "snapshot-delegated-storage-test"
CAPABILITY_ID = "storage-capability-home-battery"
SCOPE_ID = "home-battery"


def _capability_set(
    *,
    primitive: ExecutionPrimitive = ExecutionPrimitive.BALANCE_CHARGE_ONLY,
    available: bool = True,
) -> CapabilitySnapshotSet:
    capability = LogicalCapabilitySnapshot(
        capability_id=CAPABILITY_ID,
        execution_scope_id=SCOPE_ID,
        supported_primitives=(primitive,) if available else (),
        availability=(
            CapabilityAvailability.AVAILABLE
            if available
            else CapabilityAvailability.UNAVAILABLE
        ),
        health=CapabilityHealth.HEALTHY if available else CapabilityHealth.INVALID,
        fresh_at=BASE,
        confidence=1.0 if available else 0.0,
        source_mapping_id="storage-mode-options:v1",
        adapter_contract_version="1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,) if available else (),
    )
    return CapabilitySnapshotSet(
        snapshot_id=SNAPSHOT_ID,
        mapping_version=1,
        captured_at=BASE,
        capabilities=(capability,),
    )


def _snapshot(capability_set: CapabilitySnapshotSet) -> PlanningInputSnapshot:
    storage = CurrentStorageState(
        storage_state_id="storage-home",
        execution_scope_id=SCOPE_ID,
        capability_id=CAPABILITY_ID,
        current_soc=0.125,
        usable_capacity_wh=8000.0,
        measured_at=BASE,
        confidence=0.9,
        evidence_ids=("storage-evidence",),
    )
    pv_intervals = (
        PVEnergyTimelineInterval(
            interval_id="pv-surplus-window",
            starts_at=BASE,
            ends_at=WINDOW_END,
            pv_energy_wh=800.0,
            evidence_type="FORECAST",
            confidence=0.8,
            actual_evidence_ids=(),
            forecast_evidence_ids=("pv-window-evidence",),
            conversion_method_version="forecast-energy:v1",
        ),
        PVEnergyTimelineInterval(
            interval_id="pv-after-window",
            starts_at=WINDOW_END,
            ends_at=REQUIRED_BY,
            pv_energy_wh=0.0,
            evidence_type="FORECAST",
            confidence=0.8,
            actual_evidence_ids=(),
            forecast_evidence_ids=("pv-after-evidence",),
            conversion_method_version="forecast-energy:v1",
        ),
    )
    load_intervals = (
        HouseholdLoadForecastInterval(
            interval_id="load-during-window",
            starts_at=BASE,
            ends_at=WINDOW_END,
            expected_energy_wh=200.0,
            confidence=0.7,
            source_reference="load-window-evidence",
            method_version="test-load:v1",
        ),
        HouseholdLoadForecastInterval(
            interval_id="load-after-window",
            starts_at=WINDOW_END,
            ends_at=REQUIRED_BY,
            expected_energy_wh=200.0,
            confidence=0.7,
            source_reference="load-after-evidence",
            method_version="test-load:v1",
        ),
    )
    return PlanningInputSnapshot(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        captured_at=BASE,
        picot_version="test",
        architecture_baseline_commit="test",
        pipeline_contract_version=1,
        strategy_id="strategy:test",
        horizon_end=REQUIRED_BY,
        current_storage_states=(storage,),
        pv_energy_timeline=PVEnergyTimeline(
            timeline_id="pv-timeline",
            run_id=RUN_ID,
            snapshot_id=SNAPSHOT_ID,
            intervals=pv_intervals,
        ),
        household_load_forecast=HouseholdLoadForecast(
            forecast_id="load-forecast",
            run_id=RUN_ID,
            snapshot_id=SNAPSHOT_ID,
            intervals=load_intervals,
            fallback_active=False,
            fallback_reason=None,
        ),
        capability_snapshot_set=capability_set,
    )


def _balance() -> ProjectedHouseholdEnergyBalance:
    return ProjectedHouseholdEnergyBalance(
        balance_id="projected-balance",
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        storage_state_id="storage-home",
        intervals=(
            ProjectedHouseholdEnergyBalanceInterval(
                starts_at=BASE,
                ends_at=WINDOW_END,
                current_usable_storage_energy_wh=1000.0,
                expected_usable_pv_energy_wh=800.0,
                planned_grid_energy_wh=0.0,
                household_load_forecast_energy_wh=200.0,
                known_future_demand_energy_wh=0.0,
                conversion_losses_wh=0.0,
                other_planned_household_energy_flows_wh=0.0,
                projected_storage_energy_wh=1600.0,
                confidence=0.7,
                evidence_ids=("pv-window-evidence", "load-window-evidence"),
            ),
            ProjectedHouseholdEnergyBalanceInterval(
                starts_at=WINDOW_END,
                ends_at=REQUIRED_BY,
                current_usable_storage_energy_wh=1600.0,
                expected_usable_pv_energy_wh=0.0,
                planned_grid_energy_wh=0.0,
                household_load_forecast_energy_wh=200.0,
                known_future_demand_energy_wh=0.0,
                conversion_losses_wh=0.0,
                other_planned_household_energy_flows_wh=0.0,
                projected_storage_energy_wh=1400.0,
                confidence=0.7,
                evidence_ids=("pv-after-evidence", "load-after-evidence"),
            ),
        ),
    )


def _requirement() -> StorageEnergyRequirement:
    return StorageEnergyRequirement(
        requirement_id="storage-requirement",
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        storage_state_id="storage-home",
        projected_balance_id="projected-balance",
        required_energy_wh=1200.0,
        required_soc=0.15,
        required_by=REQUIRED_BY,
        reason="household_requirement",
        confidence=0.7,
        evidence_ids=("storage-evidence", "load-after-evidence"),
        reserve_contribution_wh=200.0,
    )


def _construct(snapshot: PlanningInputSnapshot) -> object:
    module = import_module("picot.v2.delegated_storage_candidates")
    return module.construct_pv_charge_only_candidate(
        snapshot=snapshot,
        balance=_balance(),
        requirement=_requirement(),
    )


def test_pv_surplus_constructs_one_delegated_charge_only_candidate() -> None:
    candidate_set = _construct(_snapshot(_capability_set()))

    assert candidate_set.derivation_status == "constructed"
    assert len(candidate_set.candidates) == 1
    assert len(candidate_set.energy_paths) == 1
    candidate = candidate_set.candidates[0]
    path = candidate_set.energy_paths[0]
    assert candidate.energy_path_id == path.path_id
    assert candidate.family == "pv_charge_only"
    assert path.family == "pv_charge_only"
    assert len(path.segments) == 1
    segment = path.segments[0]
    assert segment.starts_at == BASE
    assert segment.ends_at == WINDOW_END
    assert segment.primitive is ExecutionPrimitive.BALANCE_CHARGE_ONLY
    assert segment.requested_power_w is None
    assert segment.charge_source_policy is ChargeSourcePolicy.PV_ONLY


def test_candidate_projects_window_end_and_later_requirement_energy() -> None:
    candidate_set = _construct(_snapshot(_capability_set()))

    states = candidate_set.energy_paths[0].projected_states
    assert [state.at for state in states] == [WINDOW_END, REQUIRED_BY]
    assert states[0].storage_energy_wh == pytest.approx(1400.0)
    assert states[1].storage_energy_wh == pytest.approx(1200.0)
    assert all(state.confidence == pytest.approx(0.7) for state in states)


def test_bidirectional_balance_capability_supports_pv_charge_alternative() -> None:
    candidate_set = _construct(
        _snapshot(
            _capability_set(
                primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
            )
        )
    )

    assert candidate_set.derivation_status == "constructed"
    assert candidate_set.derivation_reason is None
    assert len(candidate_set.candidates) == 1
    assert candidate_set.energy_paths[0].segments[0].primitive is (
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    )



def test_preferred_price_window_is_considered_before_expansion() -> None:
    module = import_module("picot.v2.delegated_storage_candidates")
    candidate_set = module.construct_pv_charge_only_candidate(
        snapshot=_snapshot(_capability_set()),
        balance=_balance(),
        requirement=_requirement(),
        preferred_price_windows=((BASE, WINDOW_END),),
    )

    assert candidate_set.derivation_status == "constructed"
    assert len(candidate_set.energy_paths) == 2
    assert [
        (segment.starts_at, segment.ends_at)
        for segment in candidate_set.energy_paths[0].segments
    ] == [(BASE, WINDOW_END)]
    assert [
        (segment.starts_at, segment.ends_at)
        for segment in candidate_set.energy_paths[1].segments
    ] == [
        (BASE, WINDOW_END),
        (WINDOW_END, REQUIRED_BY),
    ]


def test_progressive_full_horizon_reserves_every_nom_interval() -> None:
    module = import_module("picot.v2.delegated_storage_candidates")
    candidate_set = module.construct_pv_charge_only_candidate(
        snapshot=_snapshot(_capability_set()),
        balance=_balance(),
        requirement=_requirement(),
        preferred_price_windows=((BASE, WINDOW_END),),
    )

    full_horizon_path = candidate_set.energy_paths[1]
    assert full_horizon_path.segments[0].starts_at == BASE
    assert full_horizon_path.segments[-1].ends_at == REQUIRED_BY
    assert all(
        segment.charge_source_policy is ChargeSourcePolicy.PV_ONLY
        for segment in full_horizon_path.segments
    )
