from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.domain.candidate import CandidateFamily
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.current_storage_state import CurrentStorageState
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
from picot.planner.candidate_energy_path_simulator import CandidateEnergyPathSimulator

BASE = datetime(2026, 8, 13, 11, 0, tzinfo=UTC)
Q1 = BASE + timedelta(minutes=15)
Q2 = BASE + timedelta(minutes=30)


def _storage() -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id="storage-1",
        execution_scope_id="storage-primary",
        capability_id="storage-primary-energy",
        current_soc=0.4,
        usable_capacity_wh=8000.0,
        measured_at=BASE,
        confidence=1.0,
        evidence_ids=("soc",),
    )


def _snapshot() -> PlanningInputSnapshot:
    pv = PVEnergyTimeline(
        timeline_id="pv-1",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=Q2,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=BASE,
                ends_at=Q1,
                energy_wh=750.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.9,
                evidence_ids=("pv:q1",),
            ),
            PVEnergyTimelineInterval(
                starts_at=Q1,
                ends_at=Q2,
                energy_wh=500.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.9,
                evidence_ids=("pv:q2",),
            ),
        ),
    )
    load = HouseholdLoadForecast(
        forecast_id="load-1",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=Q2,
        intervals=(
            HouseholdLoadForecastInterval(
                starts_at=BASE,
                ends_at=Q1,
                expected_energy_wh=250.0,
                confidence=0.8,
            ),
            HouseholdLoadForecastInterval(
                starts_at=Q1,
                ends_at=Q2,
                expected_energy_wh=250.0,
                confidence=0.8,
            ),
        ),
        historical_source_reference="history:test",
        method_version="load-v1",
    )
    return PlanningInputSnapshot(
        snapshot_id="snapshot-1",
        captured_at=BASE,
        horizon_end=Q2,
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="objective-map-v1",
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
        replan_reasons=("test",),
        current_storage_states=(_storage(),),
        pv_energy_timeline=pv,
        household_load_forecast=load,
    )


def _path(*, pv_first: bool) -> EnergyPath:
    segment = (
        PathSegment(
            segment_id="segment-1",
            order=1,
            execution_scope_id="storage-primary",
            starts_at=BASE,
            ends_at=Q2,
            primitive=ExecutionPrimitive.CHARGE_AT_POWER,
            capability_id="storage-primary-energy",
            purpose="Store expected PV surplus.",
            evidence_ids=("pv-surplus",),
            requested_power_w=2000.0,
            charge_source_policy=ChargeSourcePolicy.PV_ONLY,
        ),
    ) if pv_first else ()
    return EnergyPath(
        path_id="pv-first" if pv_first else "baseline",
        snapshot_id="snapshot-1",
        family=CandidateFamily.PV_FIRST if pv_first else CandidateFamily.RESERVE_FIRST,
        horizon_start=BASE,
        horizon_end=Q2,
        segments=segment,
        projected_states=(),
        opportunity_ids=(("pv-surplus",) if pv_first else ()),
        constraint_ids=(),
        capability_ids=(("storage-primary-energy",) if pv_first else ()),
        strategy_version=1,
        mapping_version=1,
        assumptions=("test",),
        confidence=0.9,
    )


def test_baseline_projects_surplus_as_export_without_storage_action() -> None:
    simulated = CandidateEnergyPathSimulator().simulate(
        path=_path(pv_first=False),
        snapshot=_snapshot(),
        storage_state=_storage(),
    )

    assert [state.household_export_w for state in simulated.projected_states] == [2000.0, 1000.0]
    assert [state.controllable_load_w for state in simulated.projected_states] == [0.0, 0.0]
    assert simulated.projected_states[-1].battery_soc == 0.4


def test_pv_first_stores_surplus_and_reduces_export() -> None:
    simulated = CandidateEnergyPathSimulator().simulate(
        path=_path(pv_first=True),
        snapshot=_snapshot(),
        storage_state=_storage(),
    )

    assert [state.controllable_load_w for state in simulated.projected_states] == [2000.0, 1000.0]
    assert [state.household_export_w for state in simulated.projected_states] == [0.0, 0.0]
    assert simulated.projected_states[-1].battery_soc == 0.49375
