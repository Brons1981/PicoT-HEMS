from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)


def _interval(
    start: datetime,
    end: datetime,
    *,
    energy_wh: float = 250.0,
    evidence_type: PVEnergyEvidenceType = PVEnergyEvidenceType.FORECAST,
    confidence: float = 0.8,
) -> PVEnergyTimelineInterval:
    return PVEnergyTimelineInterval(
        starts_at=start,
        ends_at=end,
        energy_wh=energy_wh,
        evidence_type=evidence_type,
        confidence=confidence,
        evidence_ids=("pv:evidence",),
        method_version="pv-energy-v1",
    )


def test_pv_timeline_supports_actual_forecast_and_mixed_intervals() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    first_end = start + timedelta(minutes=15)
    second_end = first_end + timedelta(minutes=15)
    end = second_end + timedelta(minutes=15)

    timeline = PVEnergyTimeline(
        timeline_id="pv-timeline-1",
        created_at=start,
        horizon_start=start,
        horizon_end=end,
        intervals=(
            _interval(start, first_end, energy_wh=100.0, evidence_type=PVEnergyEvidenceType.ACTUAL),
            _interval(first_end, second_end, energy_wh=150.0, evidence_type=PVEnergyEvidenceType.MIXED),
            _interval(second_end, end, energy_wh=200.0, evidence_type=PVEnergyEvidenceType.FORECAST),
        ),
    )

    assert timeline.total_energy_wh == 450.0
    assert [item.evidence_type for item in timeline.intervals] == [
        PVEnergyEvidenceType.ACTUAL,
        PVEnergyEvidenceType.MIXED,
        PVEnergyEvidenceType.FORECAST,
    ]


def test_pv_timeline_rejects_gaps() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    midpoint = start + timedelta(minutes=15)
    end = start + timedelta(minutes=45)

    with pytest.raises(ValueError, match="contiguous"):
        PVEnergyTimeline(
            timeline_id="pv-gap",
            created_at=start,
            horizon_start=start,
            horizon_end=end,
            intervals=(
                _interval(start, midpoint),
                _interval(midpoint + timedelta(minutes=15), end),
            ),
        )


def test_pv_timeline_rejects_negative_energy() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="must not be negative"):
        _interval(start, start + timedelta(minutes=15), energy_wh=-1.0)


def test_pv_timeline_rejects_missing_evidence() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="requires evidence IDs"):
        PVEnergyTimelineInterval(
            starts_at=start,
            ends_at=start + timedelta(minutes=15),
            energy_wh=100.0,
            evidence_type=PVEnergyEvidenceType.ACTUAL,
            confidence=1.0,
            evidence_ids=(),
        )
