"""Observed market execution; forecasts never become measured export."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class MarketExecutionProgress:
    assignment_id: str
    started_at: datetime | None = None
    stop_requested_at: datetime | None = None
    stopped_at: datetime | None = None
    measured_export_wh: float | None = None
    reason: str | None = None
    measurement_unavailable: bool = False

    def __post_init__(self) -> None:
        if self.measurement_unavailable and (
            self.stopped_at is None or self.measured_export_wh is not None
        ):
            raise ValueError(
                "unavailable final measurement requires an observed stop and no amount"
            )
        if not self.assignment_id.strip():
            raise ValueError("market progress requires its daily identity")
        for at in (self.started_at, self.stop_requested_at, self.stopped_at):
            if at is not None and at.utcoffset() is None:
                raise ValueError("market execution timestamps must be aware")
        if self.stopped_at is not None and (
            self.started_at is None or self.stopped_at < self.started_at
        ):
            raise ValueError("measured stop cannot precede observed start")
        if self.measured_export_wh is not None and (
            self.started_at is None
            or not isfinite(self.measured_export_wh)
            or self.measured_export_wh < 0
        ):
            raise ValueError("market export needs actual execution and finite nonnegative energy")
        if self.stop_requested_at is not None and not self.reason:
            raise ValueError("market stop requires a reason")
