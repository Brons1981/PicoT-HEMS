from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import TestCase

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_simulator import (
    IndependentDailySimulator,
    ScenarioTimeline,
)


START = datetime(2026, 8, 23, 11, 30, tzinfo=UTC)
INTERVAL = timedelta(minutes=30)


def _household() -> HouseholdLoadForecast:
    return HouseholdLoadForecast(
        forecast_id="household-incident",
        created_at=START,
        horizon_start=START,
        horizon_end=START + 9 * INTERVAL,
        intervals=tuple(
            HouseholdLoadForecastInterval(
                starts_at=START + index * INTERVAL,
                ends_at=START + (index + 1) * INTERVAL,
                expected_energy_wh=100.0,
                confidence=0.968,
            )
            for index in range(9)
        ),
        historical_source_reference="incident-history",
        method_version="test:v1",
    )


def _timeline(scenario: PVScenario) -> ScenarioTimeline:
    # The first three intervals contain 2,684 Wh after household demand.
    pv_energy = (1000.0, 1000.0, 984.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0)
    return ScenarioTimeline(
        scenario=scenario,
        timeline=PVEnergyTimeline(
            timeline_id=f"pv-{scenario.value}",
            created_at=START,
            horizon_start=START,
            horizon_end=START + 9 * INTERVAL,
            intervals=tuple(
                PVEnergyTimelineInterval(
                    starts_at=START + index * INTERVAL,
                    ends_at=START + (index + 1) * INTERVAL,
                    energy_wh=energy_wh,
                    evidence_type=PVEnergyEvidenceType.FORECAST,
                    confidence=0.422,
                    evidence_ids=(f"pv:{scenario.value}:{index}",),
                )
                for index, energy_wh in enumerate(pv_energy)
            ),
        ),
    )


def _storage(current_soc: float, state_id: str = "storage-state") -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id=state_id,
        execution_scope_id="battery",
        capability_id="battery-capability",
        current_soc=current_soc,
        usable_capacity_wh=8160.0,
        measured_at=START,
        confidence=1.0,
        evidence_ids=(state_id,),
    )


def _simulate(current_soc: float = 5746.0 / 8160.0):
    return IndependentDailySimulator().simulate(
        snapshot_id="snapshot-incident",
        household=_household(),
        pv_scenarios=tuple(_timeline(scenario) for scenario in PVScenario),
        storage_state=_storage(current_soc),
        conversion_model=StorageConversionModel(
            model_id="conversion",
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            evidence_ids=("conversion-evidence",),
            method_version="test:v1",
        ),
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )


class IndependentDailySimulatorTest(TestCase):
    def test_incident_surplus_reaches_target_before_thirteen_hundred(self) -> None:
        simulation = _simulate()

        self.assertTrue(simulation.observer_only)
        self.assertEqual(
            {item.scenario for item in simulation.trajectories}, set(PVScenario)
        )
        for trajectory in simulation.trajectories:
            self.assertIsNotNone(trajectory.target_reached_at)
            assert trajectory.target_reached_at is not None
            self.assertLess(
                trajectory.target_reached_at,
                datetime(2026, 8, 23, 13, 0, tzinfo=UTC),
            )
            self.assertAlmostEqual(
                trajectory.intervals[2].storage_energy_at_end_wh, 8160.0
            )
            self.assertEqual(
                sum(item.grid_to_storage_input_wh for item in trajectory.intervals), 0.0
            )

    def test_unexpected_manual_discharge_restarts_from_latest_physical_state(self) -> None:
        before = _simulate(current_soc=0.80)
        after = _simulate(current_soc=0.50)

        for trajectory in after.trajectories:
            self.assertAlmostEqual(
                trajectory.intervals[0].storage_energy_at_start_wh, 4080.0
            )
        self.assertAlmostEqual(
            before.trajectories[0].intervals[0].storage_energy_at_start_wh, 6528.0
        )

    def test_simulation_rejects_missing_uncertainty_scenario(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly lower, central and upper"):
            IndependentDailySimulator().simulate(
                snapshot_id="snapshot-incomplete",
                household=_household(),
                pv_scenarios=(_timeline(PVScenario.CENTRAL),),
                storage_state=_storage(0.5),
                conversion_model=StorageConversionModel(
                    model_id="conversion",
                    charge_efficiency=0.9,
                    discharge_efficiency=0.9,
                    evidence_ids=("conversion-evidence",),
                    method_version="test:v1",
                ),
                minimum_storage_energy_wh=816.0,
                target_storage_energy_wh=8160.0,
                maximum_charge_input_power_w=2400.0,
                maximum_discharge_output_power_w=2400.0,
            )
