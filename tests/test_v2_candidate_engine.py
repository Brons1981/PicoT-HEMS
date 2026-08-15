from datetime import UTC, datetime, timedelta

import pytest

from picot.v2 import (
    ARCHITECTURE_BASELINE_COMMIT,
    PIPELINE_CONTRACT_VERSION,
    __version__,
)
from picot.v2.candidate_engine import CandidateEngine
from picot.v2.contracts import (
    CurrentStorageState,
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PlanningInputSnapshot,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)

BASE = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)
HORIZON_END = BASE + timedelta(hours=1)


def test_candidate_engine_derives_conservative_storage_requirement() -> None:
    storage = CurrentStorageState(
        storage_state_id="storage-home",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home",
        current_soc=0.50,
        usable_capacity_wh=8000.0,
        measured_at=BASE,
        confidence=0.90,
        evidence_ids=("storage-evidence",),
    )
    pv_timeline = PVEnergyTimeline(
        timeline_id="pv-timeline",
        run_id="run-1",
        snapshot_id="snapshot-1",
        intervals=(
            PVEnergyTimelineInterval(
                interval_id="pv-interval",
                starts_at=BASE,
                ends_at=HORIZON_END,
                pv_energy_wh=1000.0,
                evidence_type="FORECAST",
                confidence=0.80,
                actual_evidence_ids=(),
                forecast_evidence_ids=("pv-evidence",),
                conversion_method_version="forecast-energy:v1",
            ),
        ),
    )
    load_forecast = HouseholdLoadForecast(
        forecast_id="load-forecast",
        run_id="run-1",
        snapshot_id="snapshot-1",
        intervals=(
            HouseholdLoadForecastInterval(
                interval_id="load-interval",
                starts_at=BASE,
                ends_at=HORIZON_END,
                expected_energy_wh=1500.0,
                confidence=0.70,
                source_reference="load:forecast",
                method_version="deterministic-test:v1",
            ),
        ),
        fallback_active=False,
        fallback_reason=None,
    )
    snapshot = PlanningInputSnapshot(
        run_id="run-1",
        snapshot_id="snapshot-1",
        captured_at=BASE,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:test",
        horizon_end=HORIZON_END,
        current_storage_states=(storage,),
        pv_energy_timeline=pv_timeline,
        household_load_forecast=load_forecast,
    )

    result = CandidateEngine().derive_storage_requirements(snapshot)

    assert len(result.balances) == 1
    assert len(result.requirements) == 1

    balance = result.balances[0]
    interval = balance.intervals[0]
    requirement = result.requirements[0]

    assert interval.current_usable_storage_energy_wh == pytest.approx(4000.0)
    assert interval.expected_usable_pv_energy_wh == pytest.approx(1000.0)
    assert interval.household_load_forecast_energy_wh == pytest.approx(1500.0)
    assert interval.projected_storage_energy_wh == pytest.approx(3500.0)
    assert interval.confidence == pytest.approx(0.70)

    assert requirement.projected_balance_id == balance.balance_id
    assert requirement.required_energy_wh == pytest.approx(8000.0)
    assert requirement.required_soc == pytest.approx(1.0)
    assert requirement.required_by == HORIZON_END
    assert requirement.reason == "conservative_effective_maximum"
    assert requirement.confidence == pytest.approx(0.70)
    assert requirement.reserve_contribution_wh == pytest.approx(4500.0)
    assert set(requirement.evidence_ids) == {
        "storage-evidence",
        "pv-evidence",
        "load:forecast",
    }
