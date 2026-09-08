"""Durable once-per-rule delivery-day identity; never an execution authority."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from math import isfinite
from typing import Literal
from zoneinfo import ZoneInfo

from picot.domain.market_user_rule import MarketUserRule

MarketAssignmentStatus = Literal["pending", "completed", "skipped", "stopped"]


@dataclass(frozen=True, slots=True)
class MarketDailyAssignment:
    rule: MarketUserRule
    execution_scope_id: str
    delivery_date: date
    timezone: str
    created_at: datetime
    usable_capacity_wh: float
    status: MarketAssignmentStatus = "pending"
    ended_at: datetime | None = None
    outcome_evidence_id: str | None = None
    measured_export_wh: float | None = None

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        if not self.execution_scope_id.strip():
            raise ValueError("market assignment requires an execution scope")
        if self.created_at.utcoffset() is None or self.created_at >= self.ends_at:
            raise ValueError("market assignment must be created before the aware delivery end")
        if not isfinite(self.usable_capacity_wh) or self.usable_capacity_wh <= 0:
            raise ValueError("market assignment requires positive finite usable capacity")
        if self.status not in {"pending", "completed", "skipped", "stopped"}:
            raise ValueError("invalid market assignment status")
        if self.status == "pending":
            if any(
                v is not None
                for v in (self.ended_at, self.outcome_evidence_id, self.measured_export_wh)
            ):
                raise ValueError("pending market assignment cannot claim an outcome")
        else:
            if (
                self.ended_at is None
                or self.ended_at.utcoffset() is None
                or self.ended_at < self.created_at
            ):
                raise ValueError("market outcome requires an aware time after creation")
            if not self.outcome_evidence_id or not self.outcome_evidence_id.strip():
                raise ValueError("market outcome requires explicit evidence")
            if self.status == "skipped" and self.measured_export_wh is not None:
                raise ValueError("skipping cannot claim measured export")
            if self.measured_export_wh is not None and (
                not isfinite(self.measured_export_wh) or self.measured_export_wh < 0
            ):
                raise ValueError("executed market outcome requires measured nonnegative export")
            if self.status == "completed" and (
                self.measured_export_wh is None or self.measured_export_wh == 0
            ):
                raise ValueError("completed market action requires positive measured export")

    @property
    def assignment_id(self) -> str:
        # Revision, price snapshot and process lifetime never replenish the budget.
        fields = (self.rule.rule_id, self.execution_scope_id, self.delivery_date.isoformat())
        seed = "".join(f"{len(value)}:{value}" for value in fields)
        return "market-day:" + sha256(seed.encode()).hexdigest()[:24]

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.delivery_date, time.min, ZoneInfo(self.timezone)).astimezone(
            UTC
        )

    @property
    def ends_at(self) -> datetime:
        return datetime.combine(
            self.delivery_date + timedelta(days=1), time.min, ZoneInfo(self.timezone)
        ).astimezone(UTC)

    @property
    def battery_energy_wh(self) -> float:
        return self.usable_capacity_wh * self.rule.capacity_fraction

    def close(
        self,
        *,
        status: MarketAssignmentStatus,
        at: datetime,
        evidence_id: str,
        measured_export_wh: float | None = None,
    ) -> MarketDailyAssignment:
        if status == "pending":
            raise ValueError("closing cannot reopen a market assignment")
        if self.status != "pending":
            raise ValueError("market outcome is immutable; no second daily budget")
        return replace(
            self,
            status=status,
            ended_at=at,
            outcome_evidence_id=evidence_id,
            measured_export_wh=measured_export_wh,
        )
