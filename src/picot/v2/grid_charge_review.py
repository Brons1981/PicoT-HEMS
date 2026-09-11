"""Passive hindsight measurement; never creates plans or feeds their inputs.

The probe scales measured grid-to-storage input uniformly at its original times.
It is a feasible comparison, NOT a globally optimal alternative schedule.
Measured battery export is held fixed; PV and household load are replayed with
NOM, physical limits and the same closing inventory. Missing evidence fails closed.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any

from picot.v2.contracts import PriceForecastPoint
from picot.v2.financial_result_ledger import FinancialResultLedger
from picot.v2.power_history import PowerHistorySeries, PowerHistorySnapshot

METHOD = "measured-day-uniform-grid-reduction:v1"
ROLES = (
    "pv_generation",
    "household_load",
    "grid_import",
    "grid_export",
    "battery_charge",
    "battery_discharge",
    "storage_soc",
)


@dataclass(frozen=True)
class ReviewSettings:
    capacity_wh: float
    minimum_soc: float
    maximum_soc: float
    charge_power_w: float
    discharge_power_w: float
    charge_efficiency: float
    discharge_efficiency: float
    wear_eur_per_kwh: float

    def __post_init__(self) -> None:
        if not all(isfinite(v) for v in vars(self).values()) or not (
            self.capacity_wh > 0
            and 0 <= self.minimum_soc < self.maximum_soc <= 1
            and self.charge_power_w > 0
            and self.discharge_power_w > 0
            and 0 < self.charge_efficiency <= 1
            and 0 < self.discharge_efficiency <= 1
            and self.wear_eur_per_kwh >= 0
        ):
            raise ValueError("invalid review settings")


class _Series:
    def __init__(self, series: PowerHistorySeries) -> None:
        self.points = sorted(series.points, key=lambda p: p.sampled_at)
        self.times = [p.sampled_at for p in self.points]
        self.linear = series.history_semantics == "sampled_linear"

    def value(self, at: datetime) -> float:
        index = bisect_right(self.times, at) - 1
        if index < 0:
            raise ValueError("measurement_start_missing")
        point = self.points[index]
        value = point.power_w
        if self.linear:
            if index + 1 < len(self.points):
                following = self.points[index + 1]
                seconds = (following.sampled_at - point.sampled_at).total_seconds()
                if seconds > 300:
                    raise ValueError("household_measurement_gap")
                value += (following.power_w - value) * (
                    (at - point.sampled_at).total_seconds() / seconds
                )
            elif at - point.sampled_at > timedelta(minutes=2):
                raise ValueError("household_measurement_tail_missing")
        if not isfinite(value) or value < 0:
            raise ValueError("measurement_unavailable")
        return value


def actual_soc_view(history: PowerHistorySnapshot) -> dict[str, Any]:
    """Copy raw percent observations, including explicit breaks, never average SOC."""
    series = next((s for s in history.series if s.role == "storage_soc"), None)
    points: list[dict[str, Any]] = []
    if series is not None and history.status == "available" and history.error is None:
        for p in sorted(series.points, key=lambda p: p.sampled_at):
            if p.sampled_at <= history.ends_at:
                points.append(
                    {
                        "at": max(history.starts_at, p.sampled_at).isoformat(),
                        "observed_at": p.sampled_at.isoformat(),
                        "soc_percent": p.power_w
                        if isfinite(p.power_w) and 0 <= p.power_w <= 100
                        else None,
                        "evidence_id": p.evidence_id,
                    }
                )
    return {
        "points": points,
        "ends_at": history.ends_at.isoformat(),
        "source_entity_id": series.source_entity_id if series else None,
        "status": "available" if points else "unavailable",
    }


@dataclass(frozen=True)
class _Interval:
    hours: float
    pv: float
    load: float
    grid_charge: float
    battery_export: float
    import_rate: float
    export_rate: float
    main: bool


def review_day(
    history: PowerHistorySnapshot,
    prices: tuple[PriceForecastPoint, ...],
    settings: ReviewSettings,
    main_windows: tuple[tuple[datetime, datetime], ...],
) -> dict[str, Any]:
    """Return a model estimate with explicit quality and inventory constraints."""
    result: dict[str, Any] = {
        "method_version": METHOD,
        "status": "incomplete",
        "reason": None,
        "starts_at": history.starts_at.isoformat(),
        "ends_at": history.ends_at.isoformat(),
        "observer_only": True,
        "selection_permitted": False,
        "commitment_permitted": False,
    }
    try:
        if history.status != "available" or history.error is not None:
            raise ValueError("history_unavailable")
        raw = {s.role: s for s in history.series}
        if not all(role in raw and raw[role].points for role in ROLES):
            raise ValueError("missing_measured_series")
        if not main_windows:
            raise ValueError("main_window_evidence_missing")
        if settings.maximum_soc < 1:
            raise ValueError("configured_maximum_below_daily_target")
        series = {role: _Series(raw[role]) for role in ROLES}
        start, end = history.starts_at, history.ends_at
        tariffs = FinancialResultLedger._price_segments(prices, start, end)
        if not tariffs:
            raise ValueError("price_coverage_incomplete")
        opening, closing = series["storage_soc"].value(start), series["storage_soc"].value(end)
        if not all(0 <= v <= 100 for v in (opening, closing)):
            raise ValueError("invalid_soc")
        boundaries = {start, end}
        for role, s in series.items():
            if role == "storage_soc":
                if any(
                    not isfinite(p.power_w) or not 0 <= p.power_w <= 100
                    for p in s.points
                    if start <= p.sampled_at <= end
                ):
                    raise ValueError("measurement_unavailable")
                continue
            boundaries.update(t for t in s.times if start < t < end)
        for a, b, _, _ in tariffs:
            boundaries.update((a, b))
        for a, b in main_windows:
            boundaries.update(t for t in (a, b) if start < t < end)
        # Bound interpolation error and accurately clip full/reserve crossings.
        at = start
        while at < end:
            boundaries.add(at)
            at += timedelta(minutes=1)
        if len(boundaries) > 300_000:
            raise ValueError("review_resource_limit")
        times = sorted(boundaries)
        tariff_starts = [t[0] for t in tariffs]
        intervals = []
        measured_cost = measured_charge = measured_discharge = measured_grid = 0.0
        measured_export = balance_error = 0.0
        for a, b in zip(times, times[1:], strict=False):
            midpoint = a + (b - a) / 2
            values = {
                role: s.value(midpoint) for role, s in series.items() if role != "storage_soc"
            }
            hours = (b - a).total_seconds() / 3600
            _, _, buy, sell = tariffs[bisect_right(tariff_starts, a) - 1]
            pv, load = values["pv_generation"], values["household_load"]
            charge, discharge = values["battery_charge"], values["battery_discharge"]
            grid_charge = min(values["grid_import"], max(0.0, charge - max(0.0, pv - load)))
            battery_export = min(values["grid_export"], max(0.0, discharge - max(0.0, load - pv)))
            intervals.append(
                _Interval(
                    hours,
                    pv * hours,
                    load * hours,
                    grid_charge * hours,
                    battery_export * hours,
                    buy,
                    sell,
                    any(x <= a < y for x, y in main_windows),
                )
            )
            measured_cost += (values["grid_import"] * buy - values["grid_export"] * sell) * hours
            measured_charge += charge * hours
            measured_discharge += discharge * hours
            measured_grid += grid_charge * hours
            measured_export += battery_export * hours
            balance_error += (
                pv + values["grid_import"] + discharge - load - values["grid_export"] - charge
            ) * hours
        cap = settings.capacity_wh
        model_closing = opening / 100 * cap + measured_charge * settings.charge_efficiency
        model_closing -= measured_discharge / settings.discharge_efficiency
        error = model_closing - closing / 100 * cap
        result.update(
            {
                "opening_soc_percent": opening,
                "closing_soc_percent": closing,
                "measured_grid_charge_kwh": round(measured_grid / 1000, 4),
                "preserved_battery_export_kwh": round(measured_export / 1000, 4),
                "flow_soc_error_wh": round(error, 2),
            }
        )
        if abs(balance_error) > max(100.0, cap * 0.02):
            raise ValueError("power_balance_mismatch")
        # Measured power and BMS SOC must agree before making a savings claim.
        if abs(error) > max(100.0, cap * 0.02):
            raise ValueError("flow_soc_mismatch")

        def replay(fraction: float) -> tuple[bool, float, float, float, float]:
            energy = opening / 100 * cap
            peak = 0.0
            cost = discharge_total = grid_total = 0.0
            valid = True
            for i in intervals:
                if i.main:
                    peak = max(peak, energy)
                surplus, deficit = max(0.0, i.pv - i.load), max(0.0, i.load - i.pv)
                available = max(0.0, energy - cap * settings.minimum_soc)
                # Preserve actual exported battery energy; household residual may use the grid.
                output_limit = settings.discharge_power_w * i.hours
                trade = i.battery_export
                if trade > min(output_limit, available * settings.discharge_efficiency) + 1e-6:
                    valid = False
                trade = min(trade, output_limit, available * settings.discharge_efficiency)
                energy -= trade / settings.discharge_efficiency
                household = min(
                    deficit,
                    max(0.0, output_limit - trade),
                    max(0.0, energy - cap * settings.minimum_soc) * settings.discharge_efficiency,
                )
                # Explicit charging does not simultaneously discharge to the house.
                if i.grid_charge * fraction > 1e-6:
                    household = 0.0
                energy -= household / settings.discharge_efficiency
                room = max(0.0, cap * settings.maximum_soc - energy) / settings.charge_efficiency
                input_limit = settings.charge_power_w * i.hours if trade == 0 else 0.0
                solar = min(surplus, input_limit, room)
                grid = min(
                    i.grid_charge * fraction, max(0.0, input_limit - solar), max(0.0, room - solar)
                )
                energy += (solar + grid) * settings.charge_efficiency
                if i.main:
                    peak = max(peak, energy)
                discharge_total += trade + household
                grid_total += grid
                cost += (deficit - household + grid) * i.import_rate - (
                    surplus - solar + trade
                ) * i.export_rate
            feasible = valid and peak >= cap - 1e-6 and energy >= closing / 100 * cap - 1e-6
            return (
                feasible,
                peak / cap * 100,
                energy / cap * 100,
                grid_total,
                (cost + discharge_total * settings.wear_eur_per_kwh) / 1000,
            )

        zero = replay(0.0)
        full = replay(1.0)
        result["pv_only_peak_soc_percent"] = round(zero[1], 2)
        result["pv_only_feasible"] = zero[0]
        if not full[0] and not zero[0]:
            raise ValueError("reference_replay_not_feasible")
        # In this fixed-time probe, increasing the retained input cannot lower SOC:
        # it either adds energy or stops household discharge during charging. The
        # fixed export, goal and closing-inventory constraints are therefore monotone.
        # Search a discrete 1% grid in <= 7 probes, rather than scanning 101 full days.
        chosen = zero if zero[0] else full
        if not zero[0]:
            low, high = 1, 100
            while low < high:
                middle = (low + high) // 2
                probe = replay(middle / 100)
                if probe[0]:
                    high, chosen = middle, probe
                else:
                    low = middle + 1
        actual_net = (measured_cost + measured_discharge * settings.wear_eur_per_kwh) / 1000
        result.update(
            {
                "status": "available",
                "reason": None,
                "retained_grid_charge_kwh": round(chosen[3] / 1000, 4),
                "avoidable_grid_charge_kwh": round(max(0.0, measured_grid - chosen[3]) / 1000, 4),
                "cost_difference_eur": round(actual_net - chosen[4], 4),
                "replay_closing_soc_percent": round(chosen[2], 2),
                "probe_step_percent": 1,
            }
        )
    except ValueError as exc:
        result["reason"] = str(exc)
    return result
