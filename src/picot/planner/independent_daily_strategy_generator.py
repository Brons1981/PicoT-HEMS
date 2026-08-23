"""Generate an explicit unbiased daily intent-window search space."""

from __future__ import annotations

from picot.domain.daily_reference_charge_window import (
    DailyReferenceChargeWindowSet,
)
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_strategy_space import (
    DailyReferenceStrategySpace,
)
from picot.domain.household_load_forecast import HouseholdLoadForecast

METHOD_VERSION = "independent-daily-strategy-generator:v1"
BASELINE_INTENT = DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
DEFAULT_ACTIVE_INTENTS = (
    DailyStorageIntent.NOM,
    DailyStorageIntent.STANDBY,
    DailyStorageIntent.GRID_REQUIREMENT,
)


class IndependentDailyStrategyGenerator:
    """Enumerate schedules before any physical or financial ranking occurs."""

    def generate(
        self,
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        window_lengths_intervals: tuple[int, ...],
        active_intents: tuple[DailyStorageIntent, ...] = DEFAULT_ACTIVE_INTENTS,
        storage_export_target_wh_per_interval: float = 0.0,
    ) -> DailyReferenceStrategySpace:
        if not snapshot_id.strip():
            raise ValueError("Daily strategy snapshot must be explicit.")
        interval_count = len(household.intervals)
        lengths = tuple(dict.fromkeys(window_lengths_intervals))
        if not lengths or any(item <= 0 or item > interval_count for item in lengths):
            raise ValueError("Daily strategy window lengths must fit the horizon.")
        intents = tuple(dict.fromkeys(active_intents))
        if not intents or BASELINE_INTENT in intents:
            raise ValueError("Daily strategy active intents must exclude the baseline.")
        if storage_export_target_wh_per_interval < 0.0:
            raise ValueError("Daily strategy export target must not be negative.")
        if (
            DailyStorageIntent.STORAGE_EXPORT in intents
            and storage_export_target_wh_per_interval <= 0.0
        ):
            raise ValueError("Daily strategy export intent requires an export target.")

        schedules = [self._baseline(snapshot_id, household)]
        schedules.extend(
            self._window_schedule(
                snapshot_id=snapshot_id,
                household=household,
                intent=intent,
                start_index=start_index,
                length=length,
                storage_export_target_wh_per_interval=(
                    storage_export_target_wh_per_interval
                ),
            )
            for intent in intents
            for length in lengths
            for start_index in range(interval_count - length + 1)
        )
        return DailyReferenceStrategySpace(
            strategy_space_id=f"daily-strategy-space:{snapshot_id}",
            snapshot_id=snapshot_id,
            baseline_intent=BASELINE_INTENT,
            active_intents=intents,
            window_lengths_intervals=lengths,
            schedules=tuple(schedules),
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
        )

    def generate_from_charge_windows(
        self,
        *,
        charge_windows: DailyReferenceChargeWindowSet,
        household: HouseholdLoadForecast,
    ) -> DailyReferenceStrategySpace:
        """Build charging strategies only from physically minimal windows."""

        if charge_windows.discovery_status == "not_required":
            return DailyReferenceStrategySpace(
                strategy_space_id=(
                    f"daily-strategy-space:{charge_windows.snapshot_id}:"
                    "baseline-charge-not-required"
                ),
                snapshot_id=charge_windows.snapshot_id,
                baseline_intent=BASELINE_INTENT,
                active_intents=(),
                window_lengths_intervals=(),
                schedules=(
                    self._baseline(charge_windows.snapshot_id, household),
                ),
                observer_only=True,
                ranking_permitted=False,
                method_version=METHOD_VERSION,
                source_charge_window_set_id=charge_windows.window_set_id,
                charge_requirement_status="not_required",
            )
        if not charge_windows.windows:
            raise ValueError("Daily strategy requires proven charge windows.")
        if any(
            item.schedule.horizon_start != household.horizon_start
            or item.schedule.horizon_end != household.horizon_end
            for item in charge_windows.windows
        ):
            raise ValueError("Daily charge windows and household horizon must match.")
        intents = tuple(
            dict.fromkeys(item.intent for item in charge_windows.windows)
        )
        lengths = tuple(
            dict.fromkeys(item.interval_count for item in charge_windows.windows)
        )
        return DailyReferenceStrategySpace(
            strategy_space_id=(
                f"daily-strategy-space:{charge_windows.snapshot_id}:"
                "physical-charge-windows"
            ),
            snapshot_id=charge_windows.snapshot_id,
            baseline_intent=BASELINE_INTENT,
            active_intents=intents,
            window_lengths_intervals=lengths,
            schedules=(
                self._baseline(charge_windows.snapshot_id, household),
                *(item.schedule for item in charge_windows.windows),
            ),
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
            source_charge_window_set_id=charge_windows.window_set_id,
        )

    @staticmethod
    def _baseline(
        snapshot_id: str,
        household: HouseholdLoadForecast,
    ) -> DailyReferenceIntentSchedule:
        return DailyReferenceIntentSchedule(
            schedule_id=f"daily-strategy:{snapshot_id}:baseline-household-support",
            snapshot_id=snapshot_id,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            intervals=tuple(
                DailyReferenceIntentInterval(
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    intent=BASELINE_INTENT,
                )
                for item in household.intervals
            ),
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _window_schedule(
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        intent: DailyStorageIntent,
        start_index: int,
        length: int,
        storage_export_target_wh_per_interval: float,
    ) -> DailyReferenceIntentSchedule:
        end_index = start_index + length
        return DailyReferenceIntentSchedule(
            schedule_id=(
                f"daily-strategy:{snapshot_id}:{intent.value}:"
                f"start-{start_index}:length-{length}"
            ),
            snapshot_id=snapshot_id,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            intervals=tuple(
                DailyReferenceIntentInterval(
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    intent=(
                        intent
                        if start_index <= index < end_index
                        else BASELINE_INTENT
                    ),
                    storage_export_target_wh=(
                        storage_export_target_wh_per_interval
                        if intent is DailyStorageIntent.STORAGE_EXPORT
                        and start_index <= index < end_index
                        else 0.0
                    ),
                )
                for index, item in enumerate(household.intervals)
            ),
            method_version=METHOD_VERSION,
        )
