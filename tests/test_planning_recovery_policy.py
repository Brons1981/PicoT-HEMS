"""Characterise retained-plan failure decisions independently of pipeline flags."""

import pytest

from picot.v2.planning_recovery import failed_plan_change_blocks_execution


@pytest.mark.parametrize("has_plan, optional, charging, shortfall, blocked", [
    (False, False, False, False, True),
    (False, True, False, False, True),
    (False, False, True, False, True),
    (True, False, False, False, True),
    (True, True, False, False, False),
    (True, False, True, False, False),
    (True, True, True, False, False),
    (True, True, False, True, True),
    (True, False, True, True, True),
])
def test_failure_decision(has_plan, optional, charging, shortfall, blocked):
    assert failed_plan_change_blocks_execution(
        has_retained_plan=has_plan, optional_change=optional,
        continuing_charge=charging, current_shortfall=shortfall,
    ) is blocked
