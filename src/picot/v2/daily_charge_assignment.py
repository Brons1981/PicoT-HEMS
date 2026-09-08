"""Daily main-charge lifecycle (ADR-037.2 through ADR-037.7).

This contract owns identity and observed completion, never window selection or
battery commands. The canonical planner must explicitly bind its admitted main
segments; NOM/grid primitives alone do not establish ownership.
"""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from math import isfinite
from zoneinfo import ZoneInfo


def _aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("daily charge timestamps must be timezone-aware")


class DailyChargeRevisionReason(StrEnum):
    INITIAL = "initial_main_route"
    TARGET_UNREACHABLE = "existing_route_cannot_reach_target"
    PV_LOWER = "pv_at_or_below_lower_with_execution_impact"
    PV_UPPER = "pv_above_central_with_execution_impact"
    LOAD = "additional_load_with_execution_impact"
    RESERVE = "projected_reserve_shortfall"


@dataclass(frozen=True, slots=True)
class DailyChargeSegment:
    """Explicit membership in the main route; bridge segments are excluded."""

    segment_id: str
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("main segment identity is required")
        _aware(self.starts_at)
        _aware(self.ends_at)
        if self.starts_at >= self.ends_at:
            raise ValueError("main segment must have positive duration")


@dataclass(frozen=True, slots=True)
class DailyChargeAssignment:
    execution_scope_id: str
    delivery_date: date
    timezone: str
    created_at: datetime
    route_plan_id: str | None = None
    main_segments: tuple[DailyChargeSegment, ...] = ()
    revision: int = 0
    revised_at: datetime | None = None
    revision_reason: DailyChargeRevisionReason | None = None
    revision_evidence_id: str | None = None
    completed_at: datetime | None = None
    completion_evidence_id: str | None = None
    completion_segment_id: str | None = None

    def __post_init__(self) -> None:
        if not self.execution_scope_id.strip():
            raise ValueError("daily charge scope is required")
        ZoneInfo(self.timezone)
        _aware(self.created_at)
        if self.created_at >= self.ends_at:
            raise ValueError("assignment must be created before its day ends")
        if self.revision_reason is not None and not isinstance(
            self.revision_reason, DailyChargeRevisionReason
        ):
            raise ValueError("revision reason must be an explicit energy trigger")
        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        bound = self.route_plan_id is not None
        if bound != bool(self.main_segments) or bound != (self.revision > 0):
            raise ValueError("a bound main route requires a plan, segments and revision")
        if bound != (self.revised_at is not None) or bound != (self.revision_reason is not None):
            raise ValueError("a bound main route requires revision evidence")
        if bound != (self.revision_evidence_id is not None):
            raise ValueError("a bound main route requires revision evidence identity")
        for value in (self.route_plan_id, self.revision_evidence_id, self.completion_evidence_id):
            if value is not None and not value.strip():
                raise ValueError("daily charge evidence and plan identities must be explicit")
        if self.revised_at is not None:
            _aware(self.revised_at)
            if not self.created_at <= self.revised_at < self.ends_at:
                raise ValueError("revision must follow creation and precede day end")
        if len({s.segment_id for s in self.main_segments}) != len(self.main_segments):
            raise ValueError("main segment identities must be unique")
        for segment in self.main_segments:
            if not self.starts_at <= segment.starts_at < segment.ends_at <= self.ends_at:
                raise ValueError("main segments must belong to the delivery day")
        if any(
            a.ends_at > b.starts_at
            for a, b in zip(self.main_segments, self.main_segments[1:], strict=False)
        ):
            raise ValueError("main segments must be ordered and non-overlapping")
        complete = self.completed_at is not None
        if complete != (self.completion_evidence_id is not None) or complete != (
            self.completion_segment_id is not None
        ):
            raise ValueError("completion requires observed evidence and main segment identity")
        if self.completed_at is not None:
            _aware(self.completed_at)
            if self.revised_at is None or self.completed_at < self.revised_at:
                raise ValueError("completion must follow the admitted route")
            if not any(
                s.segment_id == self.completion_segment_id
                and s.starts_at <= self.completed_at <= s.ends_at
                for s in self.main_segments
            ):
                raise ValueError("completion must belong to an explicit main segment")

    @property
    def assignment_id(self) -> str:
        return f"daily-charge:{self.execution_scope_id}:{self.timezone}:{self.delivery_date}"

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.delivery_date, time(), ZoneInfo(self.timezone)).astimezone(UTC)

    @property
    def ends_at(self) -> datetime:
        return datetime.combine(
            self.delivery_date + timedelta(days=1), time(), ZoneInfo(self.timezone)
        ).astimezone(UTC)

    def bind_main_route(
        self,
        *,
        plan_id: str,
        segments: tuple[DailyChargeSegment, ...],
        at: datetime,
        reason: DailyChargeRevisionReason,
        evidence_id: str,
    ) -> "DailyChargeAssignment":
        """Record the admitted route, with the same daily identity on revisions.

        A reason is supplied by the existing planner after assessing material
        execution impact; this lifecycle does not invent optimisation triggers.
        """
        if self.completed_at is not None:
            raise ValueError("a completed main route cannot be replaced")
        if (self.revision == 0) != (reason is DailyChargeRevisionReason.INITIAL):
            raise ValueError("initial reason is valid only for the first main route")
        _aware(at)
        if self.revised_at is not None and at < self.revised_at:
            raise ValueError("route revisions must be chronological")
        if not segments or all(s.ends_at <= at for s in segments):
            raise ValueError("a main route must have remaining execution time")
        return replace(
            self,
            route_plan_id=plan_id,
            main_segments=segments,
            revision=self.revision + 1,
            revised_at=at,
            revision_reason=reason,
            revision_evidence_id=evidence_id,
        )

    def observe_completion(
        self,
        *,
        measured_at: datetime,
        soc: float,
        evidence_id: str,
        plan_id: str,
        segment_id: str,
        execution_allowed: bool,
        state_read_at: datetime | None = None,
        state_valid_since: datetime | None = None,
    ) -> "DailyChargeAssignment":
        """Use actual telemetry for the explicitly admitted executing segment.

        Full at segment start counts. Full at midnight, in a bridge segment,
        between main segments, or from an old plan does not. A sample at the
        exact end of an executed segment may prove its just-completed charge.
        """
        _aware(measured_at)
        if not isfinite(soc) or not 0.0 <= soc <= 1.0:
            raise ValueError("observed SOC must be finite and between zero and one")
        if not evidence_id.strip():
            raise ValueError("completion evidence must be explicit")
        completed_at = measured_at
        if state_read_at is not None and state_valid_since is not None:
            _aware(state_read_at)
            _aware(state_valid_since)
            main = next((s for s in self.main_segments if s.segment_id == segment_id), None)
            if (main is not None and state_valid_since <= measured_at <= state_read_at
                    and state_valid_since <= main.starts_at <= state_read_at < main.ends_at):
                # A current HA state read proves full-at-start without inventing
                # a fresh sensor measurement or backdating the completion event.
                completed_at = state_read_at
        if (
            self.completed_at is not None
            or not execution_allowed
            or soc < 1.0
            or plan_id != self.route_plan_id
            or self.revised_at is None
            or completed_at < self.revised_at
        ):
            return self
        if not any(
            s.segment_id == segment_id and s.starts_at <= completed_at <= s.ends_at
            for s in self.main_segments
        ):
            return self
        return replace(
            self,
            completed_at=completed_at,
            completion_evidence_id=evidence_id,
            completion_segment_id=segment_id,
        )


