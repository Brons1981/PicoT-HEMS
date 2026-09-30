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
    recovery_ends_at: datetime | None = None


def common_market_recovery(
    *, projections: tuple[DailyPlanningProjection, ...],
    recovery_segments: tuple[MarketRecoverySegment, ...], after: datetime,
    allow_recovery_surplus: bool = False,
) -> MarketRecoverySegment | None:
    """Find a priced full recovery with equal stock or a paid new-trade surplus.

    The caller supplies owned charge cycles, not an invented midnight target.
    Use the whole cycle so differences in its last charging actions are valued.
    Later unrelated actions remain in the physical path but not this comparison.
    With allow_recovery_surplus, projections[0] is the unchanged reference;
    every challenger must finish with at least that stock. No surplus valuation.
    """
    if not projections:
        return None
    for segment in sorted(recovery_segments, key=lambda s: (s.ends_at, s.starts_at)):
        if segment.starts_at < after:
            continue
        ends = []
        for projection in projections:
            finish = next((i for i in projection.intervals if i.ends_at == segment.ends_at), None)
            reached = any(
                segment.starts_at <= at <= segment.ends_at
                and energy + 1e-6 >= segment.target_storage_energy_wh
                for i in projection.intervals for at, energy in (
                    (i.starts_at, i.storage_energy_at_start_wh),
                    (i.ends_at, i.storage_energy_at_end_wh),
                )
            )
            if finish is None or not reached:
                break
            ends.append(finish.storage_energy_at_end_wh)
        if len(ends) == len(projections):
            equal_stock = max(ends) - min(ends) <= 1e-6
            # A new trade may pay for more stock than the unchanged reference.
            # All paths must still prove the full goal; never allow a deficit.
            # Settlement below includes every import and gives surplus no value.
            paid_surplus = allow_recovery_surplus and all(
                energy + 1e-6 >= ends[0] for energy in ends[1:]
            )
            if equal_stock or paid_surplus:
                return segment
    return None


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
    allow_recovery_surplus: bool = False,
) -> MarketAdmission:
    """Admit automatic trade only with actual, comparable recovery economics.

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
        recovery_ends_at: datetime | None = None,
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
            recovery_ends_at,
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
    recovery = common_market_recovery(
        projections=(baseline, proposed), after=end,
        allow_recovery_surplus=allow_recovery_surplus,
        recovery_segments=tuple(s for s in recovery_segments
                                if s.target_storage_energy_wh == assignment.usable_capacity_wh),
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
    before = settlement.settle_planning_basis(
        projection=baseline, tariffs=tariffs, horizon_end=recovery.ends_at)
    after = settlement.settle_planning_basis(
        projection=proposed, tariffs=tariffs, horizon_end=recovery.ends_at)
    cash = after.cash_result_eur - before.cash_result_eur
    profit = cash - (
        settlement.storage_discharge_cost(proposed, wear_eur_per_export_kwh,
                                          horizon_end=recovery.ends_at)
        - settlement.storage_discharge_cost(baseline, wear_eur_per_export_kwh,
                                            horizon_end=recovery.ends_at)
    )
    margin = profit / (export / 1000)
    required_margin = (assignment.rule.minimum_net_margin_eur_per_export_kwh
                       if assignment.rule.recovery_required else 0.0)
    profitable = profit > 0 and margin >= required_margin
    return result(
        "admissible"
        if profitable
        else "rejected",
        "recovery_and_net_margin_met"
        if profitable
        else "recovery_net_margin_not_met",
        recovery_assignment_id=recovery.assignment_id,
        incremental_cash_eur=cash,
        incremental_net_profit_eur=profit,
        net_margin_eur_per_export_kwh=margin,
        recovery_ends_at=recovery.ends_at,
    )
