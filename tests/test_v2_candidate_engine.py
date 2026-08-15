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
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project

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

    pipeline_run = CanonicalPipeline().run(
        planning_input=snapshot,
    )

    assert (
        pipeline_run.candidate_set.projected_balances
        == result.balances
    )
    assert (
        pipeline_run.candidate_set.storage_requirements
        == result.requirements
    )

    candidate_card = project(pipeline_run).cards[2]

    assert candidate_card.attributes["projected_balance_count"] == 1
    assert candidate_card.attributes["storage_requirement_count"] == 1
    assert candidate_card.attributes["storage_requirements"] == [
        {
            "required_energy_wh": 8000.0,
            "required_soc": 1.0,
            "required_by": HORIZON_END.isoformat(),
            "reason": "conservative_effective_maximum",
            "confidence": 0.70,
            "reserve_contribution_wh": 4500.0,
        }
    ]


def test_candidate_engine_aggregates_quarter_hour_load_for_half_hour_pv() -> None:
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
                interval_id="pv-half-hour",
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=30),
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
                interval_id="load-quarter-1",
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=15),
                expected_energy_wh=750.0,
                confidence=0.70,
                source_reference="load:quarter-1",
                method_version="deterministic-test:v1",
            ),
            HouseholdLoadForecastInterval(
                interval_id="load-quarter-2",
                starts_at=BASE + timedelta(minutes=15),
                ends_at=BASE + timedelta(minutes=30),
                expected_energy_wh=750.0,
                confidence=0.75,
                source_reference="load:quarter-2",
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
        horizon_end=BASE + timedelta(minutes=30),
        current_storage_states=(storage,),
        pv_energy_timeline=pv_timeline,
        household_load_forecast=load_forecast,
    )

    result = CandidateEngine().derive_storage_requirements(snapshot)

    assert len(result.balances) == 1
    assert len(result.balances[0].intervals) == 1

    interval = result.balances[0].intervals[0]
    requirement = result.requirements[0]

    assert interval.starts_at == BASE
    assert interval.ends_at == BASE + timedelta(minutes=30)
    assert interval.current_usable_storage_energy_wh == pytest.approx(4000.0)
    assert interval.expected_usable_pv_energy_wh == pytest.approx(1000.0)
    assert interval.household_load_forecast_energy_wh == pytest.approx(1500.0)
    assert interval.projected_storage_energy_wh == pytest.approx(3500.0)
    assert interval.confidence == pytest.approx(0.70)
    assert set(interval.evidence_ids) == {
        "storage-evidence",
        "pv-evidence",
        "load:quarter-1",
        "load:quarter-2",
    }
    assert requirement.reserve_contribution_wh == pytest.approx(4500.0)


def test_candidate_engine_normalizes_shifted_live_interval_boundaries() -> None:
    captured_at = BASE + timedelta(minutes=7)
    horizon_end = BASE + timedelta(minutes=30)
    storage = CurrentStorageState(
        storage_state_id="storage-home",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home",
        current_soc=0.50,
        usable_capacity_wh=8000.0,
        measured_at=captured_at,
        confidence=0.90,
        evidence_ids=("storage-evidence",),
    )
    pv_timeline = PVEnergyTimeline(
        timeline_id="pv-timeline",
        run_id="run-1",
        snapshot_id="snapshot-1",
        intervals=(
            PVEnergyTimelineInterval(
                interval_id="pv-clock-half-hour",
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=30),
                pv_energy_wh=900.0,
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
                interval_id="load-shifted-quarter-1",
                starts_at=captured_at,
                ends_at=captured_at + timedelta(minutes=15),
                expected_energy_wh=300.0,
                confidence=0.70,
                source_reference="load:shifted-quarter-1",
                method_version="deterministic-test:v1",
            ),
            HouseholdLoadForecastInterval(
                interval_id="load-shifted-quarter-2",
                starts_at=captured_at + timedelta(minutes=15),
                ends_at=captured_at + timedelta(minutes=30),
                expected_energy_wh=300.0,
                confidence=0.75,
                source_reference="load:shifted-quarter-2",
                method_version="deterministic-test:v1",
            ),
        ),
        fallback_active=False,
        fallback_reason=None,
    )
    snapshot = PlanningInputSnapshot(
        run_id="run-1",
        snapshot_id="snapshot-1",
        captured_at=captured_at,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:test",
        horizon_end=horizon_end,
        current_storage_states=(storage,),
        pv_energy_timeline=pv_timeline,
        household_load_forecast=load_forecast,
    )

    result = CandidateEngine().derive_storage_requirements(snapshot)

    interval = result.balances[0].intervals[0]
    requirement = result.requirements[0]

    assert interval.starts_at == captured_at
    assert interval.ends_at == horizon_end

    # PV: 900 Wh × 23/30 minutes = 690 Wh.
    assert interval.expected_usable_pv_energy_wh == pytest.approx(690.0)

    # Load: 300 Wh + 300 Wh × 8/15 minutes = 460 Wh.
    assert interval.household_load_forecast_energy_wh == pytest.approx(460.0)

    assert interval.projected_storage_energy_wh == pytest.approx(4230.0)
    assert interval.confidence == pytest.approx(0.70)
    assert set(interval.evidence_ids) == {
        "storage-evidence",
        "pv-evidence",
        "load:shifted-quarter-1",
        "load:shifted-quarter-2",
    }
    assert requirement.reserve_contribution_wh == pytest.approx(3770.0)


