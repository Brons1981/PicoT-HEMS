"""Immutable directional storage-conversion evidence from V2ADR-054."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StorageConversionModel:
    """Versioned charge and discharge conversion efficiencies."""

    model_id: str
    charge_efficiency: float
    discharge_efficiency: float
    evidence_ids: tuple[str, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("Storage conversion model ID must not be empty.")
        for value, label in (
            (self.charge_efficiency, "Charge efficiency"),
            (self.discharge_efficiency, "Discharge efficiency"),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{label} must be greater than 0.0 and at most 1.0.")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("Storage conversion evidence IDs must contain values.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Storage conversion evidence IDs must be unique.")
        if not self.method_version.strip():
            raise ValueError("Storage conversion method version must not be empty.")
