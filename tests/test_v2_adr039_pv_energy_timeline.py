from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import (
    PlanningInputSnapshot,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)

BASE = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)


def _planning_input_snapshot(
    *,
    run_id: str = "run-adr039",
    snapshot_id: str = "snapshot-adr039",
    pv_energy_timeline: PVEnergyTimeline | None = None,
) -> PlanningInputSnapshot:
    return PlanningInputSnapshot(
        run_id=run_id,
        snapshot_id=snapshot_id,
        captured_at=BASE,
        picot_version="2.0.0-dev.12",
        architecture_baseline_commit="baseline-adr039",
        pipeline_contract_version=1,
        strategy_id="strategy:no-objectives:v1",
        pv_energy_timeline=pv_energy_timeline,
    )


def _pv_interval(
    interval_id: str,
    starts_at: datetime,
    ends_at: datetime,
) -> PVEnergyTimelineInterval:
    return PVEnergyTimelineInterval(
        interval_id=interval_id,
        starts_at=starts_at,
        ends_at=ends_at,
        pv_energy_wh=100.0,
        evidence_type="FORECAST",
        confidence=0.8,
        actual_evidence_ids=(),
        forecast_evidence_ids=(f"evidence-{interval_id}",),
        conversion_method_version="forecast-energy-v1",
    )


def _evidence_interval(
    evidence_type: str,
    actual_evidence_ids: tuple[str, ...],
    forecast_evidence_ids: tuple[str, ...],
) -> PVEnergyTimelineInterval:
    return PVEnergyTimelineInterval(
        interval_id="pv-energy-evidence-test",
        starts_at=BASE,
        ends_at=BASE + timedelta(minutes=15),
        pv_energy_wh=100.0,
        evidence_type=evidence_type,
        confidence=0.8,
        actual_evidence_ids=actual_evidence_ids,
        forecast_evidence_ids=forecast_evidence_ids,
        conversion_method_version="forecast-energy-v1",
    )


def test_pv_energy_timeline_is_immutable_and_traceable() -> None:
    interval = PVEnergyTimelineInterval(
        interval_id="pv-energy-interval-mixed",
        starts_at=BASE,
        ends_at=BASE + timedelta(minutes=15),
        pv_energy_wh=306.0,
        evidence_type="MIXED",
        confidence=0.85,
        actual_evidence_ids=("evidence-pv-actual",),
        forecast_evidence_ids=("evidence-solcast-forecast",),
        conversion_method_version="solcast-interval-energy-v1",
    )
    timeline = PVEnergyTimeline(
        timeline_id="pv-energy-timeline-1",
        run_id="run-adr039",
        snapshot_id="snapshot-adr039",
        intervals=(interval,),
    )

    assert timeline.run_id == "run-adr039"
    assert timeline.snapshot_id == "snapshot-adr039"
    assert timeline.intervals == (interval,)
    assert interval.starts_at == BASE
    assert interval.ends_at == BASE + timedelta(minutes=15)
    assert interval.pv_energy_wh == pytest.approx(306.0)
    assert interval.evidence_type == "MIXED"
    assert interval.confidence == pytest.approx(0.85)
    assert interval.actual_evidence_ids == ("evidence-pv-actual",)
    assert interval.forecast_evidence_ids == (
        "evidence-solcast-forecast",
    )
    assert (
        interval.conversion_method_version
        == "solcast-interval-energy-v1"
    )

    with pytest.raises(FrozenInstanceError):
        interval.pv_energy_wh = 0.0  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        timeline.intervals = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    "ends_at",
    (BASE, BASE - timedelta(minutes=15)),
)
def test_pv_energy_interval_requires_positive_duration(
    ends_at: datetime,
) -> None:
    with pytest.raises(
        ValueError,
        match="starts_at must be before ends_at",
    ):
        _pv_interval("invalid-duration", BASE, ends_at)


def test_pv_energy_timeline_rejects_out_of_order_intervals() -> None:
    later = _pv_interval(
        "later",
        BASE + timedelta(minutes=30),
        BASE + timedelta(minutes=45),
    )
    earlier = _pv_interval(
        "earlier",
        BASE,
        BASE + timedelta(minutes=15),
    )

    with pytest.raises(
        ValueError,
        match="intervals must be chronologically ordered",
    ):
        PVEnergyTimeline(
            timeline_id="out-of-order",
            run_id="run-adr039",
            snapshot_id="snapshot-adr039",
            intervals=(later, earlier),
        )


