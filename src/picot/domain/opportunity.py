"""Immutable opportunity records produced by the Opportunity Engine.

Opportunities are objective, evidence-backed and time-bound facts. They never
select devices, assign power or prescribe execution. See ADR-023.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OpportunityKind(StrEnum):
    """Objective opportunity categories currently supported by PicoT."""

    NEGATIVE_PRICE_WINDOW = "negative_price_window"
    LOWEST_PRICE_WINDOW = "lowest_price_window"
    PV_SURPLUS_WINDOW = "pv_surplus_window"


class OpportunityLifecycle(StrEnum):
    """Lifecycle state of an immutable opportunity record."""

    DETECTED = "detected"
    ACTIVE = "active"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class OpportunityMetricKind(StrEnum):
    """Objective metrics that may describe an opportunity."""

    ENERGY_PRICE_EUR_PER_KWH = "energy_price_eur_per_kwh"
    MINIMUM_EXPECTED_POWER_W = "minimum_expected_power_w"


@dataclass(frozen=True, slots=True)
class OpportunityMetric:
    """One typed numeric fact derived for an opportunity."""

    kind: OpportunityMetricKind
    value: float

    def __post_init__(self) -> None:
        if self.kind is OpportunityMetricKind.MINIMUM_EXPECTED_POWER_W and self.value <= 0:
            raise ValueError("Minimum expected power must be greater than zero.")


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Reference to one immutable source record used as evidence."""

    source_id: str
    point_indexes: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("Evidence source ID must not be empty.")
        if not self.point_indexes:
            raise ValueError("Evidence reference requires at least one point index.")
        if any(index < 0 for index in self.point_indexes):
            raise ValueError("Evidence point indexes must not be negative.")
        if tuple(sorted(set(self.point_indexes))) != self.point_indexes:
            raise ValueError("Evidence point indexes must be unique and increasing.")


@dataclass(frozen=True, slots=True)
class Opportunity:
    """One objective planning opportunity linked to its snapshot and evidence."""

    opportunity_id: str
    snapshot_id: str
    kind: OpportunityKind
    starts_at: datetime
    ends_at: datetime
    confidence: float
    lifecycle: OpportunityLifecycle
    evidence: tuple[EvidenceReference, ...]
    metrics: tuple[OpportunityMetric, ...] = ()

    def __post_init__(self) -> None:
        if not self.opportunity_id.strip():
            raise ValueError("Opportunity ID must not be empty.")
        if not self.snapshot_id.strip():
            raise ValueError("Snapshot ID must not be empty.")
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError("Opportunity start must be timezone-aware.")
        if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
            raise ValueError("Opportunity end must be timezone-aware.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Opportunity must end after it starts.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Opportunity confidence must be between 0.0 and 1.0.")
        if not self.evidence:
            raise ValueError("Opportunity requires evidence.")
        metric_kinds = [metric.kind for metric in self.metrics]
        if len(metric_kinds) != len(set(metric_kinds)):
            raise ValueError("Each opportunity metric kind may appear only once.")


@dataclass(frozen=True, slots=True)
class OpportunitySet:
    """Immutable collection produced for one Planning Input Snapshot."""

    snapshot_id: str
    opportunities: tuple[Opportunity, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("Opportunity Set snapshot ID must not be empty.")
        ids = [item.opportunity_id for item in self.opportunities]
        if len(ids) != len(set(ids)):
            raise ValueError("Each opportunity ID may appear only once.")
        if any(item.snapshot_id != self.snapshot_id for item in self.opportunities):
            raise ValueError("Every opportunity must reference the Opportunity Set snapshot.")
