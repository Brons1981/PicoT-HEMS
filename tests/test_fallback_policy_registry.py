from __future__ import annotations

import pytest

from picot.execution.fallback_policy_registry import (
    HOLD_AND_REPLAN_POLICY_ID,
    ExecutionFallbackPolicyRegistry,
)


def test_registry_resolves_canonical_hold_and_replan_policy() -> None:
    policy = ExecutionFallbackPolicyRegistry().resolve(HOLD_AND_REPLAN_POLICY_ID)

    assert policy.policy_id == HOLD_AND_REPLAN_POLICY_ID
    assert policy.version == 1
    assert policy.requests_replan is True
    assert policy.emits_vendor_command is False


def test_registry_rejects_unknown_policy() -> None:
    with pytest.raises(ValueError, match="Unknown execution fallback policy"):
        ExecutionFallbackPolicyRegistry().resolve("execution-fallback:unknown:v1")
