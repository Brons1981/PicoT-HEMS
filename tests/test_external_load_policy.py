import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import DailyPlanningProjection, PVScenario
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
from picot.planner.independent_daily_intent_simulator import IndependentDailyIntentSimulator
from picot.planner.independent_daily_simulator import ScenarioTimeline
from picot.v2.daily_bridge import energy_deficits
from picot.v2.external_load_policy import read_external_load_policy
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.planning_input import HouseholdLoadObservation

AT = datetime(2026, 10, 8, 12, tzinfo=UTC)
END = AT + timedelta(hours=1)


class ExternalLoadTests(unittest.TestCase):
    def simulate(self, pv_w, excluded=2000, soc=0.5):
        household = HouseholdLoadForecast(
            "house",
            AT,
            AT,
            END,
            (HouseholdLoadForecastInterval(AT, END, 2200, 1, excluded),),
            "history",
            "test",
        )
        scenarios = tuple(
            ScenarioTimeline(
                s,
                PVEnergyTimeline(
                    f"pv-{s}",
                    AT,
                    AT,
                    END,
                    (
                        PVEnergyTimelineInterval(
                            AT, END, pv_w, PVEnergyEvidenceType.FORECAST, 1, ("pv",)
                        ),
                    ),
                ),
            )
            for s in PVScenario
        )
        schedule = DailyReferenceIntentSchedule(
            "schedule",
            "snapshot",
            AT,
            END,
            (DailyReferenceIntentInterval(AT, END, DailyStorageIntent.NOM),),
            "test",
        )
        output = IndependentDailyIntentSimulator().simulate(
            snapshot_id="snapshot",
            household=household,
            pv_scenarios=scenarios,
            storage_state=CurrentStorageState(
                "storage", "home", "battery", soc, 8160, AT, 1, ("storage",)
            ),
            conversion_model=StorageConversionModel("conversion", 1, 1, ("conversion",), "test"),
            intent_schedule=schedule,
            minimum_storage_energy_wh=816,
            target_storage_energy_wh=8160,
            maximum_charge_input_power_w=2400,
            maximum_discharge_output_power_w=2400,
        )
        return output.trajectories[0].intervals[0], schedule

    def test_pv_surplus_only_charges800(self):
        interval, _ = self.simulate(3000)
        self.assertEqual(interval.pv_to_storage_input_wh, 800)
        self.assertEqual(interval.grid_to_storage_input_wh, 0)
        self.assertEqual(interval.household_demand_wh, 2200)

    def test_partial_pv_leaves_grid_import_without_storage_discharge(self):
        interval, _ = self.simulate(1000)
        self.assertEqual(interval.grid_to_household_wh, 1200)
        self.assertEqual(interval.storage_to_household_output_wh, 0)

    def test_night_discharge_only_house_and_preserves_ev_cost(self):
        interval, _ = self.simulate(0)
        self.assertEqual(interval.grid_to_household_wh, 2000)
        self.assertEqual(interval.storage_to_household_output_wh, 200)
        self.assertEqual(interval.storage_energy_at_end_wh, 3880)

    def test_ev_import_is_not_a_bridge_shortfall(self):
        interval, schedule = self.simulate(0)
        projection = DailyPlanningProjection(
            "snapshot",
            "schedule",
            PVEnergyTimeline(
                "pv",
                AT,
                AT,
                END,
                (PVEnergyTimelineInterval(AT, END, 0, PVEnergyEvidenceType.FORECAST, 1, ("pv",)),),
            ),
            (interval,),
            "test",
        )
        self.assertEqual(
            energy_deficits(projection, schedule, until=END, maximum_discharge_output_power_w=2400)[
                0
            ].deficit_wh,
            0,
        )

    def test_no_policy_preserves_ordinary_nom(self):
        interval, _ = self.simulate(0, excluded=0)
        self.assertEqual(interval.storage_to_household_output_wh, 2200)
        self.assertEqual(interval.grid_to_household_wh, 0)

    def test_reader_rejects_shadow_stale_and_missing_provenance(self):
        payload = {
            "contract": "measured-external-load-support-policy:v1",
            "control_enabled": True,
            "status": "ready",
            "measured_at": AT.isoformat(),
            "ev_w": 2000,
            "source_id": "energy-devices:ev",
            "revision": "1",
        }
        self.assertIsNotNone(
            read_external_load_policy(payload, captured_at=AT, execution_scope_id="home")
        )
        for update in [
            {"control_enabled": False},
            {"status": "blocked"},
            {"measured_at": (AT - timedelta(seconds=4)).isoformat()},
            {"ev_w": float("nan")},
        ]:
            self.assertIsNone(
                read_external_load_policy(
                    dict(payload, **update), captured_at=AT, execution_scope_id="home"
                )
            )

    def test_financial_segment_scales_excluded_energy(self):
        from picot.planner.independent_daily_financial_settlement import (
            IndependentDailyFinancialSettlement,
        )

        interval, _ = self.simulate(0)
        half = IndependentDailyFinancialSettlement._physical_segment(
            interval,
            starts_at=AT,
            ends_at=AT + timedelta(minutes=30),
        )
        self.assertEqual(half.household_demand_wh, 1100)
        self.assertEqual(half.battery_excluded_demand_wh, 1000)
        self.assertEqual(half.grid_to_household_wh, 1000)

    def test_current_ev_is_added_once_bounded_and_stop_removes_contribution(self):
        from picot.domain.external_load_policy import ExternalLoadPolicy
        from picot.v2.contracts import (
            HouseholdLoadForecast as VForecast,
        )
        from picot.v2.contracts import (
            HouseholdLoadForecastInterval as VInterval,
        )
        from picot.v2.external_load_policy import apply_external_load_policy

        base = VForecast(
            "forecast",
            "run",
            "snapshot",
            (VInterval("interval", AT, END, 200, 1, "history", "test"),),
            False,
            None,
        )
        policy = ExternalLoadPolicy("energy-devices:ev", "1", AT, 2000, False, "home")
        first = apply_external_load_policy(base, policy, captured_at=AT)
        self.assertEqual(sum(i.expected_energy_wh for i in first.intervals), 700)
        self.assertEqual(sum(i.battery_excluded_energy_wh for i in first.intervals), 500)
        self.assertEqual(first, apply_external_load_policy(base, policy, captured_at=AT))
        self.assertEqual(
            apply_external_load_policy(
                base, replace(policy, power_w=0, revision="2"), captured_at=AT
            ),
            base,
        )

    def test_history_preserves_physical_demand_and_separate_ev_measurement(self):
        with tempfile.TemporaryDirectory() as folder:
            store = HouseholdLoadHistoryStore(Path(folder) / "history.jsonl")
            observation = HouseholdLoadObservation(2200, AT, ("raw", "ev"), "test", 2000)
            store.append(observation)
            self.assertEqual(store.load(), (observation,))
            self.assertEqual(store.load()[0].power_w, 2200)


