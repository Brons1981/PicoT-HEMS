"""Explicit observer-only search space for independent daily strategies."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)


@dataclass(frozen=True, slots=True)
class DailyReferenceStrategySpace:
    """Unranked interval-aligned strategy schedules from one shared snapshot."""

    strategy_space_id: str
    snapshot_id: str
    baseline_intent: DailyStorageIntent
    active_intents: tuple[DailyStorageIntent, ...]
    window_lengths_intervals: tuple[int, ...]
    schedules: tuple[DailyReferenceIntentSchedule, ...]
    observer_only: bool
    ranking_permitted: bool
    method_version: str
    source_charge_window_set_id: str | None = None
    charge_requirement_status: str = "required"

    def __post_init__(self) -> None:
        if not self.strategy_space_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily strategy space identity must be explicit.")
        if not self.method_version.strip() or not self.schedules:
            raise ValueError("Daily strategy space requires schedules and lineage.")
        if (
            self.source_charge_window_set_id is not None
            and not self.source_charge_window_set_id.strip()
        ):
            raise ValueError("Daily strategy charge window lineage must be explicit.")
        if self.baseline_intent is not DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY:
            raise ValueError("Daily strategy baseline must be household support only.")
        if self.charge_requirement_status not in {"required", "not_required"}:
            raise ValueError("Daily strategy charge requirement status is invalid.")
        if self.charge_requirement_status == "required" and (
            not self.active_intents
            or len(self.active_intents) != len(set(self.active_intents))
        ):
            raise ValueError(
                "Daily strategy active intents must be explicit and unique."
            )
        if self.charge_requirement_status == "not_required" and (
            self.active_intents
            or self.window_lengths_intervals
            or len(self.schedules) != 1
        ):
            raise ValueError("Daily strategy without charge must contain only baseline.")
        if self.baseline_intent in self.active_intents:
            raise ValueError("Daily strategy active intents must differ from baseline.")
        if self.charge_requirement_status == "required" and (
            not self.window_lengths_intervals
            or any(item <= 0 for item in self.window_lengths_intervals)
        ):
            raise ValueError("Daily strategy window lengths must be positive.")
        if len(self.window_lengths_intervals) != len(
            set(self.window_lengths_intervals)
        ):
            raise ValueError("Daily strategy window lengths must be unique.")
        schedule_ids = tuple(item.schedule_id for item in self.schedules)
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("Daily strategy schedules must be unique.")
        if any(item.snapshot_id != self.snapshot_id for item in self.schedules):
            raise ValueError("Daily strategy schedules must share one snapshot.")
        if not self.observer_only or self.ranking_permitted:
            raise ValueError(
                "Daily strategy space must remain observer-only and unranked."
            )
