from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.morning_protection_strategy import (
    MorningProtectionStrategy,
    MorningProtectionStrategyConfig,
)

SWITCH_TIME = time(11, 0)


def test_before_switch_time_selects_discharge_only() -> None:
    decision = MorningProtectionStrategy().evaluate(
        MorningProtectionStrategyConfig(switch_time=SWITCH_TIME),
        evaluated_at=datetime(2026, 8, 2, 8, 30, tzinfo=UTC),
    )

    assert decision.primitive is ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
    assert decision.next_evaluation_at == datetime(2026, 8, 2, 11, 0, tzinfo=UTC)
    assert "before" in decision.reason


def test_at_switch_time_selects_bidirectional() -> None:
    decision = MorningProtectionStrategy().evaluate(
        MorningProtectionStrategyConfig(switch_time=SWITCH_TIME),
        evaluated_at=datetime(2026, 8, 2, 11, 0, tzinfo=UTC),
    )

    assert decision.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    assert decision.next_evaluation_at is None
    assert "at or after" in decision.reason


def test_after_switch_time_selects_bidirectional() -> None:
    decision = MorningProtectionStrategy().evaluate(
        MorningProtectionStrategyConfig(switch_time=SWITCH_TIME),
        evaluated_at=datetime(2026, 8, 2, 12, 15, tzinfo=UTC),
    )

    assert decision.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL


def test_disabled_strategy_produces_no_primitive() -> None:
    decision = MorningProtectionStrategy().evaluate(
        MorningProtectionStrategyConfig(switch_time=SWITCH_TIME, enabled=False),
        evaluated_at=datetime(2026, 8, 2, 8, 30, tzinfo=UTC),
    )

    assert decision.primitive is None
    assert decision.next_evaluation_at is None
    assert "disabled" in decision.reason


def test_strategy_rejects_naive_evaluation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MorningProtectionStrategy().evaluate(
            MorningProtectionStrategyConfig(switch_time=SWITCH_TIME),
            evaluated_at=datetime(2026, 8, 2, 8, 30),
        )


def test_config_rejects_timezone_aware_switch_time() -> None:
    with pytest.raises(ValueError, match="wall-clock"):
        MorningProtectionStrategyConfig(switch_time=time(11, 0, tzinfo=UTC))
