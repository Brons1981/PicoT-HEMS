"""Physically discovered minimal charge windows for the daily simulator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import DailyPlanningProjection, PVScenario
from picot.domain.execution_plan import ExecutionPlanSegment


@dataclass(frozen=True, slots=True)
class DailyReferenceChargeWindowScenario:
    """Target-reaching evidence for one PV uncertainty scenario."""

    scenario: PVScenario
    target_reached_at: datetime


@dataclass(frozen=True, slots=True)
class DailyReferenceChargeWindow:
    """One charge window proven sufficient and interval-minimal."""

    window_id: str
    intent: DailyStorageIntent
    starts_at: datetime
    ends_at: datetime
    interval_count: int
    scenario_outcomes: tuple[DailyReferenceChargeWindowScenario, ...]
    conservative_target_reached_at: datetime
    schedule: DailyReferenceIntentSchedule
    sufficient_across_scenarios: bool
    one_interval_shorter_sufficient: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.window_id.strip() or not self.method_version.strip():
            raise ValueError("Daily charge window identity must be explicit.")
        if self.intent not in {
            DailyStorageIntent.NOM,
            DailyStorageIntent.GRID_REQUIREMENT,
        }:
            raise ValueError("Daily charge window requires a charging intent.")
        if self.ends_at <= self.starts_at or self.interval_count <= 0:
            raise ValueError("Daily charge window duration must be positive.")
        scenarios = tuple(item.scenario for item in self.scenario_outcomes)
        if set(scenarios) != set(PVScenario) or len(scenarios) != len(PVScenario):
            raise ValueError("Daily charge window requires all PV scenarios.")
        if self.conservative_target_reached_at != max(
            item.target_reached_at for item in self.scenario_outcomes
        ):
            raise ValueError("Daily charge window conservative target must reconcile.")
        if not self.sufficient_across_scenarios:
            raise ValueError("Daily charge window must be physically sufficient.")
        if self.one_interval_shorter_sufficient:
            raise ValueError("Daily charge window must be interval-minimal.")
        active = tuple(
            item
            for item in self.schedule.intervals
            if item.intent is self.intent
        )
        if len(active) != self.interval_count:
            raise ValueError("Daily charge window schedule duration must reconcile.")
        if active[0].starts_at != self.starts_at or active[-1].ends_at != self.ends_at:
            raise ValueError("Daily charge window schedule boundaries must reconcile.")


@dataclass(frozen=True, slots=True)
class DailyReferenceChargeWindowSet:
    """Unranked physically minimal windows from one immutable snapshot."""

    window_set_id: str
    snapshot_id: str
    windows: tuple[DailyReferenceChargeWindow, ...]
    observer_only: bool
    ranking_permitted: bool
    method_version: str
    discovery_status: str = "discovered"
    hybrid_schedules: tuple[DailyReferenceIntentSchedule, ...] = ()

    def __post_init__(self) -> None:
        if not self.window_set_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily charge window set identity must be explicit.")
        if not self.method_version.strip():
            raise ValueError("Daily charge window set lineage must be explicit.")
        if self.discovery_status not in {
            "discovered",
            "not_required",
            "no_feasible_window",
        }:
            raise ValueError("Daily charge window discovery status is invalid.")
        if (self.discovery_status == "discovered") != bool(self.windows):
            raise ValueError("Daily charge window status must match discovered windows.")
        window_ids = tuple(item.window_id for item in self.windows)
        if len(window_ids) != len(set(window_ids)):
            raise ValueError("Daily charge windows must be unique.")
        if any(item.schedule.snapshot_id != self.snapshot_id for item in self.windows):
            raise ValueError("Daily charge windows must share one snapshot.")
        hybrid_ids = tuple(item.schedule_id for item in self.hybrid_schedules)
        if len(hybrid_ids) != len(set(hybrid_ids)):
            raise ValueError("Daily hybrid charge schedules must be unique.")
        if any(item.snapshot_id != self.snapshot_id for item in self.hybrid_schedules):
            raise ValueError("Daily hybrid charge schedules must share one snapshot.")
        if any(
            {
                DailyStorageIntent.NOM,
                DailyStorageIntent.GRID_REQUIREMENT,
            }
            - {interval.intent for interval in schedule.intervals}
            for schedule in self.hybrid_schedules
        ):
            raise ValueError("Daily hybrid schedules require NOM and grid recovery.")
        if not self.observer_only or self.ranking_permitted:
            raise ValueError(
                "Daily charge windows must remain observer-only and unranked."
            )


@dataclass(frozen=True, slots=True)
class DailyMainChargeSegment:
    """Explicit candidate-level ownership; execution IDs are projected later."""

    segment_id: str
    starts_at: datetime
    ends_at: datetime
    intent: DailyStorageIntent

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("main candidate segment identity is required")
        if any(t.utcoffset() is None for t in (self.starts_at, self.ends_at)):
            raise ValueError("main candidate segment timestamps must be timezone-aware")
        if self.starts_at >= self.ends_at:
            raise ValueError("main candidate segment duration must be positive")
        if self.intent not in {DailyStorageIntent.NOM, DailyStorageIntent.GRID_REQUIREMENT}:
            raise ValueError("main candidate segment requires a charging intent")


@dataclass(frozen=True, slots=True)
class DailyRetainedMainSegment:
    """Original ownership carried through a new horizon's physical simulation."""

    assignment_id: str
    plan_id: str
    segment: ExecutionPlanSegment

    def __post_init__(self) -> None:
        if not self.assignment_id.strip() or not self.plan_id.strip():
            raise ValueError("retained main ownership must be explicit")


