from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.pv_actual_intervals import (
    PVPowerObservation,
    build_actual_pv_interval,
)

BASE = datetime(2026, 8, 15, 8, 30, tzinfo=UTC)
END = BASE + timedelta(minutes=30)


def observation(
    seconds: int,
    power_w: float,
    evidence_id: str,
) -> PVPowerObservation:
    return PVPowerObservation(
        power_w=power_w,
        sampled_at=BASE + timedelta(seconds=seconds),
        evidence_id=evidence_id,
    )


def test_closed_goodwe_interval_becomes_traceable_actual_energy() -> None:
    interval = build_actual_pv_interval(
        interval_id="pv-actual-2026-08-15T08:30Z",
        starts_at=BASE,
        ends_at=END,
        captured_at=END + timedelta(minutes=5),
        observations=(
            observation(-5, 600.0, "goodwe-anchor"),
            observation(600, 900.0, "goodwe-0840"),
            observation(1200, 300.0, "goodwe-0850"),
            observation(1800, 600.0, "goodwe-0900"),
        ),
        telemetry_interval_seconds=300,
    )

    assert interval is not None
    assert interval.starts_at == BASE
    assert interval.ends_at == END
    assert interval.pv_energy_wh == pytest.approx(300.0)
    assert interval.evidence_type == "ACTUAL"
    assert interval.confidence == pytest.approx(1.0)
    assert interval.actual_evidence_ids == (
        "goodwe-anchor",
        "goodwe-0840",
        "goodwe-0850",
        "goodwe-0900",
    )
    assert interval.forecast_evidence_ids == ()
    assert (
        interval.conversion_method_version
        == "goodwe-sample-hold-energy:v1"
    )


def test_open_goodwe_interval_is_not_integrated() -> None:
    interval = build_actual_pv_interval(
        interval_id="pv-actual-open",
        starts_at=BASE,
        ends_at=END,
        captured_at=END - timedelta(minutes=5),
        observations=(
            observation(-5, 600.0, "goodwe-anchor"),
            observation(600, 900.0, "goodwe-0840"),
            observation(1200, 300.0, "goodwe-0850"),
            observation(1800, 600.0, "goodwe-0900"),
        ),
        telemetry_interval_seconds=300,
    )

    assert interval is None


def test_goodwe_interval_requires_complete_boundary_coverage() -> None:
    interval = build_actual_pv_interval(
        interval_id="pv-actual-incomplete",
        starts_at=BASE,
        ends_at=END,
        captured_at=END + timedelta(minutes=5),
        observations=(
            observation(-5, 600.0, "goodwe-anchor"),
            observation(1200, 300.0, "goodwe-0850"),
            observation(1800, 600.0, "goodwe-0900"),
        ),
        telemetry_interval_seconds=300,
    )

    assert interval is None
