"""Observer-only financial outcomes for independent physical daily paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isclose, isfinite

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


@dataclass(frozen=True, slots=True)
class DailyPlanningFinancialResult:
    """Cash-flow valuation of the declared planning basis, not a PV scenario.

    Main-window acquisition price includes PV opportunity cost and charge
    loss. Full-horizon cash is separate; avoided import and conversion losses
    are not counted twice in that cash-flow diagnostic.
    """

    snapshot_id: str
    intent_schedule_id: str
    basis_timeline_id: str
    tariff_schedule_id: str
    intervals: tuple[DailyReferenceFinancialInterval, ...]
    method_version: str
    acquisition_input_wh: float
    acquisition_stored_wh: float
    acquisition_cost_eur: float

    def __post_init__(self) -> None:
        if (
            not all(
                isfinite(v)
                for v in (
                    self.acquisition_input_wh,
                    self.acquisition_stored_wh,
                    self.acquisition_cost_eur,
                )
            )
            or not 0 <= self.acquisition_stored_wh <= self.acquisition_input_wh + 1e-6
        ):
            raise ValueError("main acquisition energy and cost must be finite and consistent")
        if (
            not all(
                value.strip()
                for value in (
                    self.snapshot_id,
                    self.intent_schedule_id,
                    self.basis_timeline_id,
                    self.tariff_schedule_id,
                    self.method_version,
                )
            )
            or not self.intervals
        ):
            raise ValueError("planning financial result requires complete lineage and intervals")
        if any(
            a.ends_at != b.starts_at
            for a, b in zip(self.intervals, self.intervals[1:], strict=False)
        ):
            raise ValueError("planning financial intervals must be contiguous")

    @property
    def acquisition_eur_per_stored_kwh(self) -> float | None:
        """Effective main-window price; undefined when no charging is required."""
        if self.acquisition_stored_wh == 0:
            return None
        return self.acquisition_cost_eur / (self.acquisition_stored_wh / 1000)

    @property
    def cash_result_eur(self) -> float:
        return sum(i.grid_export_result_eur - i.grid_import_cost_eur for i in self.intervals)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    self.intent_schedule_id,
                    self.basis_timeline_id,
                    self.tariff_schedule_id,
                    *(e for i in self.intervals for e in i.evidence_ids),
                )
            )
        )
