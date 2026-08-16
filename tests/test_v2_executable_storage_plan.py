from datetime import UTC, datetime, timedelta

from picot.v2 import (
    ARCHITECTURE_BASELINE_COMMIT,
    PIPELINE_CONTRACT_VERSION,
    __version__,
)
from picot.v2.contracts import (
    CurrentStorageState,
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PlanningInputSnapshot,
    PriceForecastPoint,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.pipeline import CanonicalPipeline

BASE = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
HALF_HOUR = timedelta(minutes=30)


def _live_storage_snapshot() -> PlanningInputSnapshot:
    price_points = (
        PriceForecastPoint(
            point_id="price-low",
            starts_at=BASE,
            ends_at=BASE + HALF_HOUR,
            value_eur_per_kwh=0.10,
            confidence=1.0,
            evidence_id="nordpool-forecast",
        ),
        PriceForecastPoint(
            point_id="price-high",
            starts_at=BASE + HALF_HOUR,
            ends_at=BASE + 2 * HALF_HOUR,
            value_eur_per_kwh=0.30,
            confidence=1.0,
            evidence_id="nordpool-forecast",
        ),
    )
    pv_intervals = tuple(
        PVEnergyTimelineInterval(
            interval_id=f"pv-{index}",
            starts_at=BASE + index * HALF_HOUR,
            ends_at=BASE + (index + 1) * HALF_HOUR,
            pv_energy_wh=0.0,
            evidence_type="FORECAST",
            confidence=0.9,
            actual_evidence_ids=(),
            forecast_evidence_ids=("solcast-forecast",),
            conversion_method_version=(
                "solcast-detailed-forecast-average-kw-30m:v1"
            ),
        )
        for index in range(2)
    )
    load_intervals = tuple(
        HouseholdLoadForecastInterval(
            interval_id=f"load-{index}",
            starts_at=BASE + index * HALF_HOUR,
            ends_at=BASE + (index + 1) * HALF_HOUR,
            expected_energy_wh=250.0,
            confidence=0.9,
            source_reference="household-load-history",
            method_version="household-load-forecast:v1",
        )
        for index in range(2)
    )
    return PlanningInputSnapshot(
        run_id="run-executable-storage-plan",
        snapshot_id="snapshot-executable-storage-plan",
        captured_at=BASE,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:cost-first:v1",
        horizon_end=BASE + 2 * HALF_HOUR,
        price_points=price_points,
        current_storage_states=(
            CurrentStorageState(
                storage_state_id="storage-state-home",
                execution_scope_id="home-battery",
                capability_id="storage-capability-home-battery",
                current_soc=0.25,
                usable_capacity_wh=8160.0,
                measured_at=BASE,
                confidence=1.0,
                evidence_ids=("zendure-soc",),
            ),
        ),
        pv_energy_timeline=PVEnergyTimeline(
            timeline_id="pv-timeline",
            run_id="run-executable-storage-plan",
            snapshot_id="snapshot-executable-storage-plan",
            intervals=pv_intervals,
        ),
        household_load_forecast=HouseholdLoadForecast(
            forecast_id="load-forecast",
            run_id="run-executable-storage-plan",
            snapshot_id="snapshot-executable-storage-plan",
            intervals=load_intervals,
            fallback_active=False,
            fallback_reason=None,
        ),
    )


def test_storage_deficit_produces_one_due_observer_only_execution_request() -> None:
    result = CanonicalPipeline().run(
        planning_input=_live_storage_snapshot(),
        price_opportunity_config=PriceOpportunityConfig(
            low_price_margin_eur_per_kwh=0.01,
            high_price_margin_eur_per_kwh=0.01,
            config_version="price-opportunity-test:v1",
        ),
    )

    assert result.candidate_set.derivation_status == "ready"
    assert result.candidate_set.storage_requirements
    assert result.candidate_set.storage_requirements[0].reserve_contribution_wh > 0.0

    winning_path = next(
        path
        for path in result.candidate_set.energy_paths
        if path.path_id == result.evaluation.winning_energy_path_id
    )
    segments = getattr(winning_path, "segments", ())
    assert len(segments) == 1
    segment = segments[0]
    assert segment.execution_scope_id == "home-battery"
    assert segment.starts_at == BASE
    assert segment.ends_at == BASE + HALF_HOUR
    assert segment.primitive == "CHARGE_AT_POWER"
    assert 0.0 < segment.requested_power_w <= 2400.0

    assert len(result.execution_plan_set.plan_ids) == 1
    assert result.execution_record.status == "request_emitted"
    assert result.primitive_boundary.status == "emitted"
    assert result.primitive_boundary.request_id is not None

    # This first control slice proves the canonical route only. It may not
    # translate or dispatch a vendor command yet.
    assert result.adapter_boundary.status == "not_invoked"
    assert result.vendor_result.status == "not_dispatched"
