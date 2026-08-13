"""Immutable execution fallback policy registry defined by ADR-046."""

from __future__ import annotations

from dataclasses import dataclass

HOLD_AND_REPLAN_POLICY_ID = "execution-fallback:hold-and-replan:v1"


@dataclass(frozen=True, slots=True)
class ExecutionFallbackPolicy:
    """One immutable, versioned execution fallback policy definition."""

    policy_id: str
    version: int
    action: str
    requests_replan: bool
    emits_vendor_command: bool

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("Fallback policy ID must not be empty.")
        if self.version < 1:
            raise ValueError("Fallback policy version must be at least 1.")
        if not self.action.strip():
            raise ValueError("Fallback policy action must not be empty.")
        if self.emits_vendor_command:
            raise ValueError("ADR-046 fallback policies may not emit vendor commands.")


class ExecutionFallbackPolicyRegistry:
    """Resolve code-owned immutable ADR-046 fallback policy definitions."""

    def __init__(self) -> None:
        policy = ExecutionFallbackPolicy(
            policy_id=HOLD_AND_REPLAN_POLICY_ID,
            version=1,
            action="hold_observed_state_and_replan",
            requests_replan=True,
            emits_vendor_command=False,
        )
        self._policies = {policy.policy_id: policy}

    def resolve(self, policy_id: str) -> ExecutionFallbackPolicy:
        """Return exactly one known policy or fail closed."""

        if not policy_id.strip():
            raise ValueError("Fallback policy ID must not be empty.")
        try:
            return self._policies[policy_id]
        except KeyError as exc:
            raise ValueError(f"Unknown execution fallback policy: {policy_id}") from exc
