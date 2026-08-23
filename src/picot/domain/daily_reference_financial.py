"""Observer-only financial outcomes for independent physical daily paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isclose

from picot.domain.daily_reference_simulation import PVScenario

EUR_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class DailyReferenceFinancialInterval:
    """Traceable tariff valuation of one conserved physical interval."""

    starts_at: datetime
    ends_at: datetime
    import_eur_per_kwh: float
    export_eur_per_kwh: float
    grid_import_cost_eur: float
    grid_export_result_eur: float
    avoided_import_value_eur: float
    pv_storage_opportunity_cost_eur: float
    conversion_loss_value_eur: float
    net_financial_result_eur: float
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ends_at <= self.starts_at:
            raise ValueError("Daily financial interval must have positive duration.")
        expected = (
            self.grid_export_result_eur
            + self.avoided_import_value_eur
            - self.grid_import_cost_eur
        )
        if not isclose(
            self.net_financial_result_eur,
            expected,
            rel_tol=1e-9,
            abs_tol=EUR_TOLERANCE,
        ):
            raise ValueError("Daily interval financial result does not reconcile.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Daily financial confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids or len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Daily financial evidence must be explicit and unique.")


@dataclass(frozen=True, slots=True)
class DailyReferenceFinancialPath:
    """Complete financial valuation of one physical uncertainty trajectory."""

    financial_path_id: str
    trajectory_id: str
    snapshot_id: str
    tariff_schedule_id: str
    scenario: PVScenario
    average_import_eur_per_kwh: float
    average_export_eur_per_kwh: float
    grid_import_cost_eur: float
    grid_export_result_eur: float
    avoided_import_value_eur: float
    pv_storage_opportunity_cost_eur: float
    conversion_loss_value_eur: float
    net_financial_result_eur: float
    confidence: float
    intervals: tuple[DailyReferenceFinancialInterval, ...]
    evidence_ids: tuple[str, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.financial_path_id.strip() or not self.trajectory_id.strip():
            raise ValueError("Daily financial path identity must be explicit.")
        if not self.snapshot_id.strip() or not self.tariff_schedule_id.strip():
            raise ValueError("Daily financial path lineage must be explicit.")
        if not self.intervals or not self.method_version.strip():
            raise ValueError("Daily financial path must be complete and versioned.")
        if any(
            left.ends_at != right.starts_at
            for left, right in zip(self.intervals, self.intervals[1:], strict=False)
        ):
            raise ValueError("Daily financial intervals must be contiguous.")
        for expected, actual, label in (
            (
                self.grid_import_cost_eur,
                sum(item.grid_import_cost_eur for item in self.intervals),
                "grid import cost",
            ),
            (
                self.grid_export_result_eur,
                sum(item.grid_export_result_eur for item in self.intervals),
                "grid export result",
            ),
            (
                self.avoided_import_value_eur,
                sum(item.avoided_import_value_eur for item in self.intervals),
                "avoided import value",
            ),
            (
                self.pv_storage_opportunity_cost_eur,
                sum(item.pv_storage_opportunity_cost_eur for item in self.intervals),
                "PV storage opportunity cost",
            ),
            (
                self.conversion_loss_value_eur,
                sum(item.conversion_loss_value_eur for item in self.intervals),
                "conversion loss value",
            ),
            (
                self.net_financial_result_eur,
                sum(item.net_financial_result_eur for item in self.intervals),
                "net financial result",
            ),
        ):
            if not isclose(expected, actual, rel_tol=1e-9, abs_tol=EUR_TOLERANCE):
                raise ValueError(f"Daily financial {label} does not reconcile.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Daily financial confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids or len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Daily financial path evidence must be explicit and unique.")


@dataclass(frozen=True, slots=True)
class DailyReferenceFinancialSet:
    """Unranked observer-only financial outcomes for all uncertainty paths."""

    financial_set_id: str
    simulation_id: str
    snapshot_id: str
    paths: tuple[DailyReferenceFinancialPath, ...]
    observer_only: bool
    selection_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        scenarios = tuple(item.scenario for item in self.paths)
        if set(scenarios) != set(PVScenario) or len(scenarios) != len(PVScenario):
            raise ValueError("Daily financial set requires lower, central and upper.")
        if any(item.snapshot_id != self.snapshot_id for item in self.paths):
            raise ValueError("Daily financial paths must share one snapshot.")
        if not self.observer_only or self.selection_permitted:
            raise ValueError("Daily financial outcomes must remain observer-only and unranked.")
        if not self.financial_set_id.strip() or not self.method_version.strip():
            raise ValueError("Daily financial set identity must be explicit.")
