"""Deterministic weighted household-load forecast from PicoT runtime history.

ADR-037 permits a simple weighted historical profile for the first implementation.
This forecaster consumes PicoT-owned historical planning snapshots only; it does
not query Home Assistant history and it never depends on sensor.picot_* mirrors.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import isfinite

from picot.addon.history_store import HistoryStore
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)
from picot.domain.pv_energy_timeline import PVEnergyTimeline

METHOD_VERSION = "weighted-quarter-hour-profile-v1"
HISTORY_DAYS = 14
MIN_CONFIDENCE = 0.10
GLOBAL_FALLBACK_CONFIDENCE = 0.20
MAX_PROFILE_CONFIDENCE = 0.90


@dataclass(frozen=True, slots=True)
class LoadSample:
    measured_at: datetime
    power_w: float


@dataclass(slots=True)
class HouseholdLoadForecaster:
    """Maintain a deterministic recent-history profile in memory."""

    history: HistoryStore = field(default_factory=HistoryStore)
    _samples: list[LoadSample] = field(default_factory=list)
    _loaded: bool = False

    def _load_history_once(self, now: datetime) -> None:
        if self._loaded:
            return
        start = now - timedelta(days=HISTORY_DAYS)
        for event in self.history.iter_range(start, now):
            if event.get("event") != "picot_live_planning_snapshot":
                continue
            power = event.get("household_load_w")
            measured = event.get("captured_at") or event.get("observed_at")
            if (
                isinstance(power, bool)
                or not isinstance(power, (int, float))
                or not isinstance(measured, str)
            ):
                continue
            moment = datetime.fromisoformat(measured.replace("Z", "+00:00"))
            if moment.tzinfo is None or moment.utcoffset() is None:
                continue
            value = float(power)
            if value < 0 or not isfinite(value):
                continue
            self._samples.append(LoadSample(moment, value))
        self._loaded = True
        self._prune(now)

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(days=HISTORY_DAYS)
        self._samples[:] = [sample for sample in self._samples if sample.measured_at >= cutoff]

    def observe(self, *, measured_at: datetime, household_load_w: float | None) -> None:
        """Add the current canonical household observation to the in-memory profile."""

        self._load_history_once(measured_at)
        if household_load_w is None or household_load_w < 0 or not isfinite(household_load_w):
            return
        self._samples.append(LoadSample(measured_at, household_load_w))
        self._prune(measured_at)

    @staticmethod
    def _slot(moment: datetime) -> tuple[int, int]:
        local = moment.astimezone()
        return local.hour, local.minute // 15

    @staticmethod
    def _weight(sample: LoadSample, now: datetime) -> float:
        age_days = max(0.0, (now - sample.measured_at).total_seconds() / 86400.0)
        return 1.0 / (1.0 + age_days)

    def _profile(self, now: datetime) -> tuple[dict[tuple[int, int], tuple[float, float]], float | None]:
        self._load_history_once(now)
        grouped: dict[tuple[int, int], list[LoadSample]] = defaultdict(list)
        for sample in self._samples:
            grouped[self._slot(sample.measured_at)].append(sample)

        profile: dict[tuple[int, int], tuple[float, float]] = {}
        for slot, samples in grouped.items():
            weighted_sum = 0.0
            total_weight = 0.0
            distinct_days: set[object] = set()
            for sample in samples:
                weight = self._weight(sample, now)
                weighted_sum += sample.power_w * weight
                total_weight += weight
                distinct_days.add(sample.measured_at.astimezone().date())
            if total_weight <= 0:
                continue
            confidence = min(MAX_PROFILE_CONFIDENCE, 0.30 + 0.10 * len(distinct_days))
            profile[slot] = (weighted_sum / total_weight, confidence)

        if not self._samples:
            return profile, None
        weighted_sum = 0.0
        total_weight = 0.0
        for sample in self._samples:
            weight = self._weight(sample, now)
            weighted_sum += sample.power_w * weight
            total_weight += weight
        return profile, (weighted_sum / total_weight if total_weight > 0 else None)

    def forecast(
        self,
        *,
        captured_at: datetime,
        pv_timeline: PVEnergyTimeline,
        current_household_load_w: float | None,
        sequence: int,
    ) -> HouseholdLoadForecast:
        """Forecast baseline load on exactly the canonical PV interval boundaries."""

        profile, global_average = self._profile(captured_at)
        fallback_power = global_average
        fallback_confidence = GLOBAL_FALLBACK_CONFIDENCE
        source_reference = f"picot_history:last_{HISTORY_DAYS}_days"
        if fallback_power is None:
            fallback_power = max(0.0, current_household_load_w or 0.0)
            fallback_confidence = MIN_CONFIDENCE
            source_reference = "fallback:current_household_load"

        intervals: list[HouseholdLoadForecastInterval] = []
        for pv_interval in pv_timeline.intervals:
            cursor = pv_interval.starts_at
            weighted_energy_wh = 0.0
            confidence_values: list[float] = []
            while cursor < pv_interval.ends_at:
                quarter_end = min(
                    pv_interval.ends_at,
                    cursor.replace(second=0, microsecond=0)
                    + timedelta(minutes=15 - (cursor.minute % 15)),
                )
                if quarter_end <= cursor:
                    quarter_end = min(pv_interval.ends_at, cursor + timedelta(minutes=15))
                power_w, confidence = profile.get(
                    self._slot(cursor),
                    (fallback_power, fallback_confidence),
                )
                hours = (quarter_end - cursor).total_seconds() / 3600.0
                weighted_energy_wh += max(0.0, power_w) * hours
                confidence_values.append(confidence)
                cursor = quarter_end
            intervals.append(
                HouseholdLoadForecastInterval(
                    starts_at=pv_interval.starts_at,
                    ends_at=pv_interval.ends_at,
                    expected_energy_wh=weighted_energy_wh,
                    confidence=min(confidence_values) if confidence_values else MIN_CONFIDENCE,
                )
            )

        return HouseholdLoadForecast(
            forecast_id=f"live-household-load-{sequence}",
            created_at=captured_at,
            horizon_start=pv_timeline.horizon_start,
            horizon_end=pv_timeline.horizon_end,
            intervals=tuple(intervals),
            historical_source_reference=source_reference,
            method_version=METHOD_VERSION,
        )
