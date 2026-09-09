"""Explicit market instructions and price evidence (ADR-019.1–019.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class MarketUserRule:
    rule_id: str
    revision: int
    capacity_fraction: float
    minimum_spread_eur_per_kwh: float
    recovery_required: bool = False
    minimum_net_margin_eur_per_export_kwh: float = 0.05

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or isinstance(self.revision, bool) or self.revision < 1:
            raise ValueError("market rule requires an explicit identity and revision")
        if not isinstance(self.recovery_required, bool):
            raise ValueError("recovery choice must be boolean")
        if not 0 < self.capacity_fraction <= 1:
            raise ValueError("market amount must be a positive fraction of usable capacity")
        for value in (self.minimum_spread_eur_per_kwh, self.minimum_net_margin_eur_per_export_kwh):
            if not isfinite(value) or value < 0:
                raise ValueError("market thresholds must be finite nonnegative EUR/kWh")


@dataclass(frozen=True, slots=True)
class MarketPricePart:
    starts_at: datetime
    ends_at: datetime
    grid_energy_wh: float
    price_eur_per_kwh: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.starts_at.utcoffset() is None or self.ends_at.utcoffset() is None:
            raise ValueError("market price evidence requires aware boundaries")
        if self.ends_at <= self.starts_at:
            raise ValueError("market price evidence requires positive duration")
        if not isfinite(self.grid_energy_wh) or self.grid_energy_wh <= 0:
            raise ValueError("market grid energy must be finite and positive")
        if not isfinite(self.price_eur_per_kwh) or not self.evidence_ids:
            raise ValueError("market price and source evidence must be explicit")


@dataclass(frozen=True, slots=True)
class MarketPriceWindow:
    parts: tuple[MarketPricePart, ...]
    fictitious: bool

    def __post_init__(self) -> None:
        if not self.parts or any(
            a.ends_at != b.starts_at for a, b in zip(self.parts, self.parts[1:], strict=False)
        ):
            raise ValueError("market window must be contiguous")

    @property
    def starts_at(self) -> datetime:
        return self.parts[0].starts_at

    @property
    def ends_at(self) -> datetime:
        return self.parts[-1].ends_at

    @property
    def grid_energy_wh(self) -> float:
        return sum(p.grid_energy_wh for p in self.parts)

    @property
    def average_eur_per_kwh(self) -> float:
        return sum(p.grid_energy_wh * p.price_eur_per_kwh for p in self.parts) / self.grid_energy_wh


@dataclass(frozen=True, slots=True)
class MarketSpreadEvidence:
    rule_id: str
    rule_revision: int
    snapshot_id: str
    battery_energy_wh: float
    conversion_model_id: str
    conversion_evidence_ids: tuple[str, ...]
    charge_power_w: float
    discharge_power_w: float
    export_window: MarketPriceWindow
    reference_window: MarketPriceWindow
    minimum_spread_eur_per_kwh: float

    def __post_init__(self) -> None:
        if self.export_window.fictitious or not self.reference_window.fictitious:
            raise ValueError("only the import reference is fictitious")
        if not self.rule_id or not self.snapshot_id or not self.conversion_evidence_ids:
            raise ValueError("market spread requires rule, input and conversion lineage")

    @property
    def spread_eur_per_kwh(self) -> float:
        return self.export_window.average_eur_per_kwh - self.reference_window.average_eur_per_kwh

    @property
    def meets_spread(self) -> bool:
        return self.spread_eur_per_kwh >= self.minimum_spread_eur_per_kwh
