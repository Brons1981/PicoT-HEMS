"""Frozen daily PV reference and complete comparison evidence (ADR-037.8).

No price selection, forecast correction or vendor control belongs here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from typing import TYPE_CHECKING, Any

from picot.v2.daily_charge_assignment import DailyChargeAssignment, DailyChargeRevisionReason

if TYPE_CHECKING:
    from picot.v2.contracts import PlanningInputSnapshot, PVEnergyTimeline


def _id(value: object) -> str:
    return sha256(repr(value).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DailyPVReferenceInterval:
    starts_at: datetime
    ends_at: datetime
    lower_wh: float
    central_wh: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.starts_at.utcoffset() is None or self.ends_at.utcoffset() is None:
            raise ValueError("PV reference times must be aware")
        if self.ends_at <= self.starts_at or not self.evidence_ids:
            raise ValueError("PV reference requires a positive interval and source evidence")
        if not all(isfinite(v) for v in (self.lower_wh, self.central_wh)) or (
            not 0 <= self.lower_wh <= self.central_wh
        ):
            raise ValueError("PV reference range is invalid")


@dataclass(frozen=True, slots=True)
class DailyPVComparisonBasis:
    assignment_id: str
    snapshot_id: str
    captured_at: datetime
    day_starts_at: datetime
    day_ends_at: datetime
    intervals: tuple[DailyPVReferenceInterval, ...]

    def __post_init__(self) -> None:
        if not self.assignment_id or not self.snapshot_id:
            raise ValueError("PV reference requires ownership and input lineage")
        if (
            any(
                t.utcoffset() is None
                for t in (
                    self.captured_at,
                    self.day_starts_at,
                    self.day_ends_at,
                )
            )
            or self.day_ends_at <= self.day_starts_at
        ):
            raise ValueError("PV reference requires aware day boundaries")
        for interval in self.intervals:
            if (
                not max(self.captured_at, self.day_starts_at)
                <= interval.starts_at
                < (interval.ends_at)
                <= self.day_ends_at
            ):
                raise ValueError("PV reference must precede its complete delivery-day interval")
        if any(
            a.ends_at != b.starts_at
            for a, b in zip(
                self.intervals,
                self.intervals[1:],
                strict=False,
            )
        ):
            raise ValueError("PV reference intervals must be contiguous and non-overlapping")
        if self.intervals and self.intervals[-1].ends_at != self.day_ends_at:
            raise ValueError("PV reference must cover the remaining delivery day")

    @property
    def basis_id(self) -> str:
        return "daily-pv-basis:" + _id(json.dumps(self.to_payload(), sort_keys=True))

    @classmethod
    def capture(
        cls, snapshot: PlanningInputSnapshot, owner: DailyChargeAssignment
    ) -> DailyPVComparisonBasis:
        if owner.revision:
            raise ValueError("a frozen PV reference may only be captured at first binding")
        timeline = snapshot.pv_energy_timeline
        if timeline is None:
            raise ValueError("initial PV reference requires its forecast")
        intervals = []
        for interval in sorted(timeline.intervals, key=lambda i: i.starts_at):
            if interval.starts_at < max(owner.starts_at, snapshot.captured_at) or (
                interval.ends_at > owner.ends_at
            ):
                continue
            if interval.evidence_type != "FORECAST" or (
                interval.forecast_lower_energy_wh is None
                or interval.forecast_central_energy_wh is None
            ):
                raise ValueError("initial PV reference requires the original forecast range")
            intervals.append(
                DailyPVReferenceInterval(
                    interval.starts_at,
                    interval.ends_at,
                    interval.forecast_lower_energy_wh,
                    interval.forecast_central_energy_wh,
                    interval.forecast_evidence_ids,
                )
            )
        return cls(
            owner.assignment_id,
            snapshot.snapshot_id,
            snapshot.captured_at,
            owner.starts_at,
            owner.ends_at,
            tuple(intervals),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "snapshot_id": self.snapshot_id,
            "captured_at": self.captured_at.astimezone(UTC).isoformat(),
            "day_starts_at": self.day_starts_at.astimezone(UTC).isoformat(),
            "day_ends_at": self.day_ends_at.astimezone(UTC).isoformat(),
            "intervals": [
                {
                    **asdict(i),
                    "lower_wh": float(i.lower_wh),
                    "central_wh": float(i.central_wh),
                    "starts_at": i.starts_at.astimezone(UTC).isoformat(),
                    "ends_at": i.ends_at.astimezone(UTC).isoformat(),
                }
                for i in self.intervals
            ],
        }

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> DailyPVComparisonBasis:
        return cls(
            raw["assignment_id"],
            raw["snapshot_id"],
            datetime.fromisoformat(raw["captured_at"]),
            datetime.fromisoformat(raw["day_starts_at"]),
            datetime.fromisoformat(raw["day_ends_at"]),
            tuple(
                DailyPVReferenceInterval(
                    datetime.fromisoformat(i["starts_at"]),
                    datetime.fromisoformat(i["ends_at"]),
                    float(i["lower_wh"]),
                    float(i["central_wh"]),
                    tuple(i["evidence_ids"]),
                )
                for i in raw["intervals"]
            ),
        )


@dataclass(frozen=True, slots=True)
class DailyPVComparisonState:
    assignment_id: str
    basis: DailyPVComparisonBasis | None
    assessed_evidence_ids: tuple[str, ...] = ()
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DailyPVComparison:
    assignment_id: str
    basis_id: str
    evidence_id: str
    starts_at: datetime | None
    ends_at: datetime | None
    status: str
    actual_wh: float | None
    lower_wh: float | None
    central_wh: float | None
    boundary: str | None


def compare_daily_pv(
    basis: DailyPVComparisonBasis,
    timeline: PVEnergyTimeline | None,
    *,
    at: datetime,
) -> DailyPVComparison:
    """Use exactly the closed frozen intervals; missing coverage is not zero PV."""
    closed = tuple(i for i in basis.intervals if i.ends_at <= at)
    starts = closed[0].starts_at if closed else None
    ends = closed[-1].ends_at if closed else None
    actuals = tuple(
        sorted(
            (
                i
                for i in (timeline.intervals if timeline else ())
                if i.evidence_type == "ACTUAL"
                and starts is not None
                and ends is not None
                and i.ends_at > starts
                and i.starts_at < ends
            ),
            key=lambda i: (i.starts_at, i.ends_at, i.actual_evidence_ids),
        )
    )
    identity = (
        basis.basis_id,
        starts.astimezone(UTC).isoformat() if starts else None,
        ends.astimezone(UTC).isoformat() if ends else None,
        tuple(
            (
                i.starts_at.astimezone(UTC).isoformat(),
                i.ends_at.astimezone(UTC).isoformat(),
                float(i.pv_energy_wh),
                i.actual_evidence_ids,
            )
            for i in actuals
        ),
    )
    complete = (
        bool(closed)
        and len(actuals) == len(closed)
        and all(
            (a.starts_at, a.ends_at) == (f.starts_at, f.ends_at)
            and a.actual_evidence_ids
            and isfinite(a.pv_energy_wh)
            and a.pv_energy_wh >= 0
            for f, a in zip(closed, actuals, strict=False)
        )
    )
    actual = sum(i.pv_energy_wh for i in actuals) if complete else None
    lower = sum(i.lower_wh for i in closed) if complete else None
    central = sum(i.central_wh for i in closed) if complete else None
    boundary = None
    if actual is not None and lower is not None and central is not None:
        boundary = (
            "at_or_below_lower"
            if actual <= lower
            else ("above_central" if actual > central else "within_bounds")
        )
    return DailyPVComparison(
        basis.assignment_id,
        basis.basis_id,
        "daily-pv:" + _id(identity),
        starts,
        ends,
        "complete" if complete else "partial" if closed else "no_closed_interval",
        actual,
        lower,
        central,
        boundary,
    )


@dataclass(frozen=True, slots=True)
class DailyMainPVSurplusTrigger:
    assignment_id: str
    route_plan_id: str
    revision: int
    active_plan_id: str
    snapshot_id: str
    assessed_at: datetime
    target_wh: float
    basis_id: str
    comparison_evidence_id: str
    actual_wh: float
    central_wh: float
    prior_grid_input_wh: float
    removable_grid_input_wh: float
    soc_based: bool = False

    @property
    def revision_reason(self) -> DailyChargeRevisionReason:
        return (DailyChargeRevisionReason.GRID_REDUCTION if self.soc_based
                else DailyChargeRevisionReason.PV_UPPER)

    def __post_init__(self) -> None:
        if self.assessed_at.utcoffset() is None or self.revision < 1:
            raise ValueError("PV trigger requires an aware assessment and bound revision")
        if any(
            not v
            for v in (
                self.assignment_id,
                self.route_plan_id,
                self.active_plan_id,
                self.snapshot_id,
                self.basis_id,
                self.comparison_evidence_id,
            )
        ):
            raise ValueError("PV trigger requires explicit lineage")
        if not all(
            isfinite(v)
            for v in (
                self.target_wh,
                self.actual_wh,
                self.central_wh,
                self.prior_grid_input_wh,
                self.removable_grid_input_wh,
            )
        ) or (
            self.target_wh <= 0
            or min(self.actual_wh, self.central_wh) < 0
            or (not self.soc_based and self.actual_wh <= self.central_wh)
            or not 0 < self.removable_grid_input_wh <= self.prior_grid_input_wh
        ):
            raise ValueError(
                "Grid reduction requires valid evidence and removable grid charging"
            )

    def validate(self, assignment: DailyChargeAssignment, snapshot_id: str, at: datetime) -> None:
        if (
            (assignment.assignment_id, assignment.route_plan_id, assignment.revision)
            != (
                self.assignment_id,
                self.route_plan_id,
                self.revision,
            )
            or assignment.completed_at is not None
            or self.snapshot_id != snapshot_id
            or (self.assessed_at != at or at >= assignment.ends_at)
        ):
            raise ValueError("PV surplus trigger does not match the current open route and input")
