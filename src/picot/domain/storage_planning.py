"""Immutable storage-planning facts defined by ADR-037."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EnergyRequirementKind(StrEnum):
    MINIMUM_RESERVE = "minimum_reserve"
    TARGET_SOC = "target_soc"
    RECOVERY_TARGET = "recovery_target"


@dataclass(frozen=True, slots=True)
class StoragePlanningState:
    """Observed storage state used only for planning/projection."""

    capability_id: str
    current_soc: float
    usable_capacity_wh: float
    measured_at: datetime
    confidence: float
    source_version: str
    charge_efficiency: float | None = None
    discharge_efficiency: float | None = None

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("Storage capability ID must not be empty.")
        if not 0.0 <= self.current_soc <= 1.0:
            raise ValueError("Storage SoC must be between 0.0 and 1.0.")
        if self.usable_capacity_wh <= 0:
            raise ValueError("Usable storage capacity must be greater than zero.")
        if self.measured_at.tzinfo is None or self.measured_at.utcoffset() is None:
            raise ValueError("Storage state time must be timezone-aware.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Storage state confidence must be between 0.0 and 1.0.")
        if not self.source_version.strip():
            raise ValueError("Storage state source version must not be empty.")
        for value, label in (
            (self.charge_efficiency, "Charge efficiency"),
            (self.discharge_efficiency, "Discharge efficiency"),
        ):
            if value is not None and not 0.0 < value <= 1.0:
                raise ValueError(f"{label} must be greater than 0.0 and at most 1.0.")


@dataclass(frozen=True, slots=True)
class EnergyRequirement:
    """Explicit future storage-state requirement; never created from price alone."""

    requirement_id: str
    capability_id: str
    kind: EnergyRequirementKind
    deadline: datetime
    target_soc: float
    hard: bool
    confidence: float
    source_version: str

    def __post_init__(self) -> None:
        if not self.requirement_id.strip():
            raise ValueError("Energy requirement ID must not be empty.")
        if not self.capability_id.strip():
            raise ValueError("Energy requirement capability ID must not be empty.")
        if self.deadline.tzinfo is None or self.deadline.utcoffset() is None:
            raise ValueError("Energy requirement deadline must be timezone-aware.")
        if not 0.0 <= self.target_soc <= 1.0:
            raise ValueError("Energy requirement target SoC must be between 0.0 and 1.0.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Energy requirement confidence must be between 0.0 and 1.0.")
        if not self.source_version.strip():
            raise ValueError("Energy requirement source version must not be empty.")
