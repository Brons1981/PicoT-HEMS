"""Immutable tariff and grid-permission Planning Input from V2ADR-054."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")


def _evidence(values: tuple[str, ...]) -> None:
    if not values or any(not value.strip() for value in values):
        raise ValueError("Tariff evidence IDs must contain non-empty values.")
    if len(values) != len(set(values)):
        raise ValueError("Tariff evidence IDs must be unique.")


@dataclass(frozen=True, slots=True)
class EnergyTariffInterval:
    """Uncombined tariff components applicable to one settlement interval."""

    starts_at: datetime
    ends_at: datetime
    commodity_import_eur_per_kwh: float
    commodity_export_eur_per_kwh: float
    supplier_import_eur_per_kwh: float
    supplier_export_eur_per_kwh: float
    energy_tax_import_eur_per_kwh: float
    export_charge_eur_per_kwh: float
    transaction_fee_import_eur_per_kwh: float
    transaction_fee_export_eur_per_kwh: float
    vat_rate: float
    price_components_include_vat: bool
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.starts_at, "Tariff interval start")
        _aware(self.ends_at, "Tariff interval end")
        if self.ends_at <= self.starts_at:
            raise ValueError("Tariff interval must end after it starts.")
        if not 0.0 <= self.vat_rate <= 1.0:
            raise ValueError("VAT rate must be between 0.0 and 1.0.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Tariff confidence must be between 0.0 and 1.0.")
        _evidence(self.evidence_ids)

    @classmethod
    def basic(
        cls,
        *,
        starts_at: datetime,
        ends_at: datetime,
        import_eur_per_kwh: float,
        export_eur_per_kwh: float,
        evidence_ids: tuple[str, ...],
    ) -> EnergyTariffInterval:
        """Construct a fully specified interval from already-combined VAT prices."""

        return cls(
            starts_at=starts_at,
            ends_at=ends_at,
            commodity_import_eur_per_kwh=import_eur_per_kwh,
            commodity_export_eur_per_kwh=export_eur_per_kwh,
            supplier_import_eur_per_kwh=0.0,
            supplier_export_eur_per_kwh=0.0,
            energy_tax_import_eur_per_kwh=0.0,
            export_charge_eur_per_kwh=0.0,
            transaction_fee_import_eur_per_kwh=0.0,
            transaction_fee_export_eur_per_kwh=0.0,
            vat_rate=0.0,
            price_components_include_vat=True,
            confidence=1.0,
            evidence_ids=evidence_ids,
        )


@dataclass(frozen=True, slots=True)
class EnergyContractSnapshot:
    """Atomic contract permissions and tariff schedule for one Planner snapshot."""

    contract_snapshot_id: str
    captured_at: datetime
    valid_from: datetime
    valid_until: datetime
    settlement_timezone: str
    settlement_rule_id: str
    contract_version: str
    permits_grid_import: bool
    permits_grid_export: bool
    permits_battery_export: bool
    intervals: tuple[EnergyTariffInterval, ...]

    def __post_init__(self) -> None:
        for text_value, label in (
            (self.contract_snapshot_id, "Contract Snapshot ID"),
            (self.settlement_timezone, "Settlement timezone"),
            (self.settlement_rule_id, "Settlement rule ID"),
            (self.contract_version, "Contract version"),
        ):
            if not text_value.strip():
                raise ValueError(f"{label} must not be empty.")
        for time_value, label in (
            (self.captured_at, "Contract capture time"),
            (self.valid_from, "Contract validity start"),
            (self.valid_until, "Contract validity end"),
        ):
            _aware(time_value, label)
        if self.valid_until <= self.valid_from:
            raise ValueError("Contract validity must end after it starts.")
        try:
            ZoneInfo(self.settlement_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Settlement timezone must be a valid IANA timezone.") from exc
        if self.permits_battery_export and not self.permits_grid_export:
            raise ValueError("Battery export requires grid export permission.")
        if not self.intervals:
            raise ValueError("Energy Contract Snapshot requires tariff intervals.")
        ordered = sorted(self.intervals, key=lambda item: item.starts_at)
        if list(self.intervals) != ordered:
            raise ValueError("Tariff intervals must be time ordered.")
        if any(
            interval.starts_at < self.valid_from or interval.ends_at > self.valid_until
            for interval in self.intervals
        ):
            raise ValueError("Tariff intervals must remain within contract validity.")
        if any(
            left.ends_at > right.starts_at
            for left, right in zip(self.intervals, self.intervals[1:], strict=False)
        ):
            raise ValueError("Tariff intervals may not overlap.")
