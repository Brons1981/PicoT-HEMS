"""Financial inference on the existing passive worker, isolated from planning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import timedelta
from math import isfinite
from typing import Any

from picot.v2.contracts import (
    CurrentStorageState,
    PlanningInputSnapshot,
    PriceForecastPoint,
    StoragePhysicalLimits,
)
from picot.v2.financial_measurement_inference import (
    financial_night_windows,
    infer_financial_measurements,
)
from picot.v2.financial_result_ledger import FinancialPhysicalContext, FinancialResultLedger
from picot.v2.financial_result_metrics import (
    SETTLEMENT_ROLES,
    PriceSegments,
    build_financial_metrics,
    financial_measurement_coverage,
)
from picot.v2.grid_charge_review import ReviewSettings
from picot.v2.power_history import PowerHistoryPoint, PowerHistorySnapshot
from picot.v2.pv_solar_history import HomeAssistantSolarHistoryReader, SolarHistoryReadResult
from picot.v2.review_alignment import _integrals


def _tariff_integrated_history(
    history: PowerHistorySnapshot, segments: PriceSegments,
) -> PowerHistorySnapshot:
    """Integrate once for display formulas that only consume energy per tariff.

    Keep the prepared source history for coverage and provenance. These interval
    averages are temporary formula inputs, never measurements or planner inputs.
    """
    bounds = [segments[0][0], *(segment[1] for segment in segments)]
    integrated = []
    for series in history.series:
        energies, _ = _integrals(series, bounds)
        if any(value is None for value in energies):
            raise ValueError("financial_tariff_integration_incomplete")
        integrated.append(replace(series, points=tuple(
            PowerHistoryPoint(
                start, value * 3600 / (end - start).total_seconds(),
                f"financial:tariff-integral:{series.series_id}:{start.isoformat()}",
            ) for start, end, value in zip(bounds, bounds[1:], energies, strict=False)
            if value is not None
        )))
    return replace(history, series=tuple(integrated))


class FinancialMeasurementObserver:
    """At most today's/yesterday's solar reads; never starts a thread or changes plans."""

    def __init__(
        self, *, ledger: FinancialResultLedger, solar_reader: HomeAssistantSolarHistoryReader,
        publish: Callable[[dict[str, object]], None], pv_maximum_power_w: float,
    ) -> None:
        self.ledger, self.solar_reader, self.publish = ledger, solar_reader, publish
        self.pv_maximum_power_w = pv_maximum_power_w
        self._solar_cache: dict[str, SolarHistoryReadResult] = {}

    def __call__(
        self, snapshot: PlanningInputSnapshot, history: PowerHistorySnapshot,
        prices: tuple[PriceForecastPoint, ...], settings: ReviewSettings, settings_changed: bool,
    ) -> None:
        day = history.starts_at.astimezone(self.ledger.local_timezone).date().isoformat()
        try:
            self._review(snapshot, history, prices, settings, settings_changed, day)
        except Exception as exc:
            self.ledger.record_financial_inference_error(
                day, snapshot.captured_at, str(exc) if isinstance(exc, ValueError)
                else type(exc).__name__,
            )
        self.publish(self.ledger.dashboard_view())

    def _review(
        self, snapshot: PlanningInputSnapshot, history: PowerHistorySnapshot,
        prices: tuple[PriceForecastPoint, ...], settings: ReviewSettings,
        settings_changed: bool, day: str,
    ) -> None:
        if (settings_changed or settings.charge_efficiency != self.ledger.charge_efficiency
                or settings.discharge_efficiency != self.ledger.discharge_efficiency
                or settings.wear_eur_per_kwh != self.ledger.wear_rate):
            raise ValueError("financial_settings_changed_during_day")
        if history.status != "available" or history.error:
            raise ValueError("measurement_history_unavailable")
        if (history.ends_at <= history.starts_at or history.ends_at > snapshot.captured_at
                or history.ends_at - history.starts_at > timedelta(hours=26)):
            raise ValueError("measurement_period_mismatch")
        if sum(len(s.points) for s in history.series) > 300_000:
            raise ValueError("financial_measurement_resource_limit")
        if len({series.role for series in history.series}) != len(history.series):
            raise ValueError("ambiguous_measurement_roles")
        if len(snapshot.current_storage_states) != 1:
            raise ValueError("single_storage_scope_required")
        soc = next((s for s in history.series if s.role == "storage_soc"), None)
        closing = max((p for p in soc.points if p.sampled_at <= history.ends_at),
                      key=lambda p: p.sampled_at, default=None) if soc else None
        if closing is None or not isfinite(closing.power_w) or not 0 <= closing.power_w <= 100:
            raise ValueError("financial_closing_soc_missing")
        solar = self._solar_cache.get(day)
        if (solar is None or solar.ends_at < history.ends_at or solar.status != "available"
                or not solar.observations
                or solar.observations[0].sampled_at > history.starts_at
                or history.ends_at - solar.observations[-1].sampled_at > timedelta(minutes=30)
                or any(b.sampled_at - a.sampled_at > timedelta(minutes=30)
                       for a, b in zip(solar.observations, solar.observations[1:], strict=False))):
            solar = self.solar_reader.read(
                starts_at=history.starts_at - timedelta(minutes=30), ends_at=history.ends_at,
                local_timezone=self.ledger.local_timezone,
            )
            if len(solar.observations) > 4096:
                raise ValueError("financial_solar_history_resource_limit")
            self._solar_cache[day] = solar
        for old in sorted(self._solar_cache)[:-2]:
            del self._solar_cache[old]
        nights = financial_night_windows(solar, history.starts_at, history.ends_at)
        prepared = infer_financial_measurements(
            history, night_windows=nights, pv_maximum_power_w=self.pv_maximum_power_w,
            charge_maximum_power_w=settings.charge_power_w,
            discharge_maximum_power_w=settings.discharge_power_w,
        )
        source_state = snapshot.current_storage_states[0]
        # Recorder evidence has its own timestamp. A current HA read/valid-since
        # envelope must never be transplanted onto yesterday's closing SOC.
        state = CurrentStorageState(
            storage_state_id=f"financial-closing:{day}:{closing.evidence_id}",
            execution_scope_id=source_state.execution_scope_id,
            capability_id=source_state.capability_id, confidence=source_state.confidence,
            current_soc=closing.power_w / 100, usable_capacity_wh=settings.capacity_wh,
            measured_at=closing.sampled_at, evidence_ids=(closing.evidence_id,),
        )
        physical = StoragePhysicalLimits(
            execution_scope_id=state.execution_scope_id, capability_id=state.capability_id,
            minimum_soc=settings.minimum_soc, maximum_soc=settings.maximum_soc,
            maximum_charge_input_power_w=settings.charge_power_w,
            maximum_discharge_output_power_w=settings.discharge_power_w,
            evidence_ids=(f"financial-recorded-settings:{day}",),
            method_version="financial-recorded-physical-settings:v1",
        )
        context = FinancialPhysicalContext(history.ends_at, (state,), (physical,))
        # Never pass SOC as watts to the original energy accounting formula.
        energy_history = replace(prepared.history, series=tuple(
            s for s in prepared.history.series if s.role != "storage_soc"
        ))
        segments = self.ledger._price_segments(prices, history.starts_at, history.ends_at)
        coverage = financial_measurement_coverage(energy_history)
        settlement = (
            self.ledger.evaluate_display_history(
                context, _tariff_integrated_history(energy_history, segments), prices,
            )
            if segments and not any(coverage[role]["gap_count"] for role in SETTLEMENT_ROLES)
            else {}
        )
        metrics = build_financial_metrics(
            history=energy_history, settlement=settlement,
            price_segments=segments,
            wear_rate=self.ledger.wear_rate, expected_starts_at=history.starts_at,
            expected_ends_at=history.ends_at,
        )
        for value in metrics["values"].values():
            if value["status"] == "available" and prepared.inferred_roles.intersection(
                value["required_roles"]
            ):
                value["status"] = "estimated"
        if metrics["status"] == "available" and prepared.inferred_roles:
            metrics["status"] = "estimated"
        metrics.update({
            "method_version": "financial-measurement-inference:v1",
            "inferences": list(prepared.inferences), "rejected_inferences": list(prepared.rejected),
            "raw_measurement_coverage": prepared.raw_coverage,
            "maximum_estimation_error_wh": round(prepared.uncertainty_wh, 6),
            "solar_history_status": solar.status, "solar_history_error": solar.error,
            "household_energy_sources": settlement.get("household_energy_sources", {}),
        })
        solar_evidence: dict[str, Any] = {
            "source_entity_id": solar.source_entity_id, "status": solar.status,
            "error": solar.error, "starts_at": solar.starts_at.isoformat(),
            "ends_at": solar.ends_at.isoformat(), "method_version": solar.method_version,
            "observations": [{**asdict(o), "sampled_at": o.sampled_at.isoformat(),
                              "sunset_at": o.sunset_at.isoformat()} for o in solar.observations],
        }
        self.ledger.store_financial_estimate(day, metrics, {
            "attempted_at": snapshot.captured_at.isoformat(), "settings": asdict(settings),
            "pv_maximum_power_w": self.pv_maximum_power_w, "solar": solar_evidence,
            "night_windows": [{"starts_at": n.starts_at.isoformat(),
                               "ends_at": n.ends_at.isoformat(),
                               "evidence_ids": list(n.evidence_ids)} for n in nights],
        })