if __name__ == "__main__":
    unittest.main()


def test_real_ingestion_preserves_raw_and_adds_ev_once(tmp_path, monkeypatch):
    import json

    from picot.v2 import planning_input as module

    options = tmp_path / "options.json"
    options.write_text(json.dumps({"energy_device_policy_enabled": True}))
    values = {
        "grid_power": 2200,
        "pv_power": 0,
        "storage_power_signed": 0,
        "storage_power_to_house": 0,
        "storage_power_from_house": 0,
    }
    payload = {
        "contract": "measured-external-load-support-policy:v1",
        "control_enabled": True,
        "status": "ready",
        "measured_at": AT.isoformat(),
        "ev_w": 2000,
        "source_id": "energy-devices:ev",
        "revision": "1",
    }

    def read(_self, binding):
        return module.SourceEvidence(
            evidence_id=binding.semantic_role,
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state=str(values.get(binding.semantic_role, "enabled")),
            raw_unit="W",
            observed_at=AT,
            availability="available",
            mapping_version="test",
            external_load_payload=payload
            if binding.semantic_role == "external_load_policy"
            else None,
        )

    monkeypatch.setattr(module.HomeAssistantStateReader, "read", read)
    bindings = tuple(
        module.SourceBinding("test", role, "sensor." + role)
        for role in (*values, "external_load_policy")
    )

    def assemble():
        return module.assemble_planning_input(
            "test-token",
            bindings=bindings,
            options_path=str(options),
            captured_at=AT,
            storage_state_config=module.StorageStateConfig("home", "battery", 8160),
            household_load_fallback_power_w=200,
        )

    enabled = assemble()
    assert enabled.household_load_observation.power_w == 2200
    assert enabled.household_load_observation.identified_external_power_w == 2000
    assert next(f for f in enabled.facts if f.semantic_role == "grid_power").value == 2200
    intervals = enabled.snapshot.household_load_forecast.intervals
    first = next(i for i in intervals if i.starts_at == AT)
    assert first.expected_energy_wh == 550
    assert first.battery_excluded_energy_wh == 500
    options.write_text(json.dumps({"energy_device_policy_enabled": False}))
    disabled = assemble()
    assert disabled.snapshot.external_load_policy is None
    assert disabled.household_load_observation.power_w == 2200
    assert disabled.household_load_observation.identified_external_power_w == 0
    assert all(
        i.battery_excluded_energy_wh == 0
        for i in disabled.snapshot.household_load_forecast.intervals
    )


