from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.candidate import CandidateFamily
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.energy_contract import EnergyContractSnapshot, EnergyTariffInterval
from picot.domain.energy_path import EnergyPath, PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastSet
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.canonical_household_energy_simulator import (
    CanonicalHouseholdEnergySimulator,
)

BASE = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
END = BASE + timedelta(minutes=15)


def _storage() -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id="storage-state-1",
        execution_scope_id="battery-main",
        capability_id="storage-capability-1",
        current_soc=0.50,
        usable_capacity_wh=8000.0,
        measured_at=BASE,
        confidence=0.95,
        evidence_ids=("soc:1",),
    )


def _snapshot(*, pv_wh: float, load_wh: float) -> PlanningInputSnapshot:
    pv = PVEnergyTimeline(
        timeline_id="pv-timeline-1",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=END,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=BASE,
                ends_at=END,
                energy_wh=pv_wh,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.85,
                evidence_ids=("pv:q1",),
            ),
        ),
    )
    load = HouseholdLoadForecast(
        forecast_id="load-forecast-1",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=END,
        intervals=(
            HouseholdLoadForecastInterval(
                starts_at=BASE,
                ends_at=END,
                expected_energy_wh=load_wh,
                confidence=0.90,
            ),
        ),
        historical_source_reference="history:comparable-days",
        method_version="load-forecast:v1",
    )
    return PlanningInputSnapshot(
        snapshot_id="snapshot-1",
        captured_at=BASE,
        horizon_end=END,
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="objective-map:v1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=()),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("reference-simulation",),
        current_storage_states=(_storage(),),
        pv_energy_timeline=pv,
        household_load_forecast=load,
    )


def _contract(*, permits_import: bool = True) -> EnergyContractSnapshot:
    tariff = EnergyTariffInterval.basic(
        starts_at=BASE,
        ends_at=END,
        import_eur_per_kwh=0.25,
        export_eur_per_kwh=0.10,
        evidence_ids=("tariff:q1",),
    )
    return EnergyContractSnapshot(
        contract_snapshot_id="energy-contract-1",
        captured_at=BASE,
        valid_from=BASE,
        valid_until=END,
        settlement_timezone="Europe/Amsterdam",
        settlement_rule_id="dynamic-quarter-hour:v1",
        contract_version="contract:v1",
        permits_grid_import=permits_import,
        permits_grid_export=True,
        permits_battery_export=False,
        intervals=(tariff,),
    )


def _path(
    *,
    policy: ChargeSourcePolicy | None = None,
    requested_power_w: float = 2000.0,
) -> EnergyPath:
    segments: tuple[PathSegment, ...] = ()
    capability_ids: tuple[str, ...] = ()
    if policy is not None:
        segments = (
            PathSegment(
                segment_id="charge-segment-1",
                order=1,
                execution_scope_id="battery-main",
                starts_at=BASE,
                ends_at=END,
                primitive=ExecutionPrimitive.CHARGE_AT_POWER,
                capability_id="storage-capability-1",
                purpose="Acquire required storage energy.",
                evidence_ids=("requirement:1",),
                requested_power_w=requested_power_w,
                charge_source_policy=policy,
            ),
        )
        capability_ids = ("storage-capability-1",)
    return EnergyPath(
        path_id="energy-path-1",
        snapshot_id="snapshot-1",
        family=(CandidateFamily.COST_FIRST if policy else CandidateFamily.RESERVE_FIRST),
        horizon_start=BASE,
        horizon_end=END,
        segments=segments,
        projected_states=(),
        opportunity_ids=(),
        constraint_ids=(),
        capability_ids=capability_ids,
        strategy_version=1,
        mapping_version=1,
        assumptions=("reference scenario",),
        confidence=0.88,
    )


def _simulate(
    *,
    pv_wh: float,
    load_wh: float,
    policy: ChargeSourcePolicy | None = None,
    permits_import: bool = True,
    requested_power_w: float = 2000.0,
    requirement_target_energy_wh: float | None = None,
):
    if (
        requirement_target_energy_wh is None
        and policy is ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT
    ):
        requirement_target_energy_wh = 4450.0
    return CanonicalHouseholdEnergySimulator().simulate(
        run_id="run-1",
        candidate_id="candidate-1",
        path=_path(policy=policy, requested_power_w=requested_power_w),
        snapshot=_snapshot(pv_wh=pv_wh, load_wh=load_wh),
        storage_state=_storage(),
        conversion_model=StorageConversionModel(
            model_id="storage-conversion-1",
            charge_efficiency=0.90,
            discharge_efficiency=0.90,
            evidence_ids=("manufacturer:efficiency",),
            method_version="fixed-directional-efficiency:v1",
        ),
        energy_contract=_contract(permits_import=permits_import),
        requirement_target_energy_wh=requirement_target_energy_wh,
    )


def test_baseline_uses_pv_for_household_and_exports_only_the_surplus() -> None:
    ledger = _simulate(pv_wh=500.0, load_wh=300.0)
    interval = ledger.intervals[0]

    assert interval.pv_to_household_wh == pytest.approx(300.0)
    assert interval.pv_to_grid_wh == pytest.approx(200.0)
    assert interval.grid_import_wh == pytest.approx(0.0)
    assert interval.storage_energy_at_end_wh == pytest.approx(4000.0)


