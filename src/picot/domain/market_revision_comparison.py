"""Producer-owned evidence for a remaining today/tomorrow market comparison."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MarketRevisionBasis:
    assignment_id: str
    previous_plan_id: str
    horizon_end: datetime
    required_horizon_end: datetime
    horizon_complete: bool
    original_remaining_export_wh: float
    export_intervals: tuple[tuple[datetime, datetime], ...]
    wear_eur_per_kwh: float = 0.0
    unplanned_assignment_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketRevisionDayResult:
    delivery_date: str
    import_cost_eur: float
    export_revenue_eur: float


@dataclass(frozen=True, slots=True)
class MarketRevisionCandidateEvidence:
    candidate_id: str
    assignment_id: str
    variant: str
    horizon_start: datetime
    horizon_end: datetime
    days: tuple[MarketRevisionDayResult, ...]
    grid_charge_wh: float
    terminal_storage_wh: float
    minimum_storage_wh: float
    wear_cost_eur: float
    comparable_result_eur: float | None
    delta_from_incumbent_eur: float | None
    invalidity_reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
