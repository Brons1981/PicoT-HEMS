"""Effective storage planning limit used by ADR-037 requirement derivation."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.current_storage_state import CurrentStorageState


@dataclass(frozen=True, slots=True)
class EffectiveStorageLimit:
    """Maximum storage level PicoT may target for one Planner Run.

    This is a planning boundary, not a second representation of current battery
    state. CurrentStorageState remains authoritative for what is stored now.
    """

    limit_id: str
    execution_scope_id: str
    max_soc: float
    usable_capacity_wh: float
    confidence: float
    evidence_ids: tuple[str, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.limit_id.strip():
            raise ValueError("Effective storage limit ID must not be empty.")
        if not self.execution_scope_id.strip():
            raise ValueError("Execution scope ID must not be empty.")
        if not 0.0 < self.max_soc <= 1.0:
            raise ValueError("Effective maximum SoC must be above 0.0 and at most 1.0.")
        if self.usable_capacity_wh <= 0:
            raise ValueError("Usable storage capacity must be positive.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Effective storage limit confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids:
            raise ValueError("Effective storage limit requires evidence IDs.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Effective storage limit evidence IDs must not be empty.")
        if not self.method_version.strip():
            raise ValueError("Effective storage limit method version must not be empty.")

    @property
    def max_energy_wh(self) -> float:
        """Return the maximum energy the Planner may target for this run."""

        return self.max_soc * self.usable_capacity_wh

    def validate_against(self, storage_state: CurrentStorageState) -> None:
        """Require the limit and current state to describe the same storage scope."""

        if self.execution_scope_id != storage_state.execution_scope_id:
            raise ValueError("Effective storage limit and current state must share a scope.")
        if self.usable_capacity_wh != storage_state.usable_capacity_wh:
            raise ValueError(
                "Effective storage limit must use the canonical usable storage capacity."
            )
