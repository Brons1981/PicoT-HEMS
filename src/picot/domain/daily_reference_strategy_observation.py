"""Closed observation of one fully simulated independent strategy space."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.daily_reference_observer_result import (
    DailyReferenceObserverResult,
)
from picot.domain.daily_reference_strategy_space import (
    DailyReferenceStrategySpace,
)


@dataclass(frozen=True, slots=True)
class DailyReferenceStrategyObservation:
    """Tie every generated schedule to its complete observer result."""

    observation_id: str
    snapshot_id: str
    strategy_space: DailyReferenceStrategySpace
    observer_result: DailyReferenceObserverResult
    observer_only: bool
    selection_permitted: bool
    commitment_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily strategy observation identity must be explicit.")
        if not self.method_version.strip():
            raise ValueError("Daily strategy observation lineage must be explicit.")
        if self.strategy_space.snapshot_id != self.snapshot_id:
            raise ValueError("Daily strategy space snapshot must match observation.")
        if self.observer_result.snapshot_id != self.snapshot_id:
            raise ValueError("Daily observer snapshot must match strategy space.")
        generated_ids = tuple(
            item.schedule_id for item in self.strategy_space.schedules
        )
        simulated_ids = tuple(
            item.intent_schedule.schedule_id
            for item in self.observer_result.portfolio.strategy_results
        )
        if generated_ids != simulated_ids:
            raise ValueError("Every generated daily strategy must be simulated once.")
        if len(self.observer_result.candidate_set.candidates) != len(generated_ids):
            raise ValueError("Every simulated daily strategy must become a candidate.")
        if len(self.observer_result.evaluation.records) != len(generated_ids):
            raise ValueError("Every daily strategy candidate must be evaluated.")
        if not self.observer_only or self.selection_permitted:
            raise ValueError("Daily strategy observation must remain observer-only.")
        if self.commitment_permitted:
            raise ValueError("Daily strategy observation must not permit commitment.")