def test_pipeline_continues_conservatively_after_pv_forecast_ends() -> None:
    horizon_end = BASE + timedelta(hours=1)
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
        run_id="run-gap",
        snapshot_id="snapshot-gap",
        intervals=(
            PVEnergyTimelineInterval(
                interval_id="pv-first-half-hour",
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=30),
                pv_energy_wh=500.0,
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
        run_id="run-gap",
        snapshot_id="snapshot-gap",
        intervals=(
            HouseholdLoadForecastInterval(
                interval_id="load-first-half-hour",
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=30),
                expected_energy_wh=300.0,
                confidence=0.70,
                source_reference="load:first-half-hour",
                method_version="deterministic-test:v1",
            ),
            HouseholdLoadForecastInterval(
                interval_id="load-pv-gap",
                starts_at=BASE + timedelta(minutes=30),
                ends_at=horizon_end,
                expected_energy_wh=300.0,
                confidence=0.75,
                source_reference="load:pv-gap",
                method_version="deterministic-test:v1",
            ),
        ),
        fallback_active=False,
        fallback_reason=None,
    )
    snapshot = PlanningInputSnapshot(
        run_id="run-gap",
        snapshot_id="snapshot-gap",
        captured_at=BASE,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:test",
        horizon_end=horizon_end,
        current_storage_states=(storage,),
        pv_energy_timeline=pv_timeline,
        household_load_forecast=load_forecast,
    )

    pipeline_run = CanonicalPipeline().run(planning_input=snapshot)
    candidate_set = pipeline_run.candidate_set
    card = project(pipeline_run).cards[2]

    assert candidate_set.derivation_status == "ready_with_gaps"
    assert candidate_set.derivation_reason == "pv_forecast_gap"
    assert len(candidate_set.projected_balances) == 1
    assert len(candidate_set.storage_requirements) == 1

    intervals = candidate_set.projected_balances[0].intervals
    assert len(intervals) == 2
    assert intervals[0].projected_storage_energy_wh == pytest.approx(4200.0)
    assert intervals[1].expected_usable_pv_energy_wh == pytest.approx(0.0)
    assert intervals[1].projected_storage_energy_wh == pytest.approx(3900.0)
    assert intervals[1].confidence == pytest.approx(0.0)

    requirement = candidate_set.storage_requirements[0]
    assert requirement.reserve_contribution_wh == pytest.approx(4100.0)

    assert card.attributes["planning_gaps"] == [
        {
            "kind": "pv_forecast_gap",
            "starts_at": (
                BASE + timedelta(minutes=30)
            ).isoformat(),
            "ends_at": horizon_end.isoformat(),
            "duration_seconds": 1800.0,
            "assumption": "zero_usable_pv",
            "confidence": 0.0,
        }
    ]
