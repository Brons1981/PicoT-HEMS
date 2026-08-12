"""Immutable current storage state from ADR-038."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CurrentStorageState:
    """Vendor-independent current energy state for one logical storage scope."""

    storage_state_id: str
    execution_scope_id: str
    capability_id: str
    current_soc: float
    usable_capacity_wh: float
    measured_at: datetime
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.storage_state_id.strip():
            raise ValueError("Storage state ID must not be empty.")
        if not self.execution_scope_id.strip():
            raise ValueError("Execution scope ID must not be empty.")
        if not self.capability_id.strip():
            raise ValueError("Storage capability ID must not be empty.")
        if not 0.0 <= self.current_soc <= 1.0:
            raise ValueError("Current storage SoC must be between 0.0 and 1.0.")
        if self.usable_capacity_wh <= 0:
            raise ValueError("Usable storage capacity must be positive.")
        if self.measured_at.tzinfo is None or self.measured_at.utcoffset() is None:
            raise ValueError("Storage state measurement time must be timezone-aware.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Storage state confidence must be between 0.0 and 1.0.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Storage state evidence IDs must not be empty.")

    @property
    def current_stored_energy_wh(self) -> float:
        """Return the canonical SoC-to-energy derivation owned by the domain."""

        return self.current_soc * self.usable_capacity_wh
