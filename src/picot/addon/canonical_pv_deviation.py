"""ADR-045 canonical PV energy deviation evidence and Runtime Monitor bridge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from picot.addon.actual_pv_energy import actual_pv_energy_for_interval
from picot.addon.history_store import HistoryStore
from picot.domain.planning_input_snapshot import RuntimePressureState
from picot.domain.pv_energy_timeline import PVEnergyEvidenceType, PVEnergyTimeline
from picot.domain.runtime import (
    PlannerRunState,
    RuntimeCoordinationState,
    RuntimeObservation,
    RuntimeObservationKind,
)
from picot.runtime.runtime_monitor import RuntimeMonitor

CANONICAL_PV_DEVIATION_METHOD_VERSION = "canonical-quarter-energy-deviation-v1"
DEFAULT_THRESHOLD_PERCENT = 25.0
DEFAULT_MIN_EXPECTED_ENERGY_WH = 125.0


@dataclass(frozen=True, slots=True)
class CanonicalPVDeviationResult:
    interval_start: datetime
    interval_end: datetime
    expected_energy_wh: float
    actual_energy_wh: float
    deviation_wh: float
    deviation_percent: float
    threshold_percent: float
    threshold_crossed: bool
    forecast_evidence_ids: tuple[str, ...]
    actual_evidence_ids: tuple[str, ...]
    forecast_method_version: str
    actual_method_version: str

    def as_fields(self) -> dict[str, object]:
        return {
            "canonical_pv_deviation_status": "material" if self.threshold_crossed else "within_tolerance",
            "canonical_pv_deviation_observer_only": False,
            "canonical_pv_deviation_authoritative": True,
            "canonical_pv_interval_start": self.interval_start.isoformat(),
            "canonical_pv_interval_end": self.interval_end.isoformat(),
            "canonical_pv_expected_energy_wh": self.expected_energy_wh,
            "canonical_pv_actual_energy_wh": self.actual_energy_wh,
            "canonical_pv_deviation_wh": self.deviation_wh,
            "canonical_pv_deviation_percent": self.deviation_percent,
            "canonical_pv_deviation_threshold_percent": self.threshold_percent,
            "canonical_pv_material_transition": self.threshold_crossed,
            "canonical_pv_forecast_evidence_ids": list(self.forecast_evidence_ids),
            "canonical_pv_actual_evidence_ids": list(self.actual_evidence_ids),
            "canonical_pv_forecast_method_version": self.forecast_method_version,
            "canonical_pv_actual_method_version": self.actual_method_version,
            "canonical_pv_method_version": CANONICAL_PV_DEVIATION_METHOD_VERSION,
        }


def quarter_floor(moment: datetime) -> datetime:
    return moment.replace(minute=(moment.minute // 15) * 15, second=0, microsecond=0)


def quarter_anchor_event(
    *, timeline: PVEnergyTimeline, captured_at: datetime
) -> dict[str, object] | None:
    """Freeze the Solcast energy evidence for the next full canonical quarter."""

    start = quarter_floor(captured_at)
    if captured_at != start:
        start += timedelta(minutes=15)
    end = start + timedelta(minutes=15)
    interval = next(
        (
            item
            for item in timeline.intervals
            if item.starts_at == start
            and item.ends_at == end
            and item.evidence_type is PVEnergyEvidenceType.FORECAST
        ),
        None,
    )
    if interval is None:
        return None
    return {
        "event": "picot_pv_forecast_quarter_anchor",
        "layer": "pv_forecast_validation",
        "anchored_at": captured_at.isoformat(),
        "interval_start": start.isoformat(),
        "interval_end": end.isoformat(),
        "expected_energy_wh": interval.energy_wh,
        "confidence": interval.confidence,
        "forecast_evidence_ids": list(interval.evidence_ids),
        "forecast_method_version": interval.method_version,
    }


class CanonicalPVDeviationEvaluator:
    """Compare one completed canonical quarter using frozen forecast evidence."""

    def __init__(
        self,
        *,
        history: HistoryStore,
        threshold_percent: float = DEFAULT_THRESHOLD_PERCENT,
        minimum_expected_energy_wh: float = DEFAULT_MIN_EXPECTED_ENERGY_WH,
    ) -> None:
        self.history = history
        self.threshold_percent = threshold_percent
        self.minimum_expected_energy_wh = minimum_expected_energy_wh
        self._last_interval_end: datetime | None = None

    def evaluate(
        self,
        *,
        captured_at: datetime,
        telemetry_interval_seconds: int = 5,
    ) -> CanonicalPVDeviationResult | None:
        interval_end = quarter_floor(captured_at)
        interval_start = interval_end - timedelta(minutes=15)
        if interval_end == captured_at and captured_at.second == 0 and captured_at.microsecond == 0:
            pass
        if self._last_interval_end == interval_end:
            return None
        self._last_interval_end = interval_end

        anchor = self._forecast_anchor(interval_start, interval_end)
        if anchor is None:
            return None
        expected = anchor.get("expected_energy_wh")
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return None
        expected_wh = float(expected)
        if expected_wh < self.minimum_expected_energy_wh:
            return None

        actual = actual_pv_energy_for_interval(
            history=self.history,
            starts_at=interval_start,
            ends_at=interval_end,
            telemetry_interval_seconds=telemetry_interval_seconds,
        )
        if actual is None:
            return None

        deviation_wh = actual.energy_wh - expected_wh
        deviation_percent = deviation_wh / expected_wh * 100.0
        threshold_crossed = abs(deviation_percent) >= self.threshold_percent
        raw_forecast_ids = anchor.get("forecast_evidence_ids")
        forecast_ids = (
            tuple(str(item) for item in raw_forecast_ids)
            if isinstance(raw_forecast_ids, list)
            else ()
        )
        forecast_method = anchor.get("forecast_method_version")
        return CanonicalPVDeviationResult(
            interval_start=interval_start,
            interval_end=interval_end,
            expected_energy_wh=expected_wh,
            actual_energy_wh=actual.energy_wh,
            deviation_wh=deviation_wh,
            deviation_percent=deviation_percent,
            threshold_percent=self.threshold_percent,
            threshold_crossed=threshold_crossed,
            forecast_evidence_ids=forecast_ids,
            actual_evidence_ids=actual.evidence_ids,
            forecast_method_version=(
                str(forecast_method) if isinstance(forecast_method, str) else "unknown"
            ),
            actual_method_version=actual.method_version,
        )

    def _forecast_anchor(
        self, interval_start: datetime, interval_end: datetime
    ) -> dict[str, object] | None:
        selected: dict[str, object] | None = None
        selected_at: datetime | None = None
        lookup_start = interval_start - timedelta(hours=1)
        for record in self.history.iter_range(lookup_start, interval_start):
            if record.get("event") != "picot_pv_forecast_quarter_anchor":
                continue
            if record.get("interval_start") != interval_start.isoformat():
                continue
            if record.get("interval_end") != interval_end.isoformat():
                continue
            raw_anchored = record.get("anchored_at")
            if not isinstance(raw_anchored, str):
                continue
            anchored_at = datetime.fromisoformat(raw_anchored.replace("Z", "+00:00"))
            if anchored_at > interval_start:
                continue
            if selected_at is None or anchored_at > selected_at:
                selected = record
                selected_at = anchored_at
        return selected


def runtime_monitor_fields(
    result: CanonicalPVDeviationResult,
    *, observed_at: datetime,
) -> dict[str, object]:
    """Route authoritative PV deviation through the accepted ADR-034 monitor."""

    observation = RuntimeObservation(
        observation_id=(
            f"canonical-pv-deviation:{result.interval_start.isoformat()}:{result.interval_end.isoformat()}"
        ),
        kind=RuntimeObservationKind.FORECAST_CHANGED,
        observed_at=observed_at,
        source_reference="canonical-pv-deviation",
        old_value=f"forecast:{result.expected_energy_wh:.6f}Wh",
        new_value=f"actual:{result.actual_energy_wh:.6f}Wh",
        unit="Wh",
        source_version=1,
        evidence_ids=tuple(dict.fromkeys((*result.forecast_evidence_ids, *result.actual_evidence_ids))),
        material_transition=result.threshold_crossed,
    )
    state = RuntimeCoordinationState(
        planner_state=PlannerRunState.IDLE,
        active_planner_run_id=None,
        last_planner_run_started_at=None,
        last_planner_run_ended_at=None,
        stabilisation_deadline=None,
        replan_required=False,
        replan_reasons=(),
        source_observation_ids=(),
        last_processed_observation_at=None,
        runtime_pressure_state=RuntimePressureState.NORMAL,
        state_version=1,
    )
    monitor_result = RuntimeMonitor().evaluate((observation,), state, now=observed_at)
    record = monitor_result.material_changes[0]
    signal = monitor_result.replanning_signal
    return {
        "canonical_pv_material_classification": record.classification.value,
        "canonical_pv_material_reason": record.reason,
        "canonical_pv_replan_signal": signal.status.value,
        "canonical_pv_fresh_snapshot_required": signal.fresh_snapshot_required,
        "canonical_pv_replan_reasons": list(signal.reasons),
        "canonical_pv_replan_source_observation_ids": list(signal.source_observation_ids),
    }
