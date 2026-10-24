"""Real HC controller and measured models; HA messages and transport are fixtures."""

import copy
import hashlib
import json
from unittest.mock import patch

from picot_hc.energy_measurement import measurement
from picot_hc.energy_model import meter_context
from picot_hc.energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY
from picot_hc.energy_start import PERMIT_ENTITY
from test_downstairs_comfort import DownstairsComfortTests
from test_energy_proposals import inputs
from test_startup_energy import run


class EnergyStartTests(DownstairsComfortTests):
    def test_cv_recipe_starts_once_and_holds_into_comfort_after_permit_expiry(self):
        from pathlib import Path

        from picot_hc.cv_warmup import cv_sample
        from test_cv_auxiliary import config as auxiliary_config
        from test_cv_plans import setup as cv_setup

        self.prepare()
        self.runtime.start_intent.current = None
        self.config.update(auxiliary_config(), gas_price=1.4)
        for entity, state, unit in (
            (self.config["gas"], "100", "m³"),
            (self.config["cv_dhw_active"], "off", None),
        ):
            self.states[entity] = dict(
                state=state,
                last_reported=self.stamp(self.now),
                attributes=dict(unit_of_measurement=unit),
            )
        self.fresh()
        plan, view = self.heat.view(self.config, self.now), self.schedule.view(self.now)
        query = cv_sample(self.config, self.ctl, plan, self.now, target=20)
        self.assertIsNotNone(query)
        training_now, _, _, _, context, _ = cv_setup(Path(self.tmp.name))
        shift = self.now - training_now - 86400
        for model in (context["warmup"], context["maintenance"].evidence):
            for r in model.records:
                for key in (
                    "start",
                    "measured_at",
                    "stable_at",
                    "gas_start_reported_at",
                    "gas_end_reported_at",
                ):
                    r[key] += shift
                for key in ("checked_at", "review_until"):
                    r["gas_screening"][key] += shift
                r["identity"] = query["identity"]
                r["gas_screening"]["identity"] = query["gas_screening"]["identity"]
            model.save(model.records, [])
        context["sample"] = query
        self.runtime.cv_warmup = self.heat.energy_start.cv_warmup = context["warmup"]
        self.runtime.cv_maintenance = self.heat.energy_start.cv_maintenance = context["maintenance"]
        generator = self.runtime.energy_proposals
        self.runtime.start_intent.current = None
        generator.withdraw("new comparison")
        generator.fixed_start = None
        generator.standby.points = []
        for minute in range(16):
            elapsed = 960 - minute * 60
            generator.standby.observe(
                dict(self.sample, energy_wh=self.sample["energy_wh"] - elapsed * 10 / 3600),
                self.now - elapsed,
            )
        outlook = inputs(self.now)[2]
        outlook["snapshot_id"] = "joint-cv"
        outlook["replacement_basis"].update(
            source_id=self.sample["source_id"],
            modeled_source_id=context["modeled_source_id"],
            ends_at=view["next"]["ends_at"],
        )
        generator.tick(
            None,
            view,
            plan,
            outlook,
            self.now,
            startup=self.runtime.startup_energy,
            idle_sample=self.sample,
            cv_context=context,
        )
        self.assertIsNotNone(generator.pending)
        index = next(
            i for i, p in enumerate(generator.local["candidates"]) if p.get("source") == "cv"
        )
        self.choose(index)
        self.assertEqual(self.runtime.start_intent.current["source"], "cv")
        chosen = self.runtime.start_intent.current["heat_starts_at"]
        window = self.runtime.start_intent.current["window"]
        self.now = chosen - 60
        self.fresh()
        generator.withdraw("renew before execution")
        generator.fixed_start = chosen
        generator.standby.points = []
        for minute in range(16):
            elapsed = 960 - minute * 60
            generator.standby.observe(
                dict(self.sample, energy_wh=self.sample["energy_wh"] - elapsed * 10 / 3600),
                self.now - elapsed,
            )
        outlook.update(
            snapshot_id="joint-cv-renew", generated_at=self.now, valid_until=self.now + 180
        )
        generator.tick(
            None,
            self.schedule.view(self.now),
            self.heat.view(self.config, self.now),
            outlook,
            self.now,
            startup=self.runtime.startup_energy,
            idle_sample=self.sample,
            cv_context=context,
        )
        index = next(
            i for i, p in enumerate(generator.local["candidates"]) if p.get("source") == "cv"
        )
        self.choose(index)
        self.now = chosen
        for entity in (self.config["gas"], self.config["cv_dhw_active"]):
            self.states[entity]["last_reported"] = self.stamp(self.now)
        self.fresh()
        self.runtime.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]["entity_id"], self.config["cv"])
        self.assertEqual(self.calls[0][1]["hvac_mode"], "heat")
        self.assertIn("energy_start", self.heat.data["owned"]["cv"])
        self.now += 30
        self.fresh()
        self.runtime.collect()
        self.now = window["starts_at"] + 30
        self.temperature("beneden", 20)
        self.fresh()
        self.runtime.collect()
        final = self.heat.view(self.config, self.now)
        self.assertEqual(final["desired"].get("cv"), 20)
        self.assertFalse(any(body.get("hvac_mode") == "off" for _, body in self.calls))
        self.assertEqual(
            self.runtime.energy_execution_publisher.submit.call_args.args[0]["state"], "running"
        )

    def fresh(self):
        for zone in self.config["zones"]:
            self.states[zone["temperature"]]["last_reported"] = self.stamp(self.now)
        for entity, value, unit in (
            (self.config["outdoor"], 10, "°C"),
            ("sensor.kwh_meter_airco_vermogen", 10, "W"),
            ("sensor.kwh_meter_airco_energie_import", 100, "kWh"),
        ):
            self.states[entity] = dict(
                state=str(value),
                last_reported=self.stamp(self.now),
                attributes={"unit_of_measurement": unit},
            )
        self.ctl.observe(self.states, self.now, self.now)

    def choose(self, index=0):
        generator = self.runtime.energy_proposals
        request = copy.deepcopy(generator.pending)
        choice = request["plans"][index]["plan_id"]
        self.states[REQUEST_ENTITY] = dict(state="requested", attributes=request)
        digest = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.states[RESPONSE_ENTITY] = dict(
            state="selected",
            attributes=dict(
                contract="hc-energy-assessment:v1",
                status="selected",
                execution_authorized=False,
                request_id=request["request_id"],
                revision=request["revision"],
                basis_snapshot_id=request["basis_snapshot_id"],
                replacement_basis_id=request["replacement_basis_id"],
                request_fingerprint=digest,
                scope="replacement_demand_on_retained_route",
                valid_until=request["valid_until"],
                selected_plan_id=choice,
                assessments=[
                    dict(plan_id=p["plan_id"], status="feasible", total_incremental_cost_eur=0.1)
                    for p in request["plans"]
                ],
            ),
        )
        self.runtime.energy_selection.tick(self.states, generator, self.now, True)
        self.assertIsNotNone(self.runtime.energy_selection.current)
        self.runtime.start_intent.capture(
            self.runtime.energy_selection,
            generator,
            self.sample,
            self.schedule.view(self.now),
            self.heat.view(self.config, self.now),
            self.now,
        )
        message = self.runtime.energy_selection.current["message"]
        self.states[PERMIT_ENTITY] = dict(
            state="permitted",
            attributes=dict(
                message, contract="hc-energy-start-permit:v1", execution_authorized=True
            ),
        )

    def prepare(self, *, waiting=False):
        self.settings(
            enabled=True,
            learning_enabled=True,
            energy_start_enabled=True,
            door_close_seconds=0,
            initial_preheat_minutes=80 if waiting else 45,
            setback_temperature=17,
            windows=[dict(day=3, start="19:30", end="22:00", target=20, hard=True)],
        )
        self.temperature("beneden", 18)
        self.fresh()
        self.schedule.tick(self.config, self.now)
        plan = self.heat.view(self.config, self.now)
        self.assertTrue(plan["learning_context"]["valid"])
        self.sample = meter_context(
            self.config,
            self.states,
            plan,
            measurement(self.config, self.states, self.now),
            self.now,
            target=20,
        )
        self.assertIsNotNone(self.sample)
        base = dict(self.sample, indoor=20, energy_wh=10000)
        with patch("test_startup_energy.sample", return_value=base):
            for day in (3, 2, 1):
                run(self.runtime.startup_energy, self.now - day * 86400)
        self.assertEqual(len(self.runtime.startup_energy.model.records), 3)
        generator = self.runtime.energy_proposals
        for minute in range(63):
            generator.model.observe(
                dict(base, energy_wh=10000 + minute * 10, power_w=600),
                self.now - 3720 + minute * 60,
            )
        self.heat.learning.cooling.samples = [
            dict(
                end=self.now - day * 86400,
                indoor=18,
                outdoor=10,
                coefficient=0.008,
                identity=base["identity"],
            )
            for day in (3, 2, 1)
        ]
        self.addCleanup(patch.stopall)
        patch.object(generator.publisher, "submit").start()
        patch.object(self.runtime.energy_publisher, "submit").start()
        patch.object(self.runtime.weather, "collect", return_value={}).start()
        patch(
            "picot_hc.__main__.fetch_states", side_effect=lambda *args: copy.deepcopy(self.states)
        ).start()
        self.offer("initial")
        self.choose(1)
        chosen = self.runtime.start_intent.current["heat_starts_at"]
        self.assertEqual(chosen, self.now + 1020)
        if waiting:
            self.now += 540
            self.fresh()
            generator.fixed_start = chosen
            self.offer("before_normal_start")
            self.choose()
            self.now += 60
            self.fresh()
            return
        self.now = chosen - 60
        self.fresh()
        generator.fixed_start = self.runtime.start_intent.check(
            self.sample,
            self.schedule.view(self.now),
            self.heat.view(self.config, self.now),
            self.now,
        )
        self.offer("near_start")
        self.choose()
        self.assertEqual(self.runtime.start_intent.current["heat_starts_at"], chosen)
        self.now = chosen
        self.fresh()

    def offer(self, name):
        generator = self.runtime.energy_proposals
        generator.standby.points = []
        for minute in range(16):
            generator.standby.observe(
                dict(self.sample, energy_wh=10000 + minute / 6), self.now - 900 + minute * 60
            )
        outlook = inputs(self.now)[2]
        outlook.update(snapshot_id=name)
        outlook["replacement_basis"]["source_id"] = self.sample["source_id"]
        generator.delayed_tick(
            self.sample,
            self.schedule.view(self.now),
            self.heat.view(self.config, self.now),
            outlook,
            self.now,
            self.runtime.startup_energy,
        )
        self.assertIsNotNone(generator.pending)

    def test_normal_preheat_waits_for_selected_start_without_stopping_any_unit(self):
        self.prepare(waiting=True)
        with patch.object(self.heat, "energy_start", None):
            baseline = self.heat.view(self.config, self.now)
        self.assertTrue(baseline["preheating"])
        self.assertIn("beneden", baseline["desired"])
        self.runtime.collect()
        self.assertEqual(self.calls, [])
        plan = self.heat.view(self.config, self.now)
        self.assertEqual(plan["strategy"], "hems_waiting_start")
        self.assertEqual(self.runtime.start_intent.current["status"], "planned")
        self.assertEqual(
            self.runtime.energy_reservation_publisher.submit.call_args.args[0]["state"], "reserved"
        )
        chosen = self.runtime.start_intent.current["heat_starts_at"]
        while self.now < chosen:
            self.now += 30
            self.fresh()
            if self.now < chosen:
                self.runtime.energy_proposals.fixed_start = chosen
                self.offer("renew-" + str(self.now))
                self.choose()
            self.runtime.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]["hvac_mode"], "heat")
        self.assertIn("energy_start", self.heat.data["owned"]["beneden"])
        self.assertEqual(self.heat.learning.data["outcomes"], [])

    def test_waiting_falls_back_to_normal_heat_when_permission_expires(self):
        self.prepare(waiting=True)
        self.runtime.collect()
        self.assertEqual(self.calls, [])
        self.now += 61
        self.fresh()
        self.runtime.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]["hvac_mode"], "heat")
        self.assertNotIn("energy_start", self.heat.data["owned"]["beneden"])
        self.assertEqual(self.runtime.start_intent.current["status"], "cancelled")
        self.now += 30
        self.fresh()
        self.runtime.collect()
        self.assertFalse(any(body.get("hvac_mode") == "off" for _, body in self.calls))

    def test_waiting_cannot_suppress_floor_demand_or_missing_evidence(self):
        self.prepare(waiting=True)
        original = copy.deepcopy(self.states)
        for case in ("meter", "permission", "floor", "cold_outside", "manual"):
            with self.subTest(case=case):
                self.states = copy.deepcopy(original)
                if case == "meter":
                    self.states.pop("sensor.kwh_meter_airco_energie_import")
                elif case == "permission":
                    self.states.pop(PERMIT_ENTITY)
                elif case == "floor":
                    self.temperature("beneden", 16.5)
                elif case == "cold_outside":
                    self.states[self.config["outdoor"]]["state"] = "5"
                else:
                    self.states[self.ctl.bindings["beneden"]["entity_id"]]["state"] = "heat"
                self.ctl.observe(self.states, self.now, self.now)
                plan = self.heat.view(self.config, self.now)
                self.assertNotEqual(plan["strategy"], "hems_waiting_start")
                if case != "manual":
                    self.assertIn("beneden", plan["desired"])
                else:
                    self.assertNotIn("beneden", plan["desired"])
        self.assertEqual(self.calls, [])

    def test_waiting_preserves_upstairs_demand_even_when_cv_would_be_cheaper(self):
        self.prepare(waiting=True)
        self.config["gas_price"] = 0.01
        self.temperature("boven", 18)
        self.fresh()
        with patch.object(self.heat, "energy_start", None):
            self.assertIn("cv", self.heat.view(self.config, self.now)["desired"])
        self.runtime.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]["entity_id"], self.ctl.bindings["boven"]["entity_id"])
        self.assertEqual(self.heat.view(self.config, self.now)["strategy"], "hems_waiting_start")

    def test_waiting_requires_measured_duration_and_time_margin(self):
        self.prepare(waiting=True)
        current = self.runtime.start_intent.current
        estimate = self.runtime.startup_energy.model.estimate(self.sample, self.now)
        duration = current["window"]["starts_at"] - current["heat_starts_at"]
        current["recipe"]["startup_duration_seconds"] = duration
        for duration_value in (None, duration):
            with self.subTest(duration=duration_value):
                with patch.object(
                    self.runtime.startup_energy.model,
                    "estimate",
                    return_value=dict(estimate, duration_seconds=duration_value),
                ):
                    self.assertIn("beneden", self.heat.view(self.config, self.now)["desired"])

    def test_permitted_start_runs_once_and_keeps_heat_after_permit_expires(self):
        self.prepare()
        with patch.object(self.heat, "energy_start", None):
            self.assertNotIn("beneden", self.heat.view(self.config, self.now)["desired"])
        self.runtime.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]["hvac_mode"], "heat")
        self.assertEqual(self.calls[0][1]["temperature"], 20)
        self.assertIn("energy_start", self.heat.data["owned"]["beneden"])
        self.assertEqual(self.runtime.current()["start_intent"]["status"], "started")
        self.temperature("beneden", 20)
        for _ in range(12):
            self.now += 30
            self.fresh()
            self.runtime.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.heat.view(self.config, self.now)["desired"]["beneden"], 20)
        self.assertFalse(any(body.get("hvac_mode") == "off" for _, body in self.calls))
        self.assertEqual(self.heat.learning.data["outcomes"], [])

    def test_advice_without_start_permit_cannot_start(self):
        self.prepare()
        self.states.pop(PERMIT_ENTITY)
        self.fresh()
        self.runtime.collect()
        self.assertEqual(self.calls, [])

    def test_execution_is_opt_in_and_disabling_does_not_stop_running_airco(self):
        from picot_hc.schedule import validate_settings

        old = dict(self.schedule.data["settings"])
        old.pop("energy_start_enabled")
        self.assertFalse(validate_settings(old)["energy_start_enabled"])
        with self.assertRaises(ValueError):
            validate_settings(dict(old, energy_start_enabled=1))
        self.prepare()
        with patch.dict(self.schedule.data["settings"], energy_start_enabled=False):
            self.heat.tick(self.config, self.now)
            self.assertEqual(self.calls, [])
        self.runtime.collect()
        self.settings(energy_start_enabled=False)
        self.now += 30
        self.fresh()
        self.runtime.collect()
        self.assertNotIn("energy_start", self.heat.view(self.config, self.now))
        self.assertFalse(any(body.get("hvac_mode") == "off" for _, body in self.calls))

    def test_changed_permit_during_final_read_blocks_start(self):
        self.prepare()

        def changed(*args):
            value = copy.deepcopy(self.states)
            value[PERMIT_ENTITY]["state"] = "withdrawn"
            return value

        with patch("picot_hc.control.fetch_states", side_effect=changed):
            self.runtime.collect()
        self.assertEqual(self.calls, [])

    def test_minimum_off_time_still_blocks_economic_start(self):
        self.prepare()
        self.heat.data["changed"]["beneden"] = self.now - 30
        self.runtime.collect()
        self.assertEqual(self.calls, [])

    def test_missing_meter_blocks_start(self):
        self.prepare()
        self.states.pop("sensor.kwh_meter_airco_energie_import")
        self.ctl.observe(self.states, self.now, self.now)
        self.runtime.collect()
        self.assertEqual(self.calls, [])

    def test_expired_mismatched_and_rejected_permissions_cannot_start(self):
        self.prepare()
        original = copy.deepcopy(self.states)
        intent = copy.deepcopy(self.runtime.start_intent.current)
        for case in (
            "expired",
            "fingerprint",
            "rejected",
            "replaced",
            "revised_payload",
            "nonboolean",
        ):
            with self.subTest(case=case):
                self.states = copy.deepcopy(original)
                self.runtime.start_intent.current = copy.deepcopy(intent)
                permit = self.states[PERMIT_ENTITY]["attributes"]
                if case == "expired":
                    permit["valid_until"] = self.stamp(self.now)
                    self.runtime.start_intent.current["selection"]["valid_until"] = permit[
                        "valid_until"
                    ]
                elif case == "fingerprint":
                    permit["request_fingerprint"] = "different"
                elif case == "rejected":
                    self.states[RESPONSE_ENTITY]["state"] = "rejected"
                    self.states[RESPONSE_ENTITY]["attributes"]["status"] = "rejected"
                elif case == "replaced":
                    self.states[REQUEST_ENTITY]["attributes"]["request_id"] = "different"
                elif case == "nonboolean":
                    permit["execution_authorized"] = 1
                else:
                    request = self.states[REQUEST_ENTITY]["attributes"]
                    request["plans"][0]["slots"][0]["energy_wh"] += 1
                    self.states[RESPONSE_ENTITY]["attributes"]["request_fingerprint"] = (
                        hashlib.sha256(
                            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest()
                    )
                self.fresh()
                self.heat.tick(self.config, self.now)
                self.assertEqual(self.calls, [])

    def test_failed_persistence_prevents_start_and_retry(self):
        self.prepare()
        with patch.object(self.heat, "save", side_effect=[None, OSError("disk unavailable")]):
            self.runtime.collect()
        self.assertEqual(self.calls, [])
        self.assertNotIn("beneden", self.heat.data["owned"])
        self.now += 30
        self.fresh()
        self.runtime.collect()
        self.assertEqual(self.calls, [])

    def test_manual_takeover_and_schema_changes_keep_authority(self):
        self.prepare()
        self.runtime.collect()
        self.settings(setback_temperature=19)
        self.now += 30
        self.fresh()
        self.runtime.collect()
        self.assertEqual(self.heat.view(self.config, self.now)["desired"]["beneden"], 19)
        self.assertFalse(any(body.get("hvac_mode") == "off" for _, body in self.calls))
        entity = self.ctl.bindings["beneden"]["entity_id"]
        self.states[entity]["state"] = "off"
        self.now += 30
        self.fresh()
        count = len(self.calls)
        self.runtime.collect()
        self.assertEqual(len(self.calls), count)
        self.assertNotIn("beneden", self.heat.data["owned"])

    def test_upstairs_demand_remains_independent(self):
        self.prepare()
        self.temperature("boven", 18)
        self.fresh()
        self.runtime.collect()
        self.assertEqual(self.calls[0][1]["entity_id"], self.ctl.bindings["beneden"]["entity_id"])
        self.now += 30
        self.fresh()
        self.runtime.collect()
        self.assertEqual(self.calls[1][1]["entity_id"], self.ctl.bindings["boven"]["entity_id"])
        self.now += 30
        self.fresh()
        self.runtime.collect()
        self.states[self.config["price_entity"]]["attributes"]["raw_today"][0]["value"] = 0.9
        self.now += 360
        self.fresh()
        self.runtime.collect()
        desired = self.heat.view(self.config, self.now)["desired"]
        self.assertEqual(desired["beneden"], 20)
        self.assertEqual(desired["boven"], 20)
        self.assertNotIn("cv", desired)
        self.assertFalse(any(body.get("hvac_mode") == "off" for _, body in self.calls))

    def test_execution_receipt_requires_observed_confirmation_and_reports_finish(self):
        from picot_hc.energy_execution import execution_receipt

        self.prepare()

        def receipt():
            return execution_receipt(self.runtime.start_intent, self.ctl, self.config, self.now)

        self.runtime.collect()
        self.assertEqual(receipt()["state"], "unavailable")
        self.now += 30
        self.fresh()
        self.runtime.collect()
        running = receipt()
        self.assertEqual(running["state"], "running")
        self.assertEqual(
            set(running["attributes"]),
            {
                "contract",
                "status",
                "request_id",
                "request_fingerprint",
                "selected_plan_id",
                "executed_at",
                "reported_at",
            },
        )
        self.now += 180
        self.fresh()
        self.runtime.collect()
        self.assertEqual(receipt()["state"], "running")
        self.assertEqual(
            receipt()["attributes"]["executed_at"], running["attributes"]["executed_at"]
        )
        self.ctl.connected = False
        self.assertEqual(receipt()["state"], "unavailable")
        self.states[self.ctl.bindings["beneden"]["entity_id"]]["state"] = "off"
        self.now += 30
        self.fresh()
        self.runtime.collect()
        self.assertEqual(receipt()["state"], "finished")

    def test_reservation_requires_opt_in_and_fresh_valid_intent(self):
        from picot_hc.energy_execution import reservation_receipt

        self.prepare()
        self.now -= 30
        self.fresh()

        def receipt():
            return reservation_receipt(
                self.runtime.start_intent, self.ctl, self.heat, self.config, self.now
            )

        self.assertEqual(receipt()["state"], "reserved")
        self.runtime.collect()
        self.assertEqual(
            self.runtime.energy_reservation_publisher.submit.call_args.args[0]["state"], "reserved"
        )
        self.ctl.connected = False
        self.assertEqual(receipt()["state"], "unavailable")
        self.fresh()
        self.settings(energy_start_enabled=False)
        self.assertEqual(receipt()["state"], "cancelled")
        self.assertEqual(self.calls, [])

    def test_restart_does_not_resume_economic_execution(self):
        from picot_hc.__main__ import Runtime

        self.prepare()
        self.runtime.collect()
        restored = Runtime(self.config, self.store, "http://fake/api", "test")
        self.assertEqual(restored.start_intent.view(self.now)["status"], "cancelled")
        self.assertFalse(restored.heating.view(self.config, self.now)["enabled"])
        count = len(self.calls)
        restored.heating.tick(self.config, self.now)
        self.assertEqual(len(self.calls), count)


for _name in dir(DownstairsComfortTests):
    if _name.startswith("test_") and _name not in EnergyStartTests.__dict__:
        setattr(EnergyStartTests, _name, None)
