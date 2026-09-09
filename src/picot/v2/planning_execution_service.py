"""Service existing execution between market alternatives, on the same thread."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.pipeline import PlanningInputSuperseded


@dataclass
class PlanningExecutionService:
    refresh: Callable[[], PlanningInputSnapshot]
    advance: Callable[[PlanningInputSnapshot], bool]
    now: Callable[[], datetime]
    poll_interval_seconds: float
    next_check_at: datetime

    def checkpoint(self) -> None:
        if self.now() < self.next_check_at:
            return
        observed = self.refresh()
        changed = self.advance(observed)
        next_poll = observed.captured_at + timedelta(seconds=self.poll_interval_seconds)
        context = observed.daily_charge_context
        boundaries = (
            [
                s.ends_at
                for p in context.main_plans
                for s in p.segments
                if s.ends_at > observed.captured_at
            ]
            if context is not None
            else []
        )
        self.next_check_at = min([next_poll, *boundaries])
        if changed:
            # The caller retries from new immutable input. No candidate based
            # on pre-completion ownership may be committed after this point.
            raise PlanningInputSuperseded("execution ownership changed while planning")
