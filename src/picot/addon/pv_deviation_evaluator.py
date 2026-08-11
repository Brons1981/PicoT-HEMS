"""Rolling observation-only evaluator for PV forecast deviation.

The evaluator deliberately does not trigger replanning from the experimental
energy windows. It keeps the existing rolling power-based evidence intact while
also integrating Solcast expected power and GoodWe actual power over 15, 30 and
60 minute windows for later analysis.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeGuard

ENERGY_WINDOWS_MINUTES = (15, 30, 60)
ENERGY_WINDOW_COVERAGE_RATIO = 0.95


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
        self._energy_samples: deque[PvDeviationSample] = deque()

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
            result = self._result("unavailable", None, None, None)
            result.update(self._energy_window_results())
            return result

        observed_at = datetime.fromisoformat(observed_raw.replace("Z", "+00:00"))
        expected_w = float(expected)
        actual_w = float(actual)
        sample = PvDeviationSample(
            observed_at=observed_at,
            expected_power_w=expected_w,
            actual_power_w=actual_w,
        )
        self._append_energy_sample(sample)
        self._discard_old_samples(observed_at)

        if expected_w < self.config.minimum_expected_power_w:
            result = self._result("low_expected_power", None, None, None)
            result.update(self._energy_window_results(observed_at))
            return result

        self._samples.append(sample)
        self._discard_old_samples(observed_at)

        history_seconds = self._history_seconds()
        rolling_deviation = self._rolling_deviation_percent()
        if history_seconds < self.config.minimum_history.total_seconds():
            result = self._result(
                "insufficient_history",
                rolling_deviation,
                history_seconds,
                len(self._samples),
            )
            result.update(self._energy_window_results(observed_at))
            return result

        assert rolling_deviation is not None
        threshold = self.config.deviation_threshold_percent
        if rolling_deviation <= -threshold:
            classification = "persistent_under_forecast"
        elif rolling_deviation >= threshold:
            classification = "persistent_over_forecast"
        else:
            classification = "within_tolerance"

        result = self._result(
            classification,
            rolling_deviation,
            history_seconds,
            len(self._samples),
        )
        result.update(self._energy_window_results(observed_at))
        return result

    def _append_energy_sample(self, sample: PvDeviationSample) -> None:
        self._energy_samples.append(sample)
        cutoff = sample.observed_at - timedelta(minutes=max(ENERGY_WINDOWS_MINUTES))
        while len(self._energy_samples) >= 2 and self._energy_samples[1].observed_at < cutoff:
            self._energy_samples.popleft()

    def _energy_window_results(
        self, observed_at: datetime | None = None
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        if observed_at is None and self._energy_samples:
            observed_at = self._energy_samples[-1].observed_at

        for minutes in ENERGY_WINDOWS_MINUTES:
            prefix = f"pv_energy_{minutes}m"
            if observed_at is None:
                result.update(
                    {
                        f"{prefix}_status": "insufficient_history",
                        f"{prefix}_expected_kwh": None,
                        f"{prefix}_actual_kwh": None,
                        f"{prefix}_deviation_percent": None,
                        f"{prefix}_coverage_seconds": 0.0,
                    }
                )
                continue

            expected_kwh, actual_kwh, coverage_seconds = self._integrate_window(
                observed_at,
                timedelta(minutes=minutes),
            )
            required_coverage = minutes * 60.0 * ENERGY_WINDOW_COVERAGE_RATIO
            if coverage_seconds < required_coverage:
                status = "insufficient_history"
                deviation = None
            elif expected_kwh <= 0.0:
                status = "insufficient_expected_energy"
                deviation = None
            else:
                status = "available"
                deviation = ((actual_kwh - expected_kwh) / expected_kwh) * 100.0

            result.update(
                {
                    f"{prefix}_status": status,
                    f"{prefix}_expected_kwh": expected_kwh,
                    f"{prefix}_actual_kwh": actual_kwh,
                    f"{prefix}_deviation_percent": deviation,
                    f"{prefix}_coverage_seconds": coverage_seconds,
                }
            )
        return result

    def _integrate_window(
        self,
        observed_at: datetime,
        window: timedelta,
    ) -> tuple[float, float, float]:
        """Integrate expected/actual power over one window using trapezoids."""

        if len(self._energy_samples) < 2:
            return 0.0, 0.0, 0.0

        cutoff = observed_at - window
        samples = list(self._energy_samples)
        expected_wh = 0.0
        actual_wh = 0.0
        coverage_seconds = 0.0

        for left, right in zip(samples, samples[1:], strict=False):
            interval_start = max(left.observed_at, cutoff)
            interval_end = min(right.observed_at, observed_at)
            if interval_end <= interval_start:
                continue

            total_seconds = (right.observed_at - left.observed_at).total_seconds()
            if total_seconds <= 0.0:
                continue

            start_fraction = (
                interval_start - left.observed_at
            ).total_seconds() / total_seconds
            end_fraction = (
                interval_end - left.observed_at
            ).total_seconds() / total_seconds

            expected_start = left.expected_power_w + (
                right.expected_power_w - left.expected_power_w
            ) * start_fraction
            expected_end = left.expected_power_w + (
                right.expected_power_w - left.expected_power_w
            ) * end_fraction
            actual_start = left.actual_power_w + (
                right.actual_power_w - left.actual_power_w
            ) * start_fraction
            actual_end = left.actual_power_w + (
                right.actual_power_w - left.actual_power_w
            ) * end_fraction

            seconds = (interval_end - interval_start).total_seconds()
            expected_wh += ((expected_start + expected_end) / 2.0) * seconds / 3600.0
            actual_wh += ((actual_start + actual_end) / 2.0) * seconds / 3600.0
            coverage_seconds += seconds

        return expected_wh / 1000.0, actual_wh / 1000.0, coverage_seconds

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
    """Return persistent rolling PV and energy-window observation evidence."""

    record: dict[str, object] = {
        "event": "picot_pv_deviation_evaluator",
        "layer": "pv_forecast_validation",
        "observation_only": True,
        "energy_windows_replan_input": False,
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
    for minutes in ENERGY_WINDOWS_MINUTES:
        prefix = f"pv_energy_{minutes}m"
        record[f"energy_{minutes}m_status"] = event.get(f"{prefix}_status")
        record[f"energy_{minutes}m_expected_kwh"] = event.get(
            f"{prefix}_expected_kwh"
        )
        record[f"energy_{minutes}m_actual_kwh"] = event.get(f"{prefix}_actual_kwh")
        record[f"energy_{minutes}m_deviation_percent"] = event.get(
            f"{prefix}_deviation_percent"
        )
        record[f"energy_{minutes}m_coverage_seconds"] = event.get(
            f"{prefix}_coverage_seconds"
        )
    return record


def _number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
