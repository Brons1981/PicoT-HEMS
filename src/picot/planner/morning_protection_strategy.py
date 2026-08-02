"""Deterministic Morning Protection Strategy defined by PEP-PS-001."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from picot.domain.execution_primitive import ExecutionPrimitive

STRATEGY_ID = "morning-protection"
STRATEGY_VERSION = 1


@dataclass(frozen=True, slots=True)
class MorningProtectionStrategyConfig:
    """Immutable configuration for the first live validation strategy."""

    switch_time: time
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.switch_time.tzinfo is not None:
            raise ValueError("Morning Protection switch time must be a local wall-clock time.")


@dataclass(frozen=True, slots=True)
class MorningProtectionDecision:
    """Traceable outcome of one Morning Protection evaluation."""

    strategy_id: str
    strategy_version: int
    evaluated_at: datetime
    switch_time: time
    primitive: ExecutionPrimitive | None
    reason: str
    next_evaluation_at: datetime | None

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("Strategy ID must not be empty.")
        if self.strategy_version < 1:
            raise ValueError("Strategy version must be at least 1.")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("Strategy evaluation time must be timezone-aware.")
        if not self.reason.strip():
            raise ValueError("Strategy decision reason must not be empty.")
        if self.next_evaluation_at is not None:
            if (
                self.next_evaluation_at.tzinfo is None
                or self.next_evaluation_at.utcoffset() is None
            ):
                raise ValueError("Next evaluation time must be timezone-aware.")
            if self.next_evaluation_at <= self.evaluated_at:
                raise ValueError("Next evaluation time must be later than evaluation time.")


class MorningProtectionStrategy:
    """Choose one of two vendor-independent battery behaviours."""

    def evaluate(
        self,
        config: MorningProtectionStrategyConfig,
        *,
        evaluated_at: datetime,
    ) -> MorningProtectionDecision:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("Strategy evaluation time must be timezone-aware.")

        if not config.enabled:
            return MorningProtectionDecision(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                evaluated_at=evaluated_at,
                switch_time=config.switch_time,
                primitive=None,
                reason="Morning Protection Strategy is disabled.",
                next_evaluation_at=None,
            )

        local_switch = evaluated_at.replace(
            hour=config.switch_time.hour,
            minute=config.switch_time.minute,
            second=config.switch_time.second,
            microsecond=config.switch_time.microsecond,
        )
        if evaluated_at < local_switch:
            return MorningProtectionDecision(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                evaluated_at=evaluated_at,
                switch_time=config.switch_time,
                primitive=ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
                reason="Current local time is before the configured switch time.",
                next_evaluation_at=local_switch,
            )

        return MorningProtectionDecision(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            evaluated_at=evaluated_at,
            switch_time=config.switch_time,
            primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
            reason="Current local time is at or after the configured switch time.",
            next_evaluation_at=None,
        )
