"""Fail-closed adapter from shared v2 Planning Input to the daily simulator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    EnergyFlowDirection,
)
from picot.domain.current_storage_state import CurrentStorageState as DomainStorageState
from picot.domain.daily_reference_simulation import DailyReferenceSimulationSet, PVScenario
from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
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

METHOD_VERSION = "v2-independent-daily-reference-adapter:v2"
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
        strategy_space = IndependentDailyStrategyGenerator().generate_from_charge_windows(
            charge_windows=charge_windows,
            household=inputs.household,
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
            minimum_storage_energy_wh=(
                limits.minimum_soc * storage.usable_capacity_wh
            ),
            target_storage_energy_wh=(
                limits.maximum_soc * storage.usable_capacity_wh
            ),
            maximum_charge_input_power_w=(
                limits.maximum_charge_input_power_w
            ),
            maximum_discharge_output_power_w=(
                limits.maximum_discharge_output_power_w
            ),
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
            if interval.starts_at < horizon_end
            and interval.ends_at > captured_at
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
                (
                    min(item.ends_at, ends_at) - max(item.starts_at, starts_at)
                ).total_seconds()
                for item in overlapping
            )
            required_seconds = (ends_at - starts_at).total_seconds()
            if not overlapping or covered_seconds != required_seconds:
                raise DailyReferenceInputError(
                    "daily_reference_household_horizon_incomplete"
                )
            expected_energy_wh = sum(
                item.expected_energy_wh
                * (
                    min(item.ends_at, ends_at) - max(item.starts_at, starts_at)
                ).total_seconds()
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
