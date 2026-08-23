"""Fail-closed adapter from shared v2 Planning Input to the daily simulator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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

METHOD_VERSION = "v2-independent-daily-reference-adapter:v1"


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
    ) -> DailyReferenceStrategyObservation:
        """Run the complete observer chain from one immutable Planning Input."""

        inputs = self._inputs(snapshot)
        if tariffs is None:
            tariffs = IndependentDailyTariffAdapter().build(snapshot)
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

    def _inputs(self, snapshot: PlanningInputSnapshot) -> _DailyReferenceInputs:
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
        if capability.maximum_power_w is None:
            raise DailyReferenceInputError("daily_reference_power_limit_missing")
        if capability.minimum_soc is None or capability.maximum_soc is None:
            raise DailyReferenceInputError("daily_reference_soc_limits_missing")
        directions = set(capability.flow_directions)
        if EnergyFlowDirection.BIDIRECTIONAL not in directions and not {
            EnergyFlowDirection.CHARGE,
            EnergyFlowDirection.DISCHARGE,
        }.issubset(directions):
            raise DailyReferenceInputError("daily_reference_directions_incomplete")

        household = self._household(
            snapshot.household_load_forecast,
            captured_at=snapshot.captured_at,
            horizon_end=snapshot.horizon_end,
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
                capability.minimum_soc * storage.usable_capacity_wh
            ),
            target_storage_energy_wh=(
                capability.maximum_soc * storage.usable_capacity_wh
            ),
            maximum_charge_input_power_w=capability.maximum_power_w,
            maximum_discharge_output_power_w=capability.maximum_power_w,
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
        intervals = forecast.intervals
        if not intervals:
            raise DailyReferenceInputError("daily_reference_household_empty")
        if intervals[0].starts_at != captured_at or intervals[-1].ends_at != horizon_end:
            raise DailyReferenceInputError("daily_reference_household_horizon_incomplete")
        if any(
            left.ends_at != right.starts_at
            for left, right in zip(intervals, intervals[1:], strict=False)
        ):
            raise DailyReferenceInputError("daily_reference_household_gap")
        return DomainHouseholdForecast(
            forecast_id=forecast.forecast_id,
            created_at=captured_at,
            horizon_start=captured_at,
            horizon_end=horizon_end,
            intervals=tuple(
                DomainHouseholdInterval(
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    expected_energy_wh=item.expected_energy_wh,
                    confidence=item.confidence,
                )
                for item in intervals
            ),
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
