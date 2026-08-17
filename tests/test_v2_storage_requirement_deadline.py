from dataclasses import replace
from datetime import UTC, datetime, timedelta

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

BASE = datetime(2026, 8, 16, 14, 45, tzinfo=UTC)
INTERVAL = timedelta(minutes=30)
HORIZON_END = BASE + timedelta(hours=2)


def _snapshot(
    *,
    pv_wh: tuple[float, ...],
    load_wh: tuple[float, ...],
    fallback_active: bool = False,
) -> PlanningInputSnapshot:
    confidence = 0.0 if fallback_active else 0.8
    return PlanningInputSnapshot(
        run_id="run-deadline",
        snapshot_id="snapshot-deadline",
        captured_at=BASE,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:test",
        horizon_end=HORIZON_END,
        current_storage_states=(
            CurrentStorageState(
                storage_state_id="storage-home",
                execution_scope_id="home-battery",
                capability_id="storage-capability-home",
                current_soc=0.5,
                usable_capacity_wh=8000.0,
                measured_at=BASE,
                confidence=0.9,
                evidence_ids=("storage-evidence",),
            ),
        ),
        pv_energy_timeline=PVEnergyTimeline(
            timeline_id="pv-deadline",
            run_id="run-deadline",
            snapshot_id="snapshot-deadline",
            intervals=tuple(
                PVEnergyTimelineInterval(
                    interval_id=f"pv-{index}",
                    starts_at=BASE + index * INTERVAL,
                    ends_at=BASE + (index + 1) * INTERVAL,
                    pv_energy_wh=value,
                    evidence_type="FORECAST",
                    confidence=0.8,
                    actual_evidence_ids=(),
                    forecast_evidence_ids=(f"pv-evidence-{index}",),
                    conversion_method_version="forecast-energy:v1",
                )
                for index, value in enumerate(pv_wh)
            ),
        ),
        household_load_forecast=HouseholdLoadForecast(
            forecast_id="load-deadline",
            run_id="run-deadline",
            snapshot_id="snapshot-deadline",
            intervals=tuple(
                HouseholdLoadForecastInterval(
                    interval_id=f"load-{index}",
                    starts_at=BASE + index * INTERVAL,
                    ends_at=BASE + (index + 1) * INTERVAL,
                    expected_energy_wh=value,
                    confidence=confidence,
                    source_reference=f"load-evidence-{index}",
                    method_version="fallback:v1" if fallback_active else "history:v1",
                )
                for index, value in enumerate(load_wh)
            ),
            fallback_active=fallback_active,
            fallback_reason=(
                "insufficient_historical_data" if fallback_active else None
            ),
        ),
    )


def test_requirement_deadline_is_first_projected_battery_support_interval() -> None:
    snapshot = _snapshot(
        pv_wh=(600.0, 600.0, 100.0, 0.0),
        load_wh=(200.0, 200.0, 200.0, 200.0),
    )

    result = CandidateEngine().derive_storage_requirements(snapshot)

    requirement = result.requirements[0]
    assert requirement.required_by == BASE + timedelta(hours=1)
    assert requirement.required_by != snapshot.horizon_end
    assert requirement.reason == "full_before_first_projected_battery_support"
    assert requirement.reserve_contribution_wh == 3200.0


def test_current_deficit_requires_battery_at_snapshot_time() -> None:
    snapshot = _snapshot(
        pv_wh=(100.0, 100.0, 0.0, 0.0),
        load_wh=(200.0, 200.0, 200.0, 200.0),
    )

    result = CandidateEngine().derive_storage_requirements(snapshot)

    assert result.requirements[0].required_by == snapshot.captured_at


def test_current_support_uses_next_support_phase_after_future_pv_surplus() -> None:
    snapshot = _snapshot(
        pv_wh=(0.0, 600.0, 600.0, 0.0),
        load_wh=(200.0, 200.0, 200.0, 200.0),
    )
    snapshot = replace(
        snapshot,
        current_storage_states=(
            replace(
                snapshot.current_storage_states[0],
                current_soc=1.0,
            ),
        ),
    )

    result = CandidateEngine().derive_storage_requirements(snapshot)

    requirement = result.requirements[0]
    assert requirement.required_by == BASE + timedelta(hours=1, minutes=30)
    assert requirement.required_by > snapshot.captured_at
    assert result.balances[0].intervals[1].projected_storage_energy_wh == 8000.0


def test_no_projected_deficit_creates_no_artificial_horizon_deadline() -> None:
    snapshot = _snapshot(
        pv_wh=(600.0, 600.0, 600.0, 600.0),
        load_wh=(200.0, 200.0, 200.0, 200.0),
    )

    result = CandidateEngine().derive_storage_requirements(snapshot)

    assert result.requirements == ()


def test_fallback_load_keeps_preliminary_deadline_but_zero_confidence() -> None:
    snapshot = _snapshot(
        pv_wh=(600.0, 600.0, 100.0, 0.0),
        load_wh=(200.0, 200.0, 200.0, 200.0),
        fallback_active=True,
    )

    result = CandidateEngine().derive_storage_requirements(snapshot)

    requirement = result.requirements[0]
    assert requirement.required_by == BASE + timedelta(hours=1)
    assert requirement.confidence == 0.0
