from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import PVEnergyTimeline, PVEnergyTimelineInterval

BASE = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)


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
