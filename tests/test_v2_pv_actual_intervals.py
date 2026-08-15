from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.pv_actual_intervals import (
    PVPowerObservation,
    build_actual_pv_interval,
    diagnose_actual_pv_interval,
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
        == "goodwe-state-transition-step-hold-energy:v1"
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


def test_goodwe_state_changes_hold_until_the_next_transition() -> None:
    interval = build_actual_pv_interval(
        interval_id="pv-actual-state-changes",
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

    assert interval is not None
    assert interval.pv_energy_wh == pytest.approx(250.0)
    assert (
        interval.conversion_method_version
        == "goodwe-state-transition-step-hold-energy:v1"
    )


def test_long_state_transition_gap_is_diagnostic_not_missing_data(
) -> None:
    result = diagnose_actual_pv_interval(
        interval_id="pv-actual-gap",
        starts_at=BASE,
        ends_at=END,
        captured_at=END + timedelta(minutes=5),
        observations=(
            observation(-5, 600.0, "goodwe-anchor"),
            observation(60, 620.0, "goodwe-0831"),
            observation(1800, 600.0, "goodwe-0900"),
        ),
        telemetry_interval_seconds=5,
    )

    assert result.interval is not None
    assert result.status == "actual"
    assert result.reason is None
    assert result.observation_count == 3
    assert result.first_observed_at == BASE - timedelta(seconds=5)
    assert result.last_observed_at == END
    assert result.maximum_observed_gap_seconds == 1740.0
    assert result.allowed_gap_seconds is None
    assert result.history_semantics == "home_assistant_state_changes"


@pytest.mark.parametrize("source_state", ("unknown", "unavailable"))
def test_invalid_state_transition_blocks_actual_energy(
    source_state: str,
) -> None:
    result = diagnose_actual_pv_interval(
        interval_id="pv-actual-unavailable",
        starts_at=BASE,
        ends_at=END,
        captured_at=END + timedelta(minutes=5),
        observations=(
            observation(-5, 600.0, "goodwe-anchor"),
            PVPowerObservation(
                power_w=None,
                sampled_at=BASE + timedelta(minutes=10),
                evidence_id=f"goodwe-{source_state}",
                source_state=source_state,
            ),
            observation(1200, 300.0, "goodwe-recovered"),
        ),
        telemetry_interval_seconds=5,
    )

    assert result.interval is None
    assert result.status == "gap"
    assert result.reason == f"source_state_{source_state}"
    assert result.interruption_state == source_state
    assert result.interrupted_at == BASE + timedelta(minutes=10)