def test_baseline_imports_only_the_household_shortfall() -> None:
    ledger = _simulate(pv_wh=100.0, load_wh=300.0)
    interval = ledger.intervals[0]

    assert interval.pv_to_household_wh == pytest.approx(100.0)
    assert interval.grid_to_household_wh == pytest.approx(200.0)
    assert interval.grid_to_storage_input_wh == pytest.approx(0.0)


def test_pv_only_charging_applies_loss_once_and_never_imports_for_storage() -> None:
    ledger = _simulate(
        pv_wh=1000.0,
        load_wh=200.0,
        policy=ChargeSourcePolicy.PV_ONLY,
    )
    interval = ledger.intervals[0]

    assert interval.pv_to_storage_input_wh == pytest.approx(500.0)
    assert interval.grid_to_storage_input_wh == pytest.approx(0.0)
    assert interval.storage_charge_loss_wh == pytest.approx(50.0)
    assert interval.storage_energy_at_end_wh == pytest.approx(4450.0)
    assert interval.pv_to_grid_wh == pytest.approx(300.0)


def test_requirement_grid_charging_uses_pv_surplus_before_grid_energy() -> None:
    ledger = _simulate(
        pv_wh=300.0,
        load_wh=200.0,
        policy=ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT,
    )
    interval = ledger.intervals[0]

    assert interval.pv_to_storage_input_wh == pytest.approx(100.0)
    assert interval.grid_to_storage_input_wh == pytest.approx(400.0)
    assert interval.storage_charge_loss_wh == pytest.approx(50.0)
    assert interval.storage_energy_at_end_wh == pytest.approx(4450.0)


def test_requirement_grid_charging_fails_closed_without_import_permission() -> None:
    with pytest.raises(ValueError, match="does not permit required grid charging"):
        _simulate(
            pv_wh=300.0,
            load_wh=200.0,
            policy=ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT,
            permits_import=False,
        )


def test_requirement_grid_charging_is_bounded_by_named_energy_target() -> None:
    ledger = _simulate(
        pv_wh=300.0,
        load_wh=200.0,
        policy=ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT,
        requested_power_w=4000.0,
        requirement_target_energy_wh=4270.0,
    )
    interval = ledger.intervals[0]

    assert interval.storage_charge_input_wh == pytest.approx(300.0)
    assert interval.storage_charge_loss_wh == pytest.approx(30.0)
    assert interval.storage_energy_at_end_wh == pytest.approx(4270.0)


def test_market_charging_is_not_silently_supported_by_first_reference_slice() -> None:
    with pytest.raises(ValueError, match="market-cycle simulation is not implemented"):
        _simulate(
            pv_wh=300.0,
            load_wh=200.0,
            policy=ChargeSourcePolicy.GRID_ALLOWED_FOR_MARKET_ACTION,
        )


def test_requested_power_is_applied_per_canonical_interval() -> None:
    second_end = END + timedelta(minutes=15)
    snapshot = _snapshot(pv_wh=1000.0, load_wh=0.0)
    assert snapshot.pv_energy_timeline is not None
    assert snapshot.household_load_forecast is not None
    snapshot = replace(
        snapshot,
        horizon_end=second_end,
        pv_energy_timeline=replace(
            snapshot.pv_energy_timeline,
            horizon_end=second_end,
            intervals=(
                snapshot.pv_energy_timeline.intervals[0],
                replace(
                    snapshot.pv_energy_timeline.intervals[0],
                    starts_at=END,
                    ends_at=second_end,
                    evidence_ids=("pv:q2",),
                ),
            ),
        ),
        household_load_forecast=replace(
            snapshot.household_load_forecast,
            horizon_end=second_end,
            intervals=(
                snapshot.household_load_forecast.intervals[0],
                replace(
                    snapshot.household_load_forecast.intervals[0],
                    starts_at=END,
                    ends_at=second_end,
                ),
            ),
        ),
    )
    path = _path(policy=ChargeSourcePolicy.PV_ONLY)
    path = replace(
        path,
        horizon_end=second_end,
        segments=(replace(path.segments[0], ends_at=second_end),),
    )
    first_tariff = _contract().intervals[0]
    contract = replace(
        _contract(),
        valid_until=second_end,
        intervals=(
            first_tariff,
            replace(
                first_tariff,
                starts_at=END,
                ends_at=second_end,
                evidence_ids=("tariff:q2",),
            ),
        ),
    )

    ledger = CanonicalHouseholdEnergySimulator().simulate(
        run_id="run-1",
        candidate_id="candidate-1",
        path=path,
        snapshot=snapshot,
        storage_state=_storage(),
        conversion_model=StorageConversionModel(
            model_id="storage-conversion-1",
            charge_efficiency=0.90,
            discharge_efficiency=0.90,
            evidence_ids=("manufacturer:efficiency",),
            method_version="fixed-directional-efficiency:v1",
        ),
        energy_contract=contract,
        requirement_target_energy_wh=None,
    )

    assert [item.storage_charge_input_wh for item in ledger.intervals] == pytest.approx(
        [500.0, 500.0]
    )
