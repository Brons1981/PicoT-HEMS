"""Deterministic conversion of actual PV power into energy intervals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

from picot.v2.contracts import PVEnergyTimelineInterval

INTEGRATION_METHOD_VERSION = "goodwe-sample-hold-energy:v1"


@dataclass(frozen=True, slots=True)
class PVPowerObservation:
    power_w: float
    sampled_at: datetime
    evidence_id: str

    def __post_init__(self) -> None:
        if not isfinite(self.power_w) or self.power_w < 0.0:
            raise ValueError("power_w must be finite and non-negative")
        if (
            self.sampled_at.tzinfo is None
            or self.sampled_at.utcoffset() is None
        ):
            raise ValueError("sampled_at must be timezone-aware")
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must be explicit")


@dataclass(frozen=True, slots=True)
class PVActualIntervalDiagnosis:
    interval: PVEnergyTimelineInterval | None
    status: str
    reason: str | None
    observation_count: int
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    maximum_observed_gap_seconds: float | None
    allowed_gap_seconds: float


def build_actual_pv_interval(
    *,
    interval_id: str,
    starts_at: datetime,
    ends_at: datetime,
    captured_at: datetime,
    observations: Sequence[PVPowerObservation],
    telemetry_interval_seconds: int = 5,
) -> PVEnergyTimelineInterval | None:
    """Integrate one closed PV interval using bounded sample-and-hold."""
    for name, value in (
        ("starts_at", starts_at),
        ("ends_at", ends_at),
        ("captured_at", captured_at),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")
    if starts_at >= ends_at:
        raise ValueError("starts_at must be before ends_at")
    if captured_at < ends_at:
        return None
    if (
        isinstance(telemetry_interval_seconds, bool)
        or telemetry_interval_seconds <= 0
    ):
        raise ValueError(
            "telemetry_interval_seconds must be positive"
        )

    maximum_gap = timedelta(
        seconds=max(
            30,
            telemetry_interval_seconds * 3,
        )
    )

    ordered = tuple(
        sorted(
            (
                observation
                for observation in observations
                if observation.sampled_at <= ends_at
            ),
            key=lambda observation: (
                observation.sampled_at,
                observation.evidence_id,
            ),
        )
    )
    if not ordered:
        return None

    deduplicated: list[PVPowerObservation] = []
    for observation in ordered:
        if (
            deduplicated
            and deduplicated[-1].sampled_at
            == observation.sampled_at
        ):
            deduplicated[-1] = observation
        else:
            deduplicated.append(observation)

    anchor_index: int | None = None
    for index, observation in enumerate(deduplicated):
        if observation.sampled_at <= starts_at:
            anchor_index = index
        else:
            break
    if anchor_index is None:
        return None
    anchor = deduplicated[anchor_index]
    if starts_at - anchor.sampled_at > maximum_gap:
        return None

    previous_time = starts_at
    previous_power_w = anchor.power_w
    energy_wh = 0.0
    evidence_ids = [anchor.evidence_id]

    for observation in deduplicated[anchor_index + 1 :]:
        if observation.sampled_at <= starts_at:
            continue
        gap = observation.sampled_at - previous_time
        if gap > maximum_gap:
            return None
        energy_wh += (
            previous_power_w
            * gap.total_seconds()
            / 3600.0
        )
        previous_time = observation.sampled_at
        previous_power_w = observation.power_w
        evidence_ids.append(observation.evidence_id)
        if previous_time == ends_at:
            break

    if previous_time < ends_at:
        tail_gap = ends_at - previous_time
        if tail_gap > maximum_gap:
            return None
        energy_wh += (
            previous_power_w
            * tail_gap.total_seconds()
            / 3600.0
        )

    return PVEnergyTimelineInterval(
        interval_id=interval_id,
        starts_at=starts_at,
        ends_at=ends_at,
        pv_energy_wh=energy_wh,
        evidence_type="ACTUAL",
        confidence=1.0,
        actual_evidence_ids=tuple(evidence_ids),
        forecast_evidence_ids=(),
        conversion_method_version=INTEGRATION_METHOD_VERSION,
    )


def diagnose_actual_pv_interval(
    *,
    interval_id: str,
    starts_at: datetime,
    ends_at: datetime,
    captured_at: datetime,
    observations: Sequence[PVPowerObservation],
    telemetry_interval_seconds: int = 5,
) -> PVActualIntervalDiagnosis:
    """Build an interval and expose why coverage was accepted or rejected."""
    interval = build_actual_pv_interval(
        interval_id=interval_id,
        starts_at=starts_at,
        ends_at=ends_at,
        captured_at=captured_at,
        observations=observations,
        telemetry_interval_seconds=telemetry_interval_seconds,
    )
    allowed_gap_seconds = float(
        max(30, telemetry_interval_seconds * 3)
    )

    ordered = tuple(
        sorted(
            (
                observation
                for observation in observations
                if observation.sampled_at <= ends_at
            ),
            key=lambda observation: (
                observation.sampled_at,
                observation.evidence_id,
            ),
        )
    )
    deduplicated: list[PVPowerObservation] = []
    for observation in ordered:
        if (
            deduplicated
            and deduplicated[-1].sampled_at
            == observation.sampled_at
        ):
            deduplicated[-1] = observation
        else:
            deduplicated.append(observation)

    anchor_index: int | None = None
    for index, observation in enumerate(deduplicated):
        if observation.sampled_at <= starts_at:
            anchor_index = index
        else:
            break

    relevant = (
        tuple(deduplicated[anchor_index:])
        if anchor_index is not None
        else tuple(deduplicated)
    )
    observed_gaps = tuple(
        (
            current.sampled_at - previous.sampled_at
        ).total_seconds()
        for previous, current in zip(
            relevant,
            relevant[1:],
            strict=False,
        )
    )
    maximum_observed_gap_seconds = (
        max(observed_gaps) if observed_gaps else None
    )
    first_observed_at = (
        relevant[0].sampled_at if relevant else None
    )
    last_observed_at = (
        relevant[-1].sampled_at if relevant else None
    )

    if interval is not None:
        status = "actual"
        reason = None
    elif captured_at < ends_at:
        status = "not_closed"
        reason = "interval_not_closed"
    elif not relevant:
        status = "gap"
        reason = "no_observations"
    elif anchor_index is None:
        status = "gap"
        reason = "missing_start_anchor"
    elif (
        starts_at - relevant[0].sampled_at
    ).total_seconds() > allowed_gap_seconds:
        status = "gap"
        reason = "start_anchor_gap_exceeds_limit"
    elif (
        maximum_observed_gap_seconds is not None
        and maximum_observed_gap_seconds
        > allowed_gap_seconds
    ):
        status = "gap"
        reason = "observation_gap_exceeds_limit"
    elif (
        ends_at - relevant[-1].sampled_at
    ).total_seconds() > allowed_gap_seconds:
        status = "gap"
        reason = "end_gap_exceeds_limit"
    else:
        status = "gap"
        reason = "incomplete_boundary_coverage"

    return PVActualIntervalDiagnosis(
        interval=interval,
        status=status,
        reason=reason,
        observation_count=len(relevant),
        first_observed_at=first_observed_at,
        last_observed_at=last_observed_at,
        maximum_observed_gap_seconds=(
            maximum_observed_gap_seconds
        ),
        allowed_gap_seconds=allowed_gap_seconds,
    )
