"""Explicit tariff evidence for independent daily reference valuation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class DailyReferenceTariffInterval:
    """All-in import and export rates proven for one physical interval."""

    starts_at: datetime
    ends_at: datetime
    import_eur_per_kwh: float
    export_eur_per_kwh: float
    confidence: float
    evidence_ids: tuple[str, ...]
    same_interval_offset_eur_per_kwh: float | None = None
    cross_interval_export_eur_per_kwh: float | None = None
    saldering_tax_eur_per_kwh: float = 0.0

    def __post_init__(self) -> None:
        _aware(self.starts_at, "Daily tariff start")
        _aware(self.ends_at, "Daily tariff end")
        if self.ends_at <= self.starts_at:
            raise ValueError("Daily tariff interval must end after it starts.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Daily tariff confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("Daily tariff evidence must be explicit.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Daily tariff evidence IDs must be unique.")
        if self.saldering_tax_eur_per_kwh < 0.0:
            raise ValueError("Daily tariff saldering tax must not be negative.")


@dataclass(frozen=True, slots=True)
class DailyReferenceTariffSchedule:
    """Complete immutable tariff schedule for one simulation horizon."""

    schedule_id: str
    snapshot_id: str
    horizon_start: datetime
    horizon_end: datetime
    intervals: tuple[DailyReferenceTariffInterval, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.schedule_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily tariff identity must be explicit.")
        _aware(self.horizon_start, "Daily tariff horizon start")
        _aware(self.horizon_end, "Daily tariff horizon end")
        if self.horizon_end <= self.horizon_start or not self.intervals:
            raise ValueError("Daily tariff schedule requires a complete horizon.")
        if self.intervals[0].starts_at != self.horizon_start:
            raise ValueError("Daily tariff schedule must start at its horizon.")
        if self.intervals[-1].ends_at != self.horizon_end:
            raise ValueError("Daily tariff schedule must end at its horizon.")
        if any(
            left.ends_at != right.starts_at
            for left, right in zip(self.intervals, self.intervals[1:], strict=False)
        ):
            raise ValueError("Daily tariff intervals must be contiguous.")
        if not self.method_version.strip():
            raise ValueError("Daily tariff method version must be explicit.")
