from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.domain.forecast import ForecastSet
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import OpportunityKind, OpportunityMetricKind
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
from picot.planner.opportunity_engine import OpportunityEngine

BASE = datetime(2026, 8, 13, 10, 45, tzinfo=UTC)


def _snapshot() -> PlanningInputSnapshot:
    first_end = BASE + timedelta(minutes=15)
    second_end = BASE + timedelta(minutes=30)
    pv = PVEnergyTimeline(
        timeline_id="live-pv-1",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=second_end,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=BASE,
                ends_at=first_end,
                energy_wh=750.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.9,
                evidence_ids=("pv:1",),
            ),
            PVEnergyTimelineInterval(
                starts_at=first_end,
                ends_at=second_end,
                energy_wh=625.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("pv:2",),
            ),
        ),
    )
    load = HouseholdLoadForecast(
        forecast_id="live-load-1",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=second_end,
        intervals=(
            HouseholdLoadForecastInterval(
                starts_at=BASE,
                ends_at=first_end,
                expected_energy_wh=125.0,
                confidence=0.85,
            ),
            HouseholdLoadForecastInterval(
                starts_at=first_end,
                ends_at=second_end,
                expected_energy_wh=175.0,
                confidence=0.75,
            ),
        ),
        historical_source_reference="history:test",
        method_version="load-test-v1",
    )
    return PlanningInputSnapshot(
        snapshot_id="live-snapshot-pv-surplus",
        captured_at=BASE,
        horizon_end=second_end,
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="live-test-v1",
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
        replan_reasons=("live_observation",),
        pv_energy_timeline=pv,
        household_load_forecast=load,
    )


def test_opportunity_engine_uses_canonical_live_pv_and_load_energy_inputs() -> None:
    result = OpportunityEngine().detect(_snapshot())

    assert len(result.opportunities) == 1
    opportunity = result.opportunities[0]
    assert opportunity.kind is OpportunityKind.PV_SURPLUS_WINDOW
    assert opportunity.starts_at == BASE
    assert opportunity.ends_at == BASE + timedelta(minutes=30)
    assert opportunity.evidence[0].source_id == "live-pv-1"
    assert opportunity.evidence[0].point_indexes == (0, 1)
    assert opportunity.evidence[1].source_id == "live-load-1"
    assert opportunity.evidence[1].point_indexes == (0, 1)
    assert opportunity.metrics[0].kind is OpportunityMetricKind.MINIMUM_EXPECTED_POWER_W
    # quarter 1: (750-125) Wh / 0.25h = 2500 W
    # quarter 2: (625-175) Wh / 0.25h = 1800 W
    assert opportunity.metrics[0].value == 1800.0
