"""Fail-closed adapter from shared v2 Planning Input to the daily simulator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    EnergyFlowDirection,
)
from picot.domain.current_storage_state import CurrentStorageState as DomainStorageState
from picot.domain.daily_reference_charge_window import (
    DailyReferenceChargeWindow,
    DailyReferenceChargeWindowSet,
)
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import DailyReferenceSimulationSet, PVScenario
from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
from picot.domain.daily_reference_strategy_space import DailyReferenceStrategySpace
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffSchedule,
)
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast as DomainHouseholdForecast,
)
from picot.domain.household_load_forecast import (
    HouseholdLoadForecastInterval as DomainHouseholdInterval,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyTimeline as DomainPVTimeline,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyTimelineInterval as DomainPVInterval,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from picot.planner.independent_daily_simulator import (
    IndependentDailySimulator,
    ScenarioTimeline,
)
from picot.planner.independent_daily_strategy_generator import (
    IndependentDailyStrategyGenerator,
)
from picot.planner.independent_daily_strategy_observer import (
    IndependentDailyStrategyObserver,
)
from picot.v2.contracts import (
    HouseholdLoadForecast,
    PlanningInputSnapshot,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.independent_daily_tariff_adapter import (
    IndependentDailyTariffAdapter,
)
from picot.v2.plan_commitment_store import active_pv_preservation_dates

METHOD_VERSION = "v2-independent-daily-reference-adapter:v7"
DAILY_REFERENCE_DURATION = timedelta(hours=24)


class DailyReferenceInputError(ValueError):
    """The shared snapshot cannot prove a complete independent simulation input."""


@dataclass(frozen=True, slots=True)
class _DailyReferenceInputs:
    household: DomainHouseholdForecast
    pv_scenarios: tuple[ScenarioTimeline, ...]
    storage: DomainStorageState
    minimum_storage_energy_wh: float
    target_storage_energy_wh: float
    maximum_charge_input_power_w: float
    maximum_discharge_output_power_w: float


class IndependentDailyReferenceAdapter:
    """Build and run the daily simulation without reading planner Candidates."""

    def simulate(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
    ) -> DailyReferenceSimulationSet:
        inputs = self._inputs(snapshot)
        return IndependentDailySimulator().simulate(
            snapshot_id=snapshot.snapshot_id,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
            storage_state=inputs.storage,
            conversion_model=conversion_model,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
        )

    def observe(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
        tariffs: DailyReferenceTariffSchedule | None = None,
        maximum_duration: timedelta = DAILY_REFERENCE_DURATION,
        micro_charge_suppression_fraction: float = 0.01,
        required_by: datetime | None = None,
        preferred_grid_windows: tuple[tuple[datetime, datetime], ...] = (),
        preserve_pv_during_grid_charge: bool = False,
        saldering_energy_tax_credit_enabled: bool = True,
    ) -> DailyReferenceStrategyObservation:
        """Run the complete observer chain from one immutable Planning Input."""

        maximum_horizon_end = snapshot.captured_at + maximum_duration
        if tariffs is None:
            tariff_adapter = IndependentDailyTariffAdapter()
            published_horizon_end = tariff_adapter.published_horizon_end(
                snapshot,
                maximum_horizon_end=maximum_horizon_end,
            )
            inputs = self._inputs(
                snapshot,
                horizon_end=published_horizon_end,
                maximum_duration=maximum_duration,
            )
            tariffs = tariff_adapter.build(
                snapshot,
                horizon_end=published_horizon_end,
                saldering_energy_tax_credit_enabled=(
                    saldering_energy_tax_credit_enabled
                ),
            )
        else:
            inputs = self._inputs(
                snapshot,
                horizon_end=tariffs.horizon_end,
                maximum_duration=maximum_duration,
            )
        self._validate_tariffs(snapshot, inputs.household, tariffs)
        charge_windows = IndependentDailyChargeWindowDiscoverer().discover(
            snapshot_id=snapshot.snapshot_id,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
            storage_state=inputs.storage,
            conversion_model=conversion_model,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
            micro_charge_suppression_fraction=micro_charge_suppression_fraction,
            charge_session_active=(
                snapshot.storage_mode_capability_evidence is not None
                and snapshot.storage_mode_capability_evidence.current_vendor_mode
                in {"Nul op de meter", "Snel opladen"}
            ),
            required_by=required_by,
        )
        if charge_windows.discovery_status == "no_feasible_window":
            raise DailyReferenceInputError("daily_reference_charge_windows_unavailable")
        charge_windows = self._select_representative_charge_paths(
            charge_windows,
            tariffs=tariffs,
            required_by=required_by,
            preferred_grid_windows=preferred_grid_windows,
            preserve_pv_during_grid_charge=preserve_pv_during_grid_charge,
        )
        strategy_space = IndependentDailyStrategyGenerator().generate_from_charge_windows(
            charge_windows=charge_windows,
            household=inputs.household,
        )
        if charge_windows.hybrid_schedules:
            # A hybrid supersedes only the isolated grid component.  The
            # physically complete PV-only path must remain independently
            # evaluable; otherwise merely discovering residual grid charging
            # removes the cheaper PV-first alternative from the portfolio.
            component_schedule_ids = {
                item.schedule.schedule_id
                for item in charge_windows.windows
                if item.intent is DailyStorageIntent.GRID_REQUIREMENT
            }
            strategy_space = replace(
                strategy_space,
                schedules=tuple(
                    item
                    for item in strategy_space.schedules
                    if item.schedule_id not in component_schedule_ids
                ),
            )
        if preserve_pv_during_grid_charge:
            strategy_space = self._preserve_pv_across_grid_charge_days(
                strategy_space,
                snapshot=snapshot,
                charge_windows=charge_windows,
                pv_scenarios=inputs.pv_scenarios,
            )
        pv_capture_schedule = self._pv_capture_schedule(
            snapshot_id=snapshot.snapshot_id,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
        )
        if (
            strategy_space.charge_requirement_status == "required"
            and pv_capture_schedule is not None
            and all(
                item.intervals != pv_capture_schedule.intervals for item in strategy_space.schedules
            )
        ):
            strategy_space = replace(
                strategy_space,
                schedules=(*strategy_space.schedules, pv_capture_schedule),
                active_intents=tuple(
                    dict.fromkeys((*strategy_space.active_intents, DailyStorageIntent.NOM))
                ),
            )
        return IndependentDailyStrategyObserver().observe(
            strategy_space=strategy_space,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
            storage_state=inputs.storage,
            conversion_model=conversion_model,
            tariffs=tariffs,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
        )

    @staticmethod
    def _preserve_pv_across_grid_charge_days(
        strategy_space: DailyReferenceStrategySpace,
        *,
        snapshot: PlanningInputSnapshot,
        charge_windows: DailyReferenceChargeWindowSet,
        pv_scenarios: tuple[ScenarioTimeline, ...],
    ) -> DailyReferenceStrategySpace:
        """Project the User Rule onto every bounded path for the same day.

        Candidate Generation already selected at most one residual-grid path.
        Its grid day is therefore a deterministic boundary: every existing
        candidate keeps storage bidirectional wherever the Solcast upper
        scenario still permits PV on that day. Explicit grid charge and export
        remain overlays. No schedules, routes, or timing alternatives are added.
        """

        grid_days = {
            interval.starts_at.date()
            for schedule in charge_windows.hybrid_schedules
            for interval in schedule.intervals
            if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
        }
        grid_days.update(
            day
            for commitment in snapshot.active_plan_commitments
            for day in active_pv_preservation_dates(
                commitment,
                captured_at=snapshot.captured_at,
            )
        )
        if not grid_days:
            return strategy_space
        upper = next(item for item in pv_scenarios if item.scenario is PVScenario.UPPER)

        def possible_pv(interval: DailyReferenceIntentInterval) -> bool:
            return interval.starts_at.date() in grid_days and any(
                pv.energy_wh > 1e-6
                and interval.starts_at < pv.ends_at
                and interval.ends_at > pv.starts_at
                for pv in upper.timeline.intervals
            )

        schedules: list[DailyReferenceIntentSchedule] = []
        for schedule in strategy_space.schedules:
            intervals = tuple(
                replace(interval, intent=DailyStorageIntent.NOM)
                if possible_pv(interval)
                and interval.intent
                not in {
                    DailyStorageIntent.GRID_REQUIREMENT,
                    DailyStorageIntent.STORAGE_EXPORT,
                }
                else interval
                for interval in schedule.intervals
            )
            schedules.append(
                replace(
                    schedule,
                    schedule_id=(
                        f"{schedule.schedule_id}:preserve-pv-day"
                        if intervals != schedule.intervals
                        else schedule.schedule_id
                    ),
                    intervals=intervals,
                )
            )
        return replace(strategy_space, schedules=tuple(schedules))

    @classmethod
    def _select_representative_charge_paths(
        cls,
        charge_windows: DailyReferenceChargeWindowSet,
        *,
        tariffs: DailyReferenceTariffSchedule,
        required_by: datetime | None,
        preferred_grid_windows: tuple[tuple[datetime, datetime], ...],
        preserve_pv_during_grid_charge: bool = False,
    ) -> DailyReferenceChargeWindowSet:
        """Reduce physical alternatives before complete portfolio simulation.

        ADR-017/024 require confidence and economic relevance to reduce the
        search space before full simulation.  The physical discoverer may
        prove many interval-minimal starts; MEP retains the PV-only path with
        the lowest foregone export value plus one cheapest residual-grid path.
        A hybrid path supersedes pure grid charging when it exists.
        """

        if charge_windows.discovery_status != "discovered":
            return charge_windows

        nom_windows = tuple(
            item for item in charge_windows.windows if item.intent is DailyStorageIntent.NOM
        )
        grid_windows = tuple(
            item
            for item in charge_windows.windows
            if item.intent is DailyStorageIntent.GRID_REQUIREMENT
        )
        selected_nom = min(
            nom_windows,
            key=lambda item: (
                cls._nom_schedule_cost(item.schedule, tariffs),
                -item.starts_at.timestamp(),
                item.window_id,
            ),
            default=None,
        )
        preferred_hybrids = tuple(
            item
            for item in charge_windows.hybrid_schedules
            if cls._starts_in_preferred_window(cls._grid_start(item), preferred_grid_windows)
        )
        eligible_hybrids = preferred_hybrids or charge_windows.hybrid_schedules
        selected_hybrid = min(
            eligible_hybrids,
            key=lambda item: (
                cls._grid_schedule_cost(item, tariffs),
                -cls._grid_start(item).timestamp(),
                item.schedule_id,
            ),
            default=None,
        )
        if selected_hybrid is not None and preserve_pv_during_grid_charge:
            selected_hybrid = cls._preserve_pv_around_grid_charge(selected_hybrid)
        preferred_grid = tuple(
            item
            for item in grid_windows
            if cls._starts_in_preferred_window(item.starts_at, preferred_grid_windows)
        )
        eligible_grid = preferred_grid or grid_windows
        selected_grid = (
            min(eligible_grid, key=lambda item: item.starts_at, default=None)
            if required_by is None and selected_hybrid is None
            else max(
                eligible_grid,
                key=lambda item: (item.starts_at, item.window_id),
                default=None,
            )
            if not preferred_grid_windows
            else min(
                eligible_grid,
                key=lambda item: (
                    cls._grid_schedule_cost(item.schedule, tariffs),
                    -item.starts_at.timestamp(),
                    item.window_id,
                ),
                default=None,
            )
        )

        retained_windows: list[DailyReferenceChargeWindow] = []
        if selected_nom is not None:
            retained_windows.append(selected_nom)
        # The WindowSet contract retains one proven component beside a hybrid;
        # the Strategy Generator publishes only the composed path.
        if selected_grid is not None and (selected_hybrid is None or selected_nom is None):
            retained_windows.append(selected_grid)
        return DailyReferenceChargeWindowSet(
            window_set_id=charge_windows.window_set_id,
            snapshot_id=charge_windows.snapshot_id,
            windows=tuple(retained_windows),
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
            discovery_status="discovered",
            hybrid_schedules=((selected_hybrid,) if selected_hybrid is not None else ()),
        )

    @staticmethod
    def _preserve_pv_around_grid_charge(
        schedule: DailyReferenceIntentSchedule,
    ) -> DailyReferenceIntentSchedule:
        """Keep PV capture admissible before and after residual grid charging.

        The physical discoverer has already bounded the grid duration.  This
        user-rule projection changes no grid energy; it only prevents a
        household-discharge gap between the PV-capture path and that grid
        block, and restores NOM for one interval afterwards.  That gives live
        PV which exceeds the forecast an immediate storage path without
        creating another combinatorial timing search.
        """

        grid_indexes = tuple(
            index
            for index, interval in enumerate(schedule.intervals)
            if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
        )
        if not grid_indexes:
            return schedule
        first_grid = grid_indexes[0]
        last_grid = grid_indexes[-1]
        existing_nom = tuple(
            index
            for index, interval in enumerate(schedule.intervals)
            if interval.intent is DailyStorageIntent.NOM
        )
        capture_start = min(existing_nom, default=max(first_grid - 1, 0))
        # The discoverer already bounded NOM to the complete Solcast surplus
        # projection. Preserve that full window; the residual grid block is an
        # overlay, not a reason to return to household support early.
        capture_end = max(
            max(existing_nom, default=0),
            min(last_grid + 1, len(schedule.intervals) - 1),
        )
        intervals = tuple(
            replace(interval, intent=DailyStorageIntent.NOM)
            if capture_start <= index <= capture_end
            and interval.intent is not DailyStorageIntent.GRID_REQUIREMENT
            else interval
            for index, interval in enumerate(schedule.intervals)
        )
        return replace(
            schedule,
            schedule_id=f"{schedule.schedule_id}:preserve-pv",
            intervals=intervals,
        )

    @staticmethod
    def _pv_capture_schedule(
        *,
        snapshot_id: str,
        household: DomainHouseholdForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
    ) -> DailyReferenceIntentSchedule | None:
        """Publish one physical NOM path exactly where conservative PV exists."""

        conservative = next(item for item in pv_scenarios if item.scenario is PVScenario.LOWER)
        intervals = tuple(
            DailyReferenceIntentInterval(
                starts_at=load.starts_at,
                ends_at=load.ends_at,
                intent=(
                    DailyStorageIntent.NOM
                    if pv.energy_wh > 1e-6
                    else DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
                ),
            )
            for load, pv in zip(
                household.intervals,
                conservative.timeline.intervals,
                strict=True,
            )
        )
        if not any(item.intent is DailyStorageIntent.NOM for item in intervals):
            return None
        return DailyReferenceIntentSchedule(
            schedule_id=f"daily-strategy:{snapshot_id}:conservative-pv-capture",
            snapshot_id=snapshot_id,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            intervals=intervals,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _grid_start(schedule: DailyReferenceIntentSchedule) -> datetime:
        return next(
            item.starts_at
            for item in schedule.intervals
            if item.intent is DailyStorageIntent.GRID_REQUIREMENT
        )

    @staticmethod
    def _starts_in_preferred_window(
        starts_at: datetime,
        windows: tuple[tuple[datetime, datetime], ...],
    ) -> bool:
        return any(start <= starts_at < end for start, end in windows)

    @staticmethod
    def _grid_schedule_cost(
        schedule: DailyReferenceIntentSchedule,
        tariffs: DailyReferenceTariffSchedule,
    ) -> float:
        total_eur_per_kw = 0.0
        for planned in schedule.intervals:
            if planned.intent is not DailyStorageIntent.GRID_REQUIREMENT:
                continue
            for tariff in tariffs.intervals:
                overlap_start = max(planned.starts_at, tariff.starts_at)
                overlap_end = min(planned.ends_at, tariff.ends_at)
                if overlap_end <= overlap_start:
                    continue
                total_eur_per_kw += (
                    (overlap_end - overlap_start).total_seconds()
                    / 3600.0
                    * tariff.import_eur_per_kwh
                )
        return total_eur_per_kw

    @staticmethod
    def _nom_schedule_cost(
        schedule: DailyReferenceIntentSchedule,
        tariffs: DailyReferenceTariffSchedule,
    ) -> float:
        """Value the PV retained by NOM at its foregone export tariff."""

        total_eur_per_kw = 0.0
        for planned in schedule.intervals:
            if planned.intent is not DailyStorageIntent.NOM:
                continue
            for tariff in tariffs.intervals:
                overlap_start = max(planned.starts_at, tariff.starts_at)
                overlap_end = min(planned.ends_at, tariff.ends_at)
                if overlap_end <= overlap_start:
                    continue
                total_eur_per_kw += (
                    (overlap_end - overlap_start).total_seconds()
                    / 3600.0
                    * tariff.export_eur_per_kwh
                )
        return total_eur_per_kw

    def build_inputs(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        horizon_end: datetime | None = None,
        maximum_duration: timedelta = DAILY_REFERENCE_DURATION,
    ) -> _DailyReferenceInputs:
        """Expose the validated simulator inputs to composition-only planners."""

        return self._inputs(
            snapshot,
            horizon_end=horizon_end,
            maximum_duration=maximum_duration,
        )

    def _inputs(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        horizon_end: datetime | None = None,
        maximum_duration: timedelta = DAILY_REFERENCE_DURATION,
    ) -> _DailyReferenceInputs:
        if snapshot.horizon_end is None:
            raise DailyReferenceInputError("daily_reference_horizon_missing")
        if snapshot.household_load_forecast is None:
            raise DailyReferenceInputError("daily_reference_household_missing")
        if snapshot.pv_energy_timeline is None:
            raise DailyReferenceInputError("daily_reference_pv_missing")
        if len(snapshot.current_storage_states) != 1:
            raise DailyReferenceInputError("daily_reference_storage_scope_ambiguous")
        storage = snapshot.current_storage_states[0]
        capability_set = snapshot.capability_snapshot_set
        if capability_set is None:
            raise DailyReferenceInputError("daily_reference_capability_missing")
        if (
            capability_set.snapshot_id != snapshot.snapshot_id
            or capability_set.captured_at != snapshot.captured_at
        ):
            raise DailyReferenceInputError("daily_reference_capability_lineage_mismatch")
        capabilities = tuple(
            item
            for item in capability_set.capabilities
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
        )
        if len(capabilities) != 1:
            raise DailyReferenceInputError("daily_reference_capability_ambiguous")
        capability = capabilities[0]
        if (
            capability.availability is not CapabilityAvailability.AVAILABLE
            or capability.health is not CapabilityHealth.HEALTHY
        ):
            raise DailyReferenceInputError("daily_reference_capability_unavailable")
        directions = set(capability.flow_directions)
        if EnergyFlowDirection.BIDIRECTIONAL not in directions and not {
            EnergyFlowDirection.CHARGE,
            EnergyFlowDirection.DISCHARGE,
        }.issubset(directions):
            raise DailyReferenceInputError("daily_reference_directions_incomplete")
        physical_limits = tuple(
            item
            for item in snapshot.storage_physical_limits
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
        )
        if len(physical_limits) != 1:
            raise DailyReferenceInputError("daily_reference_physical_limits_missing")
        limits = physical_limits[0]
        maximum_reference_horizon_end = snapshot.captured_at + maximum_duration
        reference_horizon_end = horizon_end or maximum_reference_horizon_end
        if snapshot.horizon_end < reference_horizon_end:
            raise DailyReferenceInputError("daily_reference_horizon_too_short")
        if (
            reference_horizon_end <= snapshot.captured_at
            or reference_horizon_end > maximum_reference_horizon_end
        ):
            raise DailyReferenceInputError("daily_reference_horizon_invalid")

        household = self._household(
            snapshot.household_load_forecast,
            captured_at=snapshot.captured_at,
            horizon_end=reference_horizon_end,
        )
        pv_scenarios = self._pv_scenarios(
            snapshot.pv_energy_timeline,
            household=household,
            captured_at=snapshot.captured_at,
        )
        domain_storage = DomainStorageState(
            storage_state_id=storage.storage_state_id,
            execution_scope_id=storage.execution_scope_id,
            capability_id=storage.capability_id,
            current_soc=storage.current_soc,
            usable_capacity_wh=storage.usable_capacity_wh,
            measured_at=storage.measured_at,
            confidence=storage.confidence,
            evidence_ids=storage.evidence_ids,
        )
        return _DailyReferenceInputs(
            household=household,
            pv_scenarios=pv_scenarios,
            storage=domain_storage,
            minimum_storage_energy_wh=(limits.minimum_soc * storage.usable_capacity_wh),
            target_storage_energy_wh=(limits.maximum_soc * storage.usable_capacity_wh),
            maximum_charge_input_power_w=(limits.maximum_charge_input_power_w),
            maximum_discharge_output_power_w=(limits.maximum_discharge_output_power_w),
        )

    @staticmethod
    def _validate_tariffs(
        snapshot: PlanningInputSnapshot,
        household: DomainHouseholdForecast,
        tariffs: DailyReferenceTariffSchedule,
    ) -> None:
        if tariffs.snapshot_id != snapshot.snapshot_id:
            raise DailyReferenceInputError("daily_reference_tariff_lineage_mismatch")
        if (
            tariffs.horizon_start != household.horizon_start
            or tariffs.horizon_end != household.horizon_end
        ):
            raise DailyReferenceInputError("daily_reference_tariff_horizon_mismatch")

    @staticmethod
    def _household(
        forecast: HouseholdLoadForecast,
        *,
        captured_at: datetime,
        horizon_end: datetime,
    ) -> DomainHouseholdForecast:
        source_intervals = tuple(
            interval
            for interval in forecast.intervals
            if interval.starts_at < horizon_end and interval.ends_at > captured_at
        )
        if not source_intervals:
            raise DailyReferenceInputError("daily_reference_household_empty")
        boundaries = [captured_at]
        next_quarter = captured_at.replace(second=0, microsecond=0)
        remainder = next_quarter.minute % 15
        if remainder:
            next_quarter += timedelta(minutes=15 - remainder)
        elif next_quarter < captured_at:
            next_quarter += timedelta(minutes=15)
        if captured_at < next_quarter < horizon_end:
            boundaries.append(next_quarter)
        while boundaries[-1] + timedelta(minutes=15) < horizon_end:
            boundaries.append(boundaries[-1] + timedelta(minutes=15))
        if boundaries[-1] != horizon_end:
            boundaries.append(horizon_end)

        normalised: list[DomainHouseholdInterval] = []
        for starts_at, ends_at in zip(boundaries, boundaries[1:], strict=False):
            overlapping = tuple(
                item
                for item in source_intervals
                if item.starts_at < ends_at and item.ends_at > starts_at
            )
            covered_seconds = sum(
                (min(item.ends_at, ends_at) - max(item.starts_at, starts_at)).total_seconds()
                for item in overlapping
            )
            required_seconds = (ends_at - starts_at).total_seconds()
            if not overlapping or covered_seconds != required_seconds:
                raise DailyReferenceInputError("daily_reference_household_horizon_incomplete")
            expected_energy_wh = sum(
                item.expected_energy_wh
                * (min(item.ends_at, ends_at) - max(item.starts_at, starts_at)).total_seconds()
                / (item.ends_at - item.starts_at).total_seconds()
                for item in overlapping
            )
            normalised.append(
                DomainHouseholdInterval(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    expected_energy_wh=expected_energy_wh,
                    confidence=min(item.confidence for item in overlapping),
                )
            )
        return DomainHouseholdForecast(
            forecast_id=forecast.forecast_id,
            created_at=captured_at,
            horizon_start=captured_at,
            horizon_end=horizon_end,
            intervals=tuple(normalised),
            historical_source_reference=forecast.forecast_id,
            method_version=METHOD_VERSION,
        )

    def _pv_scenarios(
        self,
        timeline: PVEnergyTimeline,
        *,
        household: DomainHouseholdForecast,
        captured_at: datetime,
    ) -> tuple[ScenarioTimeline, ...]:
        return tuple(
            ScenarioTimeline(
                scenario=scenario,
                timeline=DomainPVTimeline(
                    timeline_id=f"{timeline.timeline_id}:{scenario.value}",
                    created_at=captured_at,
                    horizon_start=household.horizon_start,
                    horizon_end=household.horizon_end,
                    intervals=tuple(
                        self._normalise_pv_interval(
                            target.starts_at,
                            target.ends_at,
                            timeline.intervals,
                            scenario,
                        )
                        for target in household.intervals
                    ),
                ),
            )
            for scenario in PVScenario
        )

    @staticmethod
    def _normalise_pv_interval(
        starts_at: datetime,
        ends_at: datetime,
        source_intervals: tuple[PVEnergyTimelineInterval, ...],
        scenario: PVScenario,
    ) -> DomainPVInterval:
        overlapping = tuple(
            item
            for item in source_intervals
            if item.starts_at < ends_at and item.ends_at > starts_at
        )
        if not overlapping:
            raise DailyReferenceInputError("daily_reference_pv_gap")
        if any(item.forecast_range_status != "available" for item in overlapping):
            raise DailyReferenceInputError("daily_reference_pv_range_incomplete")
        covered_seconds = sum(
            (min(item.ends_at, ends_at) - max(item.starts_at, starts_at)).total_seconds()
            for item in overlapping
        )
        required_seconds = (ends_at - starts_at).total_seconds()
        if covered_seconds != required_seconds:
            raise DailyReferenceInputError("daily_reference_pv_coverage_incomplete")

        energy_wh = 0.0
        evidence_ids: list[str] = []
        confidence = 1.0
        for item in overlapping:
            values = {
                PVScenario.LOWER: item.forecast_lower_energy_wh,
                PVScenario.CENTRAL: item.forecast_central_energy_wh,
                PVScenario.UPPER: item.forecast_upper_energy_wh,
            }
            source_energy_wh = values[scenario]
            if source_energy_wh is None:
                raise DailyReferenceInputError("daily_reference_pv_range_incomplete")
            overlap_seconds = (
                min(item.ends_at, ends_at) - max(item.starts_at, starts_at)
            ).total_seconds()
            source_seconds = (item.ends_at - item.starts_at).total_seconds()
            energy_wh += source_energy_wh * overlap_seconds / source_seconds
            evidence_ids.extend((item.interval_id, *item.forecast_evidence_ids))
            confidence = min(confidence, item.confidence)
        return DomainPVInterval(
            starts_at=starts_at,
            ends_at=ends_at,
            energy_wh=energy_wh,
            evidence_type=PVEnergyEvidenceType.FORECAST,
            confidence=confidence,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            method_version=METHOD_VERSION,
        )
