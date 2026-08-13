"""ADR-041 financial outcome derivation for simulated Candidate Energy Paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.energy_path import EnergyPath
from picot.domain.evaluation import ComparisonDirection, ObjectiveOutcome
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSet
from picot.domain.objectives import ObjectiveKind


@dataclass(frozen=True, slots=True)
class FinancialCandidateOutcomeDeriver:
    """Derive complete import/export settlement cost from canonical evidence.

    ``ENERGY_PRICE`` is the canonical grid-import price already used by the
    storage-acquisition planner. ``GRID_EXPORT_PRICE`` is a separate explicit
    settlement series. No symmetric-price assumption is permitted.
    """

    def derive(self, *, path: EnergyPath, forecasts: ForecastSet) -> ObjectiveOutcome | None:
        if not path.projected_states:
            return None
        import_series = forecasts.by_kind(ForecastKind.ENERGY_PRICE)
        export_series = forecasts.by_kind(ForecastKind.GRID_EXPORT_PRICE)
        if len(import_series) != 1 or len(export_series) != 1:
            return None
        import_forecast = import_series[0]
        export_forecast = export_series[0]
        if import_forecast.unit != "EUR/kWh" or export_forecast.unit != "EUR/kWh":
            return None

        previous = path.horizon_start
        total_cost_eur = 0.0
        confidences: list[float] = []
        evidence_ids: list[str] = [path.path_id, import_forecast.forecast_id, export_forecast.forecast_id]

        for state in path.projected_states:
            if state.household_import_w is None or state.household_export_w is None:
                return None
            if state.at <= previous:
                return None
            import_point = self._covering_point(import_forecast.points, previous, state.at)
            export_point = self._covering_point(export_forecast.points, previous, state.at)
            if import_point is None or export_point is None:
                return None
            duration_h = (state.at - previous).total_seconds() / 3600.0
            import_kwh = state.household_import_w * duration_h / 1000.0
            export_kwh = state.household_export_w * duration_h / 1000.0
            total_cost_eur += import_kwh * import_point.value
            total_cost_eur -= export_kwh * export_point.value
            confidences.extend(
                (
                    state.confidence,
                    import_point.confidence,
                    export_point.confidence,
                )
            )
            previous = state.at

        if not confidences:
            return None
        return ObjectiveOutcome(
            objective=ObjectiveKind.FINANCIAL_RESULT,
            value=total_cost_eur,
            direction=ComparisonDirection.LOWER_IS_BETTER,
            unit="EUR",
            confidence=min(confidences),
            evidence_ids=tuple(evidence_ids),
        )

    @staticmethod
    def _covering_point(
        points: tuple[ForecastPoint, ...],
        starts_at: datetime,
        ends_at: datetime,
    ) -> ForecastPoint | None:
        for point in points:
            if point.starts_at <= starts_at and point.ends_at >= ends_at:
                return point
        return None