def published_assignments(
    *,
    now: datetime,
    timezone: str,
    execution_scope_id: str,
    price_intervals: tuple[tuple[datetime, datetime], ...],
    existing: tuple[DailyChargeAssignment, ...],
) -> tuple[DailyChargeAssignment, ...]:
    """Recover missed publication from coverage; preserve existing daily state.

    Today's remaining published coverage is sufficient for late startup.
    Tomorrow requires its complete local day, including 23/25-hour clock days.
    Existing records are returned even when prices temporarily disappear.
    """
    _aware(now)
    zone = ZoneInfo(timezone)
    days: set[date] = set()
    for start, end in price_intervals:
        _aware(start)
        _aware(end)
        if start >= end:
            raise ValueError("price intervals must have positive duration")
        day = start.astimezone(zone).date()
        last = (end - timedelta(microseconds=1)).astimezone(zone).date()
        while day <= last:
            days.add(day)
            day += timedelta(days=1)
    known: dict[str, DailyChargeAssignment] = {}
    for item in existing:
        if item.execution_scope_id != execution_scope_id:
            continue
        if item.timezone != timezone:
            raise ValueError("delivery timezone change requires explicit migration")
        if item.assignment_id in known:
            raise ValueError("duplicate daily assignment identity")
        known[item.assignment_id] = item
    for day in sorted(days):
        end_of_day = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(UTC)
        if end_of_day <= now:
            continue
        candidate = DailyChargeAssignment(execution_scope_id, day, timezone, now)
        cursor = max(now, candidate.starts_at)
        for start, end in sorted(price_intervals):
            if end <= cursor:
                continue
            if start > cursor:
                break
            cursor = min(end, candidate.ends_at)
            if cursor == candidate.ends_at:
                known.setdefault(candidate.assignment_id, candidate)
                break
    return tuple(sorted(known.values(), key=lambda a: a.starts_at))


@dataclass(frozen=True, slots=True)
class DailyMainShortfallTrigger:
    """Fresh physical evidence authorising a revision of one existing route."""

    assignment_id: str
    route_plan_id: str
    revision: int
    active_plan_id: str
    snapshot_id: str
    assessed_at: datetime
    projected_main_peak_wh: float
    target_wh: float

    def __post_init__(self) -> None:
        _aware(self.assessed_at)
        if any(not value.strip() for value in (
            self.assignment_id, self.route_plan_id, self.active_plan_id, self.snapshot_id,
        )) or self.revision < 1:
            raise ValueError("shortfall trigger requires explicit bound route lineage")
        if not all(isfinite(v) for v in (self.projected_main_peak_wh, self.target_wh)) or (
            self.projected_main_peak_wh < 0 or self.target_wh <= 0
            or self.projected_main_peak_wh + 1e-6 >= self.target_wh
        ):
            raise ValueError("shortfall trigger requires a physically insufficient main route")

    @property
    def revision_reason(self) -> DailyChargeRevisionReason:
        return DailyChargeRevisionReason.TARGET_UNREACHABLE

    def validate(self, assignment: DailyChargeAssignment, snapshot_id: str, at: datetime) -> None:
        if (
            assignment.assignment_id != self.assignment_id
            or assignment.route_plan_id != self.route_plan_id
            or assignment.revision != self.revision
            or assignment.completed_at is not None
            or self.snapshot_id != snapshot_id or self.assessed_at != at
            or at >= assignment.ends_at
        ):
            raise ValueError("shortfall trigger does not match the current open route and input")
