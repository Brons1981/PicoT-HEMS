"""Auditable cost basis for the energy currently stored in a battery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class StorageEnergyLot:
    source: str
    stored_energy_wh: float
    acquisition_cost_eur: float | None
    acquired_at: datetime
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.source not in {"pv", "grid", "unknown"}:
            raise ValueError("storage energy source must be pv, grid, or unknown")
        if not isfinite(self.stored_energy_wh) or self.stored_energy_wh <= 0.0:
            raise ValueError("storage energy lot must contain positive energy")
        if self.acquisition_cost_eur is not None and not isfinite(
            self.acquisition_cost_eur
        ):
            raise ValueError("storage acquisition cost must be finite")
        if self.acquired_at.tzinfo is None or self.acquired_at.utcoffset() is None:
            raise ValueError("storage acquisition time must be timezone-aware")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("storage energy lot requires explicit evidence")
        if self.source == "unknown" and self.acquisition_cost_eur is not None:
            raise ValueError("unknown storage energy may not invent a cost basis")
        if self.source != "unknown" and self.acquisition_cost_eur is None:
            raise ValueError("known storage energy requires a cost basis")

    @property
    def cost_eur_per_stored_kwh(self) -> float | None:
        if self.acquisition_cost_eur is None:
            return None
        return self.acquisition_cost_eur / (self.stored_energy_wh / 1000.0)


@dataclass(frozen=True, slots=True)
class StorageEnergyCostAllocation:
    stored_energy_wh: float
    deliverable_energy_wh: float
    acquisition_cost_eur: float
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StorageEnergyInventory:
    execution_scope_id: str
    captured_at: datetime
    measured_stored_energy_wh: float
    lots: tuple[StorageEnergyLot, ...]
    method_version: str = "measured-storage-energy-inventory:v1"

    def __post_init__(self) -> None:
        if not self.execution_scope_id.strip() or not self.method_version.strip():
            raise ValueError("storage inventory lineage must be explicit")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("storage inventory capture time must be timezone-aware")
        if (
            not isfinite(self.measured_stored_energy_wh)
            or self.measured_stored_energy_wh < 0.0
        ):
            raise ValueError("measured stored energy must be non-negative")
        accounted = sum(item.stored_energy_wh for item in self.lots)
        if abs(accounted - self.measured_stored_energy_wh) > 1.0:
            raise ValueError("storage inventory lots must reconcile with measured energy")

    @property
    def known_stored_energy_wh(self) -> float:
        return sum(
            item.stored_energy_wh
            for item in self.lots
            if item.acquisition_cost_eur is not None
        )

    def cheapest_known_allocation(
        self,
        *,
        maximum_deliverable_energy_wh: float,
        discharge_efficiency: float,
    ) -> StorageEnergyCostAllocation:
        if maximum_deliverable_energy_wh < 0.0:
            raise ValueError("maximum deliverable energy must be non-negative")
        if not 0.0 < discharge_efficiency <= 1.0:
            raise ValueError("discharge efficiency must be in (0, 1]")
        requested_stored_wh = maximum_deliverable_energy_wh / discharge_efficiency
        remaining_wh = min(requested_stored_wh, self.known_stored_energy_wh)
        allocated_wh = 0.0
        cost_eur = 0.0
        sources: list[str] = []
        known = sorted(
            (item for item in self.lots if item.acquisition_cost_eur is not None),
            key=lambda item: (
                float(item.cost_eur_per_stored_kwh or 0.0),
                item.acquired_at,
                item.source,
            ),
        )
        for lot in known:
            if remaining_wh <= 0.0:
                break
            take_wh = min(remaining_wh, lot.stored_energy_wh)
            assert lot.acquisition_cost_eur is not None
            cost_eur += lot.acquisition_cost_eur * take_wh / lot.stored_energy_wh
            allocated_wh += take_wh
            remaining_wh -= take_wh
            if lot.source not in sources:
                sources.append(lot.source)
        return StorageEnergyCostAllocation(
            stored_energy_wh=allocated_wh,
            deliverable_energy_wh=allocated_wh * discharge_efficiency,
            acquisition_cost_eur=cost_eur,
            sources=tuple(sources),
        )
