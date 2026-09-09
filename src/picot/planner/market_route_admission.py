"""Market user-rule admission from complete existing physical projections.

The shared simulator and settlement own physics and money. This boundary
checks explicit user conditions; it neither ranks nor binds execution plans.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from picot.domain.daily_reference_simulation import DailyPlanningProjection
from picot.domain.daily_reference_tariff import DailyReferenceTariffSchedule
from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.domain.market_user_rule import MarketSpreadEvidence
from picot.planner.independent_daily_financial_settlement import IndependentDailyFinancialSettlement


@dataclass(frozen=True, slots=True)
class MarketRecoverySegment:
    assignment_id: str
    starts_at: datetime
    ends_at: datetime
    target_storage_energy_wh: float

    def __post_init__(self) -> None:
        if (
            not self.assignment_id
            or self.starts_at.utcoffset() is None
            or self.ends_at.utcoffset() is None
        ):
            raise ValueError("recovery requires explicit ownership and aware times")
        if (
            self.starts_at >= self.ends_at
            or not isfinite(self.target_storage_energy_wh)
            or self.target_storage_energy_wh <= 0
        ):
            raise ValueError("recovery requires positive duration and target")


@dataclass(frozen=True, slots=True)
class MarketAdmission:
    assignment_id: str
    snapshot_id: str
    status: str
    reason: str
    expected_export_wh: float
    recovery_assignment_id: str | None = None
    incremental_cash_eur: float | None = None
    incremental_net_profit_eur: float | None = None
    net_margin_eur_per_export_kwh: float | None = None


def assess_market_route(
    *,
    assignment: MarketDailyAssignment,
    spread: MarketSpreadEvidence,
    baseline: DailyPlanningProjection,
    proposed: DailyPlanningProjection,
    minimum_storage_energy_wh: float,
    recovery_segments: tuple[MarketRecoverySegment, ...] = (),
    tariffs: DailyReferenceTariffSchedule | None = None,
    wear_eur_per_export_kwh: float = 0.0,
) -> MarketAdmission:
    """No recovery-price requirement when the user's recovery option is off.

    The caller supplies the same household/PV inputs and initial energy for
    both paths. A physically curtailed export is not silently admitted as a
    smaller requested action. Other charging obligations remain owned upstream.
    """
    if not isfinite(minimum_storage_energy_wh) or minimum_storage_energy_wh < 0:
        raise ValueError("minimum storage energy must be finite and nonnegative")
    if not isfinite(wear_eur_per_export_kwh) or wear_eur_per_export_kwh < 0:
        raise ValueError("wear must be finite nonnegative EUR/export-kWh")
    if (spread.rule_id, spread.rule_revision) != (
        assignment.rule.rule_id,
        assignment.rule.revision,
    ):
        raise ValueError("spread must belong to the frozen daily rule")
    if abs(spread.battery_energy_wh - assignment.battery_energy_wh) > 1e-6:
        raise ValueError("market volume must match the daily capacity allocation")
    if spread.minimum_spread_eur_per_kwh != assignment.rule.minimum_spread_eur_per_kwh:
        raise ValueError("spread threshold must match the frozen daily rule")
    if not baseline.intervals or not proposed.intervals:
        raise ValueError("complete physical projections are required")
    if not baseline.snapshot_id == proposed.snapshot_id == spread.snapshot_id:
        raise ValueError("market comparison must use one input snapshot")
    if (
        baseline.basis_method != proposed.basis_method
        or baseline.basis_timeline != proposed.basis_timeline
    ):
        raise ValueError("market comparison must use the same physical PV basis")
    if len(baseline.intervals) != len(proposed.intervals) or any(
        (a.starts_at, a.ends_at, a.household_demand_wh, a.usable_pv_wh)
        != (b.starts_at, b.ends_at, b.household_demand_wh, b.usable_pv_wh)
        for a, b in zip(baseline.intervals, proposed.intervals, strict=True)
    ):
        raise ValueError("market comparison requires unchanged household/PV inputs and horizon")
    if (
        abs(
            baseline.intervals[0].storage_energy_at_start_wh
            - proposed.intervals[0].storage_energy_at_start_wh
        )
        > 1e-6
    ):
        raise ValueError("market comparison must start from the same actual stored energy")
    start, end = spread.export_window.starts_at, spread.export_window.ends_at
    if not assignment.starts_at <= start < end <= assignment.ends_at:
        raise ValueError("export must belong to the daily market assignment")
    selected = tuple(i for i in proposed.intervals if start <= i.starts_at and i.ends_at <= end)
    if not selected or selected[0].starts_at != start or selected[-1].ends_at != end:
        raise ValueError("physical projection must align with exact export boundaries")
    original = tuple(i for i in baseline.intervals if start <= i.starts_at and i.ends_at <= end)
    if any(i.storage_to_grid_output_wh > 1e-6 for i in original):
        raise ValueError("new market action cannot overwrite an existing export action")
    if any(
        abs(a.storage_to_grid_output_wh - b.storage_to_grid_output_wh) > 1e-6
        for a, b in zip(baseline.intervals, proposed.intervals, strict=True)
        if b.ends_at <= start or b.starts_at >= end
    ):
        raise ValueError("market candidate cannot change another export action")
    export = sum(i.storage_to_grid_output_wh for i in selected)

    def result(
        status: str,
        reason: str,
        *,
        recovery_assignment_id: str | None = None,
        incremental_cash_eur: float | None = None,
        incremental_net_profit_eur: float | None = None,
        net_margin_eur_per_export_kwh: float | None = None,
    ) -> MarketAdmission:
        return MarketAdmission(
            assignment.assignment_id,
            spread.snapshot_id,
            status,
            reason,
            export,
            recovery_assignment_id,
            incremental_cash_eur,
            incremental_net_profit_eur,
            net_margin_eur_per_export_kwh,
        )

    if assignment.status != "pending":
        return result("rejected", "daily_market_assignment_already_closed")
    if not spread.meets_spread:
        return result("rejected", "user_spread_not_met")
    if abs(export - spread.export_window.grid_energy_wh) > 1e-6:
        return result("rejected", "requested_export_not_physically_deliverable")
    if (
        min(
            min(i.storage_energy_at_start_wh, i.storage_energy_at_end_wh)
            for i in proposed.intervals
        )
        + 1e-6
        < minimum_storage_energy_wh
    ):
        return result("rejected", "minimum_soc_violated")
    if not assignment.rule.recovery_required:
        return result("admissible", "user_conditions_met_recovery_not_required")
    recovery = next(
        (
            segment
            for segment in sorted(recovery_segments, key=lambda s: s.starts_at)
            if segment.starts_at >= end
            and segment.target_storage_energy_wh == assignment.usable_capacity_wh
            and any(
                segment.starts_at <= at <= segment.ends_at
                and energy + 1e-6 >= assignment.usable_capacity_wh
                for i in proposed.intervals
                for at, energy in (
                    (i.starts_at, i.storage_energy_at_start_wh),
                    (i.ends_at, i.storage_energy_at_end_wh),
                )
            )
        ),
        None,
    )
    if recovery is None:
        return result("insufficient_evidence", "future_owned_charge_does_not_prove_full_recovery")
    if tariffs is None:
        return result(
            "insufficient_evidence",
            "actual_recovery_prices_unavailable",
            recovery_assignment_id=recovery.assignment_id,
        )
    settlement = IndependentDailyFinancialSettlement()
    before = settlement.settle_planning_basis(projection=baseline, tariffs=tariffs)
    after = settlement.settle_planning_basis(projection=proposed, tariffs=tariffs)
    cash = after.cash_result_eur - before.cash_result_eur
    profit = cash - export / 1000 * wear_eur_per_export_kwh
    margin = profit / (export / 1000)
    return result(
        "admissible"
        if margin >= assignment.rule.minimum_net_margin_eur_per_export_kwh
        else "rejected",
        "recovery_and_net_margin_met"
        if margin >= assignment.rule.minimum_net_margin_eur_per_export_kwh
        else "recovery_net_margin_not_met",
        recovery_assignment_id=recovery.assignment_id,
        incremental_cash_eur=cash,
        incremental_net_profit_eur=profit,
        net_margin_eur_per_export_kwh=margin,
    )