def test_pv_energy_timeline_rejects_overlapping_intervals() -> None:
    first = _pv_interval(
        "first",
        BASE,
        BASE + timedelta(minutes=30),
    )
    overlapping = _pv_interval(
        "overlapping",
        BASE + timedelta(minutes=15),
        BASE + timedelta(minutes=45),
    )

    with pytest.raises(ValueError, match="intervals must not overlap"):
        PVEnergyTimeline(
            timeline_id="overlapping",
            run_id="run-adr039",
            snapshot_id="snapshot-adr039",
            intervals=(first, overlapping),
        )


def test_pv_energy_timeline_preserves_visible_gaps() -> None:
    first = _pv_interval(
        "first",
        BASE,
        BASE + timedelta(minutes=15),
    )
    after_gap = _pv_interval(
        "after-gap",
        BASE + timedelta(minutes=30),
        BASE + timedelta(minutes=45),
    )

    timeline = PVEnergyTimeline(
        timeline_id="with-gap",
        run_id="run-adr039",
        snapshot_id="snapshot-adr039",
        intervals=(first, after_gap),
    )

    assert timeline.intervals == (first, after_gap)


@pytest.mark.parametrize(
    "evidence_type",
    ("", "UNKNOWN", "actual"),
)
def test_pv_energy_interval_rejects_unknown_evidence_type(
    evidence_type: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="evidence_type must be ACTUAL, FORECAST, or MIXED",
    ):
        _evidence_interval(
            evidence_type,
            ("evidence-actual",),
            ("evidence-forecast",),
        )


@pytest.mark.parametrize(
    (
        "evidence_type",
        "actual_evidence_ids",
        "forecast_evidence_ids",
        "expected_message",
    ),
    (
        (
            "ACTUAL",
            (),
            ("evidence-forecast",),
            "ACTUAL interval requires actual evidence",
        ),
        (
            "FORECAST",
            ("evidence-actual",),
            (),
            "FORECAST interval requires forecast evidence",
        ),
        (
            "MIXED",
            ("evidence-actual",),
            (),
            "MIXED interval requires actual and forecast evidence",
        ),
        (
            "MIXED",
            (),
            ("evidence-forecast",),
            "MIXED interval requires actual and forecast evidence",
        ),
    ),
)
def test_pv_energy_interval_requires_matching_evidence(
    evidence_type: str,
    actual_evidence_ids: tuple[str, ...],
    forecast_evidence_ids: tuple[str, ...],
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        _evidence_interval(
            evidence_type,
            actual_evidence_ids,
            forecast_evidence_ids,
        )


def test_actual_interval_may_retain_forecast_diagnostics() -> None:
    interval = _evidence_interval(
        "ACTUAL",
        ("evidence-actual",),
        ("evidence-old-forecast",),
    )

    assert interval.actual_evidence_ids == ("evidence-actual",)
    assert interval.forecast_evidence_ids == (
        "evidence-old-forecast",
    )

def test_planning_input_snapshot_reuses_one_pv_energy_timeline() -> None:
    timeline = PVEnergyTimeline(
        timeline_id="pv-energy-timeline-planning-input",
        run_id="run-adr039",
        snapshot_id="snapshot-adr039",
        intervals=(
            _pv_interval(
                "planning-input",
                BASE,
                BASE + timedelta(minutes=15),
            ),
        ),
    )

    snapshot = _planning_input_snapshot(
        pv_energy_timeline=timeline,
    )

    assert snapshot.pv_energy_timeline is timeline


@pytest.mark.parametrize(
    ("run_id", "snapshot_id", "expected_message"),
    (
        (
            "different-run",
            "snapshot-adr039",
            (
                "PV energy timeline run_id must match "
                "planning input snapshot run_id"
            ),
        ),
        (
            "run-adr039",
            "different-snapshot",
            (
                "PV energy timeline snapshot_id must match "
                "planning input snapshot snapshot_id"
            ),
        ),
    ),
)
def test_planning_input_snapshot_rejects_pv_timeline_lineage_mismatch(
    run_id: str,
    snapshot_id: str,
    expected_message: str,
) -> None:
    timeline = PVEnergyTimeline(
        timeline_id="pv-energy-timeline-lineage",
        run_id="run-adr039",
        snapshot_id="snapshot-adr039",
        intervals=(),
    )

    with pytest.raises(ValueError, match=expected_message):
        _planning_input_snapshot(
            run_id=run_id,
            snapshot_id=snapshot_id,
            pv_energy_timeline=timeline,
        )
