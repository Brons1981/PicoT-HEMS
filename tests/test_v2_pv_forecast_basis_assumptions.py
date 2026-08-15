from datetime import UTC, datetime, timedelta

from picot.v2 import (
    ARCHITECTURE_BASELINE_COMMIT,
    PIPELINE_CONTRACT_VERSION,
    __version__,
)
from picot.v2.contracts import (
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
    PlanningInputSnapshot,
)
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project


CAPTURED_AT = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
FUTURE_START = CAPTURED_AT
FUTURE_END = FUTURE_START + timedelta(minutes=30)


def _snapshot(*, range_available: bool) -> PlanningInputSnapshot:
    if range_available:
        lower = 100.0
        central = 200.0
        upper = 400.0
        range_status = "available"
        source_fields = (
            "pv_estimate10",
            "pv_estimate",
            "pv_estimate90",
        )
        range_method = (
            "solcast-pv-estimate-range-average-kw-30m:v1"
        )
    else:
        lower = None
        central = None
        upper = None
        range_status = "unavailable"
        source_fields = ()
        range_method = None

    return PlanningInputSnapshot(
        run_id="run-assumptions",
        snapshot_id="snapshot-assumptions",
        captured_at=CAPTURED_AT,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:test",
        horizon_end=FUTURE_END,
        pv_energy_timeline=PVEnergyTimeline(
            timeline_id="pv-timeline-assumptions",
            run_id="run-assumptions",
            snapshot_id="snapshot-assumptions",
            intervals=(
                PVEnergyTimelineInterval(
                    interval_id="actual-elapsed",
                    starts_at=(
                        CAPTURED_AT - timedelta(minutes=30)
                    ),
                    ends_at=CAPTURED_AT,
                    pv_energy_wh=150.0,
                    evidence_type="ACTUAL",
                    confidence=1.0,
                    actual_evidence_ids=("goodwe-elapsed",),
                    forecast_evidence_ids=("solcast-elapsed",),
                    conversion_method_version=(
                        "goodwe-state-transition-step-hold-energy:v1"
                    ),
                ),
                PVEnergyTimelineInterval(
                    interval_id="forecast-future",
                    starts_at=FUTURE_START,
                    ends_at=FUTURE_END,
                    pv_energy_wh=200.0,
                    evidence_type="FORECAST",
                    confidence=0.25,
                    actual_evidence_ids=(),
                    forecast_evidence_ids=("solcast-future",),
                    conversion_method_version=(
                        "solcast-detailed-forecast-average-kw-30m:v1"
                    ),
                    forecast_lower_energy_wh=lower,
                    forecast_central_energy_wh=central,
                    forecast_upper_energy_wh=upper,
                    forecast_range_status=range_status,
                    forecast_range_source_fields=source_fields,
                    forecast_range_method_version=range_method,
                ),
            ),
        ),
    )


def test_future_pv_assumptions_are_whole_household_and_bounded() -> None:
    from picot.v2.pv_forecast_assumptions import (
        ASSUMPTION_METHOD_VERSION,
        derive_pv_forecast_basis_assumptions,
    )

    assumption_set = derive_pv_forecast_basis_assumptions(
        _snapshot(range_available=True)
    )

    assert assumption_set.run_id == "run-assumptions"
    assert assumption_set.snapshot_id == "snapshot-assumptions"
    assert assumption_set.maximum_assumption_count == 3
    assert len(assumption_set.assumptions) == 3
    assert [item.basis for item in assumption_set.assumptions] == [
        "lower",
        "central",
        "upper",
    ]
    assert all(
        item.scope == "whole_household_energy_path"
        for item in assumption_set.assumptions
    )
    assert all(
        item.status == "available"
        for item in assumption_set.assumptions
    )
    assert [
        item.intervals[0].selected_energy_wh
        for item in assumption_set.assumptions
    ] == [100.0, 200.0, 400.0]
    assert all(
        len(item.intervals) == 1
        for item in assumption_set.assumptions
    )
    for item in assumption_set.assumptions:
        interval = item.intervals[0]
        assert interval.source_interval_id == "forecast-future"
        assert interval.starts_at == FUTURE_START
        assert interval.ends_at == FUTURE_END
        assert interval.confidence == 0.25
        assert interval.forecast_evidence_ids == ("solcast-future",)
        assert interval.forecast_range_status == "available"
        assert interval.forecast_range_method_version == (
            "solcast-pv-estimate-range-average-kw-30m:v1"
        )
        assert interval.conversion_method_version == (
            "solcast-detailed-forecast-average-kw-30m:v1"
        )
    assert assumption_set.method_version == ASSUMPTION_METHOD_VERSION
    assert assumption_set.method_version == (
        "pv-forecast-basis-assumptions:future-intervals:v1"
    )


def test_missing_bounds_leave_lower_and_upper_unavailable() -> None:
    from picot.v2.pv_forecast_assumptions import (
        derive_pv_forecast_basis_assumptions,
    )

    assumption_set = derive_pv_forecast_basis_assumptions(
        _snapshot(range_available=False)
    )
    lower, central, upper = assumption_set.assumptions

    assert lower.status == "unavailable"
    assert lower.unavailable_reason == "forecast_range_unavailable"
    assert lower.intervals == ()
    assert central.status == "available"
    assert central.unavailable_reason is None
    assert central.intervals[0].selected_energy_wh == 200.0
    assert upper.status == "unavailable"
    assert upper.unavailable_reason == "forecast_range_unavailable"
    assert upper.intervals == ()


def test_candidate_card_exposes_bounded_future_pv_assumptions() -> None:
    run = CanonicalPipeline().run(
        planning_input=_snapshot(range_available=True)
    )

    assumption_set = run.candidate_set.pv_forecast_assumption_set
    assert assumption_set is not None
    assert len(assumption_set.assumptions) == 3

    attributes = project(run).cards[2].attributes
    assert attributes["pv_forecast_assumption_set_id"] == (
        assumption_set.assumption_set_id
    )
    assert attributes["pv_forecast_assumption_count"] == 3
    assert attributes["pv_forecast_maximum_assumption_count"] == 3
    assert attributes["pv_forecast_assumption_method_version"] == (
        "pv-forecast-basis-assumptions:future-intervals:v1"
    )
    assumptions = attributes["pv_forecast_assumptions"]
    assert [item["basis"] for item in assumptions] == [
        "lower",
        "central",
        "upper",
    ]
    assert assumptions[0] == {
        "assumption_id": (
            assumption_set.assumptions[0].assumption_id
        ),
        "basis": "lower",
        "scope": "whole_household_energy_path",
        "status": "available",
        "unavailable_reason": None,
        "method_version": (
            "pv-forecast-basis-assumptions:future-intervals:v1"
        ),
        "intervals": [
            {
                "source_interval_id": "forecast-future",
                "starts_at": FUTURE_START.isoformat(),
                "ends_at": FUTURE_END.isoformat(),
                "selected_energy_wh": 100.0,
                "confidence": 0.25,
                "forecast_evidence_ids": ["solcast-future"],
                "forecast_range_status": "available",
                "forecast_range_method_version": (
                    "solcast-pv-estimate-range-average-kw-30m:v1"
                ),
                "conversion_method_version": (
                    "solcast-detailed-forecast-average-kw-30m:v1"
                ),
            }
        ],
    }
