"""Physically discovered minimal charge windows for the daily simulator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import PVScenario


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
