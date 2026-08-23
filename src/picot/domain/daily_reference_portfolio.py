"""One observer-only portfolio of independently simulated daily strategies."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.daily_reference_intent import DailyReferenceIntentSchedule
from picot.domain.daily_reference_run import DailyReferenceRun


@dataclass(frozen=True, slots=True)
class DailyReferenceStrategyResult:
    """One complete canonical run tied to its exact physical intent schedule."""

    strategy_result_id: str
    intent_schedule: DailyReferenceIntentSchedule
    run: DailyReferenceRun

    def __post_init__(self) -> None:
        if not self.strategy_result_id.strip():
            raise ValueError("Daily strategy result identity must be explicit.")
        if self.intent_schedule.snapshot_id != self.run.snapshot_id:
            raise ValueError("Daily strategy schedule and run snapshots must match.")
        if any(
            item.intent_schedule_id != self.intent_schedule.schedule_id
            for item in self.run.simulation.trajectories
        ):
            raise ValueError("Daily trajectories must originate from the strategy schedule.")
        if not self.run.candidate_input_complete:
            raise ValueError("Daily strategy result requires a complete canonical run.")
        if not self.run.observer_only or self.run.selection_permitted:
            raise ValueError("Daily strategy result must remain observer-only and unselected.")


@dataclass(frozen=True, slots=True)
class DailyReferencePortfolio:
    """Comparable complete strategy results produced from one shared input state."""

    portfolio_id: str
    snapshot_id: str
    tariff_schedule_id: str
    strategy_results: tuple[DailyReferenceStrategyResult, ...]
    observer_only: bool
    ranking_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.portfolio_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily strategy portfolio identity must be explicit.")
        if not self.tariff_schedule_id.strip() or not self.method_version.strip():
            raise ValueError("Daily strategy portfolio lineage must be explicit.")
        if not self.strategy_results:
            raise ValueError("Daily strategy portfolio requires complete results.")
        schedule_ids = tuple(
            item.intent_schedule.schedule_id for item in self.strategy_results
        )
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("Daily strategy schedules must be unique.")
        if any(item.run.snapshot_id != self.snapshot_id for item in self.strategy_results):
            raise ValueError("Daily strategy results must share one snapshot.")
        if any(
            path.tariff_schedule_id != self.tariff_schedule_id
            for item in self.strategy_results
            for path in item.run.financial.paths
        ):
            raise ValueError("Daily strategy results must share one tariff schedule.")
        if not self.observer_only or self.ranking_permitted:
            raise ValueError("Daily strategy portfolio must remain observer-only and unranked.")