def test_known_ev_history_stays_separate_after_policy_is_disabled(tmp_path, monkeypatch):
    import json

    from picot.v2 import planning_input as module

    options = tmp_path / "options.json"
    options.write_text(json.dumps({"energy_device_policy_enabled": False}))
    values = {"grid_power": 200, "pv_power": 0, "storage_power_signed": 0,
              "storage_power_to_house": 0, "storage_power_from_house": 0}

    def read(_self, binding):
        return module.SourceEvidence(
            evidence_id=binding.semantic_role, category=binding.category,
            semantic_role=binding.semantic_role, entity_id=binding.entity_id,
            raw_state=str(values.get(binding.semantic_role, "enabled")),
            raw_unit="W", observed_at=AT,
            availability="available", mapping_version="test",
            external_load_payload={
                "contract": "measured-external-load-support-policy:v1",
                "control_enabled": True, "status": "ready", "measured_at": AT.isoformat(),
                "ev_w": 2000, "source_id": "energy-devices:ev", "revision": "1",
            } if binding.semantic_role == "external_load_policy" else None,
        )

    monkeypatch.setattr(module.HomeAssistantStateReader, "read", read)
    # Physically measured 2200 W: 2000 W identified EV + 200 W house. No
    # retrospective guess for old unlabelled samples, no direct EV sensor read.
    history = tuple(HouseholdLoadObservation(
        2200, AT - timedelta(days=day) + timedelta(minutes=minute),
        ("raw", "energy-device-snapshot"), "test", 2000, True,
    ) for day in range(1, 8) for minute in range(0, 1440, 5))
    result = module.assemble_planning_input(
        "test-token", bindings=tuple(module.SourceBinding("test", role, "sensor." + role)
                                    for role in values),
        options_path=str(options), captured_at=AT,
        storage_state_config=module.StorageStateConfig("home", "battery", 8160),
        household_load_observations=history,
    )
    forecast = result.snapshot.household_load_forecast
    assert forecast is not None
    assert forecast.intervals[0].expected_energy_wh == 50  # 200 W for fifteen minutes.
    assert result.household_load_observation.power_w == 200
    assert result.snapshot.external_load_policy is None
    assert all(i.battery_excluded_energy_wh == 0 for i in forecast.intervals)
    assert all(i.power_w == 2200 for i in history)  # physical source remains unchanged.

    # The same snapshot path removes the measured EV but keeps an oven's
    # 1000 W excess in the measured household guard and the physical forecast.
    options.write_text(json.dumps({"energy_device_policy_enabled": True}))
    values["grid_power"] = 3200
    oven_history = history + tuple(HouseholdLoadObservation(
        3200, AT - timedelta(minutes=minute), ("raw", "ev"), "test", 2000, True,
    ) for minute in range(1, 8))
    result = module.assemble_planning_input(
        "test-token", bindings=tuple(module.SourceBinding("test", role, "sensor." + role)
                                    for role in (*values, "external_load_policy")),
        options_path=str(options), captured_at=AT,
        storage_state_config=module.StorageStateConfig("home", "battery", 8160),
        household_load_observations=oven_history,
    )
    assert result.household_load_observation.power_w == 3200
    assert result.household_load_observation.identified_external_power_w == 2000
    assert result.snapshot.household_load_guard.extra_power_w == 1000
    first = result.snapshot.household_load_forecast.intervals[0]
    assert first.expected_energy_wh == 800  # house 200 + oven 1000 + EV 2000.
    assert first.battery_excluded_energy_wh == 500  # only the EV.
