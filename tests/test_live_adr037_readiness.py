from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.addon.live_adr037_readiness import adr037_readiness_log_event
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.forecast import ForecastSet
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import PlanningInputSnapshot, PlanningInputVersions
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)

BASE = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
END = BASE + timedelta(hours=1)


def _snapshot() -> PlanningInputSnapshot:
    pv = PVEnergyTimeline(
        timeline_id="pv-live",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=END,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=BASE,
                ends_at=END,
                energy_wh=1000.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("solcast",),
            ),
        ),
    )
    load = HouseholdLoadForecast(
        forecast_id="load-live",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=END,
        intervals=(
            HouseholdLoadForecastInterval(
                starts_at=BASE,
                ends_at=END,
                expected_energy_wh=600.0,
                confidence=0.7,
            ),
        ),
        historical_source_reference="picot_history:last_14_days",
        method_version="weighted-quarter-hour-profile-v1",
    )
    storage = CurrentStorageState(
        storage_state_id="storage-live",
        execution_scope_id="storage-primary",
        capability_id="storage-primary-energy",
        current_soc=0.5,
        usable_capacity_wh=8000.0,
        measured_at=BASE,
        confidence=1.0,
        evidence_ids=("zendure",),
    )
    return PlanningInputSnapshot(
        snapshot_id="live-1",
        captured_at=BASE,
        horizon_end=END,
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="live",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=()),
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("live",),
        current_storage_states=(storage,),
        pv_energy_timeline=pv,
        household_load_forecast=load,
    )


def test_complete_energy_inputs_reach_projected_balance_but_not_fake_capability() -> None:
    event = adr037_readiness_log_event(_snapshot())

    assert event["projected_balance_available"] is True
    assert event["projected_balance_end_energy_wh"] == 4400.0
    assert event["projected_balance_confidence"] == 0.7
    assert event["adr037_pipeline_stage_reached"] == "projected_household_energy_balance"
    assert event["adr037_live_ready"] is False
    assert "live_storage_capability_snapshot_unavailable" in event["adr037_live_blockers"]
    assert event["control_change_allowed"] is False
    assert event["observer_only"] is True
