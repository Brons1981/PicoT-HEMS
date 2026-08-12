"""Storage-energy requirement and charge-source policy from ADR-037."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class StorageRequirementReason(StrEnum):
    """Initial reason categories for a future stored-energy requirement."""

    HOUSEHOLD_DEMAND = "household_demand"
    CONSERVATIVE_RESERVE = "conservative_reserve"
    BATTERY_HEALTH = "battery_health"
    USER_REQUIREMENT = "user_requirement"


class ChargeSourcePolicy(StrEnum):
    """Explicit energy-source permission for an active charging path."""

    PV_ONLY = "pv_only"
    PV_PREFERRED_GRID_ALLOWED = "pv_preferred_grid_allowed"


@dataclass(frozen=True, slots=True)
class StorageEnergyRequirement:
    """Stored energy that must be available by a future time.

    This is planning evidence, not a charge command and not a grid-charging
    instruction.
    """

    requirement_id: str
    required_by: datetime
    required_energy_wh: float
    required_soc_percent: float | None
    reason: StorageRequirementReason
    confidence: float
    evidence_ids: tuple[str, ...]
    reserve_energy_wh: float = 0.0

    def __post_init__(self) -> None:
        if not self.requirement_id.strip():
            raise ValueError("Storage requirement ID must not be empty.")
        if self.required_by.tzinfo is None or self.required_by.utcoffset() is None:
            raise ValueError("Storage requirement deadline must be timezone-aware.")
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
