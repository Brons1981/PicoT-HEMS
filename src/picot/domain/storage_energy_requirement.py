"""Storage-energy requirement contract from ADR-037 and ADR-043."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.charge_source_policy import ChargeSourcePolicy


class StorageRequirementReason(StrEnum):
    """Initial reason categories for a future stored-energy requirement."""

    HOUSEHOLD_DEMAND = "household_demand"
    CONSERVATIVE_RESERVE = "conservative_reserve"
    BATTERY_HEALTH = "battery_health"
    USER_REQUIREMENT = "user_requirement"


@dataclass(frozen=True, slots=True)
class StorageEnergyRequirement:
    """Stored energy required across a protected future interval.

    This is planning evidence, not a charge command and not a grid-charging
    instruction. Acquisition urgency is derived separately from current storage.
    """

    requirement_id: str
    protection_starts_at: datetime
    protected_through: datetime
    required_energy_wh: float
    required_soc_percent: float | None
    reason: StorageRequirementReason
    confidence: float
    evidence_ids: tuple[str, ...]
    reserve_energy_wh: float = 0.0

    def __post_init__(self) -> None:
        if not self.requirement_id.strip():
            raise ValueError("Storage requirement ID must not be empty.")
        for name, value in (
            ("protection start", self.protection_starts_at),
            ("protected-through time", self.protected_through),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"Storage requirement {name} must be timezone-aware.")
        if self.protected_through < self.protection_starts_at:
            raise ValueError("Storage protection end must not precede its start.")
        if self.required_energy_wh < 0:
            raise ValueError("Required storage energy must not be negative.")
        if self.required_soc_percent is not None and not 0.0 <= self.required_soc_percent <= 100.0:
            raise ValueError("Required storage SoC must be between 0 and 100 percent.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Storage requirement confidence must be between 0.0 and 1.0.")
        if self.reserve_energy_wh < 0:
            raise ValueError("Reserve energy must not be negative.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Storage requirement evidence IDs must not be empty.")


__all__ = [
    "ChargeSourcePolicy",
    "StorageEnergyRequirement",
    "StorageRequirementReason",
]