@dataclass(frozen=True, slots=True)
class DailyMainChargeWindow:
    """One physically feasible main route, still unranked by economics."""

    assignment_id: str
    family: str
    schedule: DailyReferenceIntentSchedule
    main_segments: tuple[DailyMainChargeSegment, ...]
    projection: DailyPlanningProjection
    reached_at: datetime
    target_storage_energy_wh: float
    retained_main_segments: tuple[DailyRetainedMainSegment, ...] = ()

    def __post_init__(self) -> None:
        if any(s.assignment_id == self.assignment_id for s in self.retained_main_segments):
            raise ValueError("first discovery cannot also retain its own bound main route")
        if self.family not in {"pv", "grid", "hybrid", "already_full"}:
            raise ValueError("invalid main charge family")
        if not self.main_segments or not self.assignment_id.strip():
            raise ValueError("main window requires explicit assignment and segments")
        if self.schedule.snapshot_id != self.projection.snapshot_id or (
            self.schedule.schedule_id != self.projection.intent_schedule_id
        ):
            raise ValueError("main route and projection lineage must match")
        ids = tuple(s.segment_id for s in self.main_segments)
        if len(ids) != len(set(ids)):
            raise ValueError("main candidate segment identities must be unique")
        for segment in self.main_segments:
            owned = tuple(
                i
                for i in self.schedule.intervals
                if segment.starts_at <= i.starts_at and i.ends_at <= segment.ends_at
            )
            if (
                not owned
                or owned[0].starts_at != segment.starts_at
                or owned[-1].ends_at != segment.ends_at
                or any(i.intent is not segment.intent for i in owned)
            ):
                raise ValueError("main candidate ownership must match the proposed schedule")
        if any(
            a.ends_at > b.starts_at
            for a, b in zip(self.main_segments, self.main_segments[1:], strict=False)
        ):
            raise ValueError("main candidate segments must be ordered and non-overlapping")
        if not any(s.starts_at <= self.reached_at <= s.ends_at for s in self.main_segments):
            raise ValueError("main target must be reached inside its owned segments")
        if not any(
            (
                i.starts_at == self.reached_at
                and i.storage_energy_at_start_wh + 1e-6 >= self.target_storage_energy_wh
            )
            or (
                i.ends_at == self.reached_at
                and i.storage_energy_at_end_wh + 1e-6 >= self.target_storage_energy_wh
            )
            for i in self.projection.intervals
        ):
            raise ValueError("main target requires physical full-storage evidence")


@dataclass(frozen=True, slots=True)
class DailyMainChargeWindowSet:
    assignment_id: str
    snapshot_id: str
    windows: tuple[DailyMainChargeWindow, ...]
    status: str
    reason: str
    simulation_count: int

    def __post_init__(self) -> None:
        if self.status not in {"discovered", "completed", "unreachable"}:
            raise ValueError("invalid main charge discovery status")
        if bool(self.windows) != (self.status == "discovered"):
            raise ValueError("main charge status must match feasible windows")
        if any(
            w.assignment_id != self.assignment_id or w.schedule.snapshot_id != self.snapshot_id
            for w in self.windows
        ):
            raise ValueError("main windows must share the assignment and snapshot")
        ids = tuple(w.schedule.schedule_id for w in self.windows)
        if len(ids) != len(set(ids)):
            raise ValueError("main window schedules must be unique")
