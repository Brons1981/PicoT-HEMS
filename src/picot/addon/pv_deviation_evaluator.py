"""Rolling observation-only evaluator for PV forecast deviation.

The evaluator deliberately does not trigger replanning. It turns noisy point-in-time
Solcast-vs-GoodWe comparisons into stable evidence that a later planner layer can use.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class PvDeviationEvaluatorConfig:
    """Deterministic thresholds for rolling PV forecast evidence."""

    window: timedelta = timedelta(minutes=15)
    minimum_history: timedelta = timedelta(minutes=10)
    deviation_threshold_percent: float = 25.0
    minimum_expected_power_w: float = 500.0


@dataclass(frozen=True, slots=True)
class PvDeviationSample:
    """One usable comparison sample."""

    observed_at: datetime
    expected_power_w: float
    actual_power_w: float


class PvDeviationEvaluator:
    """Classify persistent PV forecast deviation over a rolling time window."""

    def __init__(self, config: PvDeviationEvaluatorConfig | None = None) -> None:
        self.config = config or PvDeviationEvaluatorConfig()
        self._samples: deque[PvDeviationSample] = deque()

    def evaluate(self, event: dict[str, Any]) -> dict[str, object]:
        """Add the current comparison to history and return stable evidence fields."""

        status = event.get("pv_forecast_comparison_status")
        expected = event.get("pv_expected_power_w")
        actual = event.get("pv_actual_power_w")
        observed_raw = event.get("telemetry_updated_at")

        if (
            status != "available"
            or not _number(expected)
            or not _number(actual)
            or not isinstance(observed_raw, str)
        ):
            return self._result("unavailable", None, None, None)

        observed_at = datetime.fromisoformat(observed_raw.replace("Z", "+00:00"))
        expected_w = float(expected)
        actual_w = float(actual)
        self._discard_old_samples(observed_at)

        if expected_w < self.config.minimum_expected_power_w:
            return self._result("low_expected_power", None, None, None)

        self._samples.append(
            PvDeviationSample(
                observed_at=observed_at,
                expected_power_w=expected_w,
                actual_power_w=actual_w,
            )
        )
        self._discard_old_samples(observed_at)

        history_seconds = self._history_seconds()
        rolling_deviation = self._rolling_deviation_percent()
        if history_seconds < self.config.minimum_history.total_seconds():
            return self._result(
                "insufficient_history",
                rolling_deviation,
                history_seconds,
                len(self._samples),
            )

        assert rolling_deviation is not None
        threshold = self.config.deviation_threshold_percent
        if rolling_deviation <= -threshold:
            classification = "persistent_under_forecast"
        elif rolling_deviation >= threshold:
            classification = "persistent_over_forecast"
        else:
            classification = "within_tolerance"

        return self._result(
            classification,
            rolling_deviation,
            history_seconds,
            len(self._samples),
        )

    def _discard_old_samples(self, observed_at: datetime) -> None:
        cutoff = observed_at - self.config.window
        while self._samples and self._samples[0].observed_at < cutoff:
            self._samples.popleft()

    def _history_seconds(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        return (
            self._samples[-1].observed_at - self._samples[0].observed_at
        ).total_seconds()

    def _rolling_deviation_percent(self) -> float | None:
        if not self._samples:
            return None
        expected_total = sum(sample.expected_power_w for sample in self._samples)
        if expected_total <= 0.0:
            return None
        actual_total = sum(sample.actual_power_w for sample in self._samples)
        return ((actual_total - expected_total) / expected_total) * 100.0

    def _result(
        self,
        classification: str,
        rolling_deviation_percent: float | None,
        history_seconds: float | None,
        sample_count: int | None,
    ) -> dict[str, object]:
        return {
            "pv_deviation_evaluator_status": classification,
            "pv_rolling_deviation_percent": rolling_deviation_percent,
            "pv_deviation_history_seconds": history_seconds,
            "pv_deviation_sample_count": sample_count,
            "pv_deviation_window_seconds": self.config.window.total_seconds(),
            "pv_deviation_minimum_history_seconds": (
                self.config.minimum_history.total_seconds()
            ),
            "pv_deviation_threshold_percent": (
                self.config.deviation_threshold_percent
            ),
            "pv_deviation_minimum_expected_power_w": (
                self.config.minimum_expected_power_w
            ),
            "pv_deviation_replan_candidate": classification
            in {"persistent_under_forecast", "persistent_over_forecast"},
        }


def pv_deviation_evaluator_log_event(event: dict[str, Any]) -> dict[str, object]:
    """Return a compact log record for rolling PV-deviation evidence."""

    return {
        "event": "picot_pv_deviation_evaluator",
        "status": event.get("pv_deviation_evaluator_status"),
        "rolling_deviation_percent": event.get("pv_rolling_deviation_percent"),
        "history_seconds": event.get("pv_deviation_history_seconds"),
        "sample_count": event.get("pv_deviation_sample_count"),
        "window_seconds": event.get("pv_deviation_window_seconds"),
        "minimum_history_seconds": event.get(
            "pv_deviation_minimum_history_seconds"
        ),
        "threshold_percent": event.get("pv_deviation_threshold_percent"),
        "minimum_expected_power_w": event.get(
            "pv_deviation_minimum_expected_power_w"
        ),
        "replan_candidate": event.get("pv_deviation_replan_candidate"),
        "solcast_confidence": event.get("solcast_today_confidence"),
        "observed_at": event.get("telemetry_updated_at"),
    }


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
