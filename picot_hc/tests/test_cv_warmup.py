from datetime import UTC

import pytest
import test_downstairs_comfort as comfort
from picot_hc.core import Store
from picot_hc.cv_warmup import CvWarmupEvidence

NOW = 1792692000.0


def run(model, fault=None, electricity=None, gas_screening=None, auxiliary=None):
    view = dict(
        revision=1,
        settings=dict(enabled=True, learning_enabled=True),
        next=dict(starts_at=NOW + 3600, target=20),
    )
    plan = dict(
        enabled=True,
        preheating=True,
        desired=dict(cv=20),
        owned={},
        sources=dict(cv=dict(state="off", temperature=20)),
    )
    first = dict(indoor=18, outdoor=10, target=20, gas_m3=100, gas_reported_at=NOW, identity="same")
    if auxiliary:
        first["auxiliary_assumptions"] = auxiliary(0)
    if gas_screening:
        first["gas_screening"] = gas_screening(0)
    if electricity:
        first["electricity"] = electricity(0)
    model.prepare(first, view, plan, ("cv", "heating", 20), NOW)
    command = dict(
        id="cv-start",
        source="cv",
        field="heating",
        origin="schedule",
        before=dict(mode="off"),
        value=20,
        created=NOW,
        sent=NOW,
        status="awaiting_feedback",
    )
    plan["owned"]["cv"] = dict(command=command["id"])
    for minute in range(26):
        now = NOW + minute * 60
        if minute:
            command["status"] = "confirmed"
            plan["sources"]["cv"]["state"] = "heat"
        point = dict(
            first,
            indoor=min(20, 18 + minute / 10),
            gas_m3=100 + (minute // 5) * 0.1,
            gas_reported_at=NOW + (minute // 5) * 300,
        )
        if auxiliary:
            point["auxiliary_assumptions"] = auxiliary(minute)
        if gas_screening:
            point["gas_screening"] = gas_screening(minute)
        if electricity:
            point["electricity"] = electricity(minute)
        if minute == 5:
            if fault == "counter_reset":
                point["gas_m3"] = 99
            elif fault == "schema":
                view["revision"] += 1
            elif fault == "manual":
                command["origin"] = "manual"
            elif fault == "missing":
                point = None
            elif fault == "identity":
                point["identity"] = "other"
            elif fault == "temperature":
                point["indoor"] = 16
            elif fault == "gap":
                now += 600
            elif fault == "restart":
                model = CvWarmupEvidence(model.store)
        model.observe(point, view, plan, [command], now)
    return model


def test_cv_trajectory_records_gas_separately_without_claiming_comparable_energy(tmp_path):
    model = run(CvWarmupEvidence(Store(tmp_path / "hc.sqlite")))
    view = model.view(NOW + 1500)
    assert view["completed_sessions"] == 1
    assert view["comparison_eligible"] is False
    assert view["execution_authorized"] is False
    record = view["latest"]
    assert record["duration_seconds"] == 1200
    assert record["household_gas_delta_m3"] == pytest.approx(0.5)
    assert record["gas_end_reported_at"] >= record["stable_at"]
    assert record["electricity_measured"] is False
    assert record["gas_attribution"] == "household_total_may_include_other_use"
    assert "energy_wh" not in record
    assert CvWarmupEvidence(model.store).view(NOW + 1500)["latest"] == record
    run(model)
    assert len(model.records) == 1


@pytest.mark.parametrize(
    "fault",
    ["counter_reset", "schema", "manual", "missing", "identity", "temperature", "gap", "restart"],
)
def test_incomplete_or_contaminated_attempt_is_not_resumed(tmp_path, fault):
    model = run(CvWarmupEvidence(Store(tmp_path / "hc.sqlite")), fault)
    assert model.view(NOW + 1500)["completed_sessions"] == 0


def test_preparation_requires_cv_off_to_heat_and_learning_opt_in(tmp_path):
    model = CvWarmupEvidence(Store(tmp_path / "hc.sqlite"))
    view = dict(
        revision=1,
        settings=dict(enabled=True, learning_enabled=False),
        next=dict(starts_at=NOW + 3600, target=20),
    )
    plan = dict(enabled=True, preheating=True, sources=dict(cv=dict(state="off", temperature=20)))
    point = dict(indoor=18, outdoor=10, target=20, gas_m3=100, gas_reported_at=NOW, identity="same")
    model.prepare(point, view, plan, ("cv", "heating", 20), NOW)
    assert model.baseline is None
    view["settings"]["learning_enabled"] = True
    model.prepare(point, view, plan, ("beneden", "heating", 20), NOW)
    assert model.baseline is None


@pytest.mark.parametrize("fault", [None, "stale", "unit", "future", "missing", "airco"])
def test_cv_sample_uses_only_gas_and_downstairs_thermal_context(fault):
    from datetime import datetime
    from types import SimpleNamespace

    from picot_hc.cv_warmup import cv_sample

    config = dict(
        stale_seconds=120,
        gas="sensor.gas",
        cv="climate.cv",
        outdoor="sensor.out",
        zones=[dict(id="beneden", temperature="sensor.down")],
    )

    def stamp(t):
        return datetime.fromtimestamp(t, UTC).isoformat()

    states = {
        "sensor.gas": dict(
            state="100", last_reported=stamp(NOW), attributes={"unit_of_measurement": "m³"}
        )
    }
    control = SimpleNamespace(connected=True, received=NOW, states=states)
    plan = dict(
        learning_context=dict(valid=True, indoor=18, outdoor=10),
        desired=dict(cv=20),
        sources=dict(
            cv=dict(available=True, temperature=20),
            beneden=dict(available=True, state="off", pending=False),
        ),
    )
    if fault == "stale":
        states["sensor.gas"]["last_reported"] = stamp(NOW - 601)
    elif fault == "unit":
        states["sensor.gas"]["attributes"]["unit_of_measurement"] = "kWh"
    elif fault == "future":
        states["sensor.gas"]["last_reported"] = stamp(NOW + 1)
    elif fault == "missing":
        states.clear()
    elif fault == "airco":
        plan["sources"]["beneden"]["state"] = "heat"
    value = cv_sample(config, control, plan, NOW)
    if fault:
        assert value is None
    else:
        assert value["gas_m3"] == 100
        assert value["indoor"] == 18
        assert "energy_wh" not in value


class CvRuntimeTests(comfort.DownstairsComfortTests):
    def test_normal_cv_start_collects_passively_and_meter_failure_does_not_stop_heat(self):
        import copy
        from unittest.mock import patch

        self.settings(
            enabled=True,
            learning_enabled=True,
            initial_preheat_minutes=60,
            door_close_seconds=0,
            setback_temperature=17,
            windows=[dict(day=3, start="19:00", end="22:00", target=20, hard=True)],
        )
        self.config["gas_price"] = 0.01
        self.runtime.config.update(
            cv_power="sensor.cv_w", cv_energy="sensor.cv_kwh", cv_meter_scope_confirmed=True
        )
        patch.object(self.runtime.weather, "collect", return_value={}).start()
        patch.object(self.runtime.energy_publisher, "submit").start()
        patch.object(self.runtime.energy_proposals.publisher, "submit").start()
        patch(
            "picot_hc.__main__.fetch_states", side_effect=lambda *args: copy.deepcopy(self.states)
        ).start()
        self.runtime.config["cv_dhw_active"] = "binary_sensor.dhw"
        start = self.now
        for minute in range(26):
            self.now = start + minute * 60
            self.temperature("beneden", min(20, 18 + minute / 10))
            for zone in self.config["zones"]:
                self.states[zone["temperature"]]["last_reported"] = self.stamp(self.now)
            self.states[self.config["outdoor"]] = dict(
                state="10",
                last_reported=self.stamp(self.now),
                attributes={"unit_of_measurement": "°C"},
            )
            self.states[self.config["gas"]] = dict(
                state=str(100 + (minute // 5) * 0.1),
                last_reported=self.stamp(start + (minute // 5) * 300),
                attributes={"unit_of_measurement": "m³"},
            )
            for entity, value, unit in (
                ("sensor.cv_w", 100, "W"),
                ("sensor.cv_kwh", 10 + minute / 600, "kWh"),
            ):
                self.states[entity] = dict(
                    state=str(value),
                    last_reported=self.stamp(self.now),
                    attributes=dict(unit_of_measurement=unit),
                )
            self.states["binary_sensor.dhw"] = dict(
                state="on" if minute == 5 else "off", last_reported=self.stamp(self.now)
            )
            self.runtime.collect()
        result = self.runtime.current()["cv_warmup"]
        self.assertEqual(result["completed_sessions"], 1)
        self.assertFalse(result["comparison_eligible"])
        self.assertEqual(result["latest"]["gas_screening"]["status"], "dhw_observed")
        self.assertTrue(result["latest"]["electricity_measured"])
        self.assertAlmostEqual(result["latest"]["electricity"]["energy_wh"], 100 * 25 / 60)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]["entity_id"], self.config["cv"])
        self.assertEqual(len(self.runtime.startup_energy.model.records), 0)
        with patch.object(
            self.runtime.cv_warmup, "observe", side_effect=OSError("storage unavailable")
        ):
            self.runtime.collect()
        self.assertEqual(self.runtime.connection, "connected")
        self.assertEqual(len(self.calls), 1)


for _name in dir(comfort.DownstairsComfortTests):
    if _name.startswith("test_") and _name not in CvRuntimeTests.__dict__:
        setattr(CvRuntimeTests, _name, None)


@pytest.mark.parametrize("fault", [None, "missing", "reset", "identity", "timestamp"])
def test_optional_electricity_requires_unbroken_trace(tmp_path, fault):
    def electricity(minute):
        point = dict(
            status="available",
            identity="cv-only",
            energy_kwh=10 + minute / 600,
            power_w=100,
            reported_at=NOW + minute * 60,
        )
        if minute == 5:
            if fault == "missing":
                return dict(status="unavailable")
            if fault == "reset":
                point["energy_kwh"] = 0
            if fault == "identity":
                point["identity"] = "other"
            if fault == "timestamp":
                point["reported_at"] = NOW
        return point

    model = run(CvWarmupEvidence(Store(tmp_path / "hc.sqlite")), electricity=electricity)
    record = model.view(NOW + 1500)["latest"]
    assert record["electricity_measured"] is (fault is None)
    assert record["comparison_eligible"] is False
    if fault is None:
        assert record["electricity"]["energy_wh"] == pytest.approx(100 * 25 / 60)
        assert record["electricity"]["end_reported_at"] == NOW + 1500
    else:
        assert "energy_wh" not in record["electricity"]
    assert CvWarmupEvidence(model.store).view(NOW + 1500)["latest"] == record


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "absent",
        "unconfirmed",
        "shared",
        "unit",
        "stale",
        "future",
        "nan",
        "negative",
        "missing",
        "zero",
    ],
)
def test_dedicated_cv_meter_validation(fault):
    from datetime import datetime

    from picot_hc.cv_electricity import cv_electricity

    config = dict(
        cv_power="sensor.cv_w",
        cv_energy="sensor.cv_kwh",
        cv_meter_scope_confirmed=True,
        zones=[dict(power="sensor.ac_w", energy="sensor.ac_kwh")],
    )
    states = {
        entity: dict(
            state=value,
            last_reported=datetime.fromtimestamp(NOW, UTC).isoformat(),
            attributes=dict(unit_of_measurement=unit),
        )
        for entity, value, unit in [("sensor.cv_w", "100", "W"), ("sensor.cv_kwh", "10", "kWh")]
    }
    if fault == "absent":
        config.pop("cv_power")
        config.pop("cv_energy")
    elif fault == "unconfirmed":
        config["cv_meter_scope_confirmed"] = False
    elif fault == "shared":
        config["cv_energy"] = "sensor.ac_kwh"
    elif fault == "unit":
        states["sensor.cv_kwh"]["attributes"]["unit_of_measurement"] = "Wh"
    elif fault in ("stale", "future"):
        states["sensor.cv_kwh"]["last_reported"] = datetime.fromtimestamp(
            NOW + (1 if fault == "future" else -61), UTC
        ).isoformat()
    elif fault in ("nan", "negative"):
        states["sensor.cv_kwh"]["state"] = "nan" if fault == "nan" else "-1"
    elif fault == "missing":
        states.clear()
    elif fault == "zero":
        for value in states.values():
            value["state"] = "0"
    value = cv_electricity(config, states, NOW)
    assert (value["status"] == "available") is (fault in (None, "zero"))
    if fault == "zero":
        assert value["energy_kwh"] == value["power_w"] == 0
    if fault not in (None, "zero"):
        assert "energy_kwh" not in value


@pytest.mark.parametrize(
    "fault, expected",
    [
        (None, "no_dhw_observed"),
        ("active", "dhw_observed"),
        ("missing", "incomplete"),
        ("changed", "incomplete"),
    ],
)
def test_warmwater_screening_retains_entire_session_evidence(tmp_path, fault, expected):
    def screening(minute):
        point = dict(status="available", active=False, identity="sensor.dhw")
        if minute == 5:
            if fault == "active":
                point["active"] = True
            elif fault == "missing":
                point = dict(status="unavailable")
            elif fault == "changed":
                point["identity"] = "sensor.other"
        return point

    model = run(CvWarmupEvidence(Store(tmp_path / "hc.sqlite")), gas_screening=screening)
    record = model.view(NOW + 1500)["latest"]
    assert record["gas_screening"]["status"] == expected
    assert record["comparison_eligible"] is False
    assert record["household_gas_delta_m3"] == pytest.approx(0.5)
    assert "heating_gas_m3" not in record
    assert CvWarmupEvidence(model.store).view(NOW + 1500)["latest"] == record


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "active",
        "absent",
        "general",
        "missing",
        "stale",
        "future",
        "naive",
        "invalid",
        "error",
    ],
)
def test_dhw_reader_only_accepts_fresh_explicit_binary_state(fault):
    from datetime import datetime

    from picot_hc.cv_gas_screening import gas_screening

    config = dict(cv_dhw_active="binary_sensor.dhw", cv_status="binary_sensor.heat")
    point = dict(
        state="off", last_reported=datetime.fromtimestamp(NOW, UTC).isoformat(), attributes={}
    )
    states = {"binary_sensor.dhw": point}
    if fault == "active":
        point["state"] = "on"
    elif fault == "absent":
        config.pop("cv_dhw_active")
    elif fault == "general":
        config["cv_dhw_active"] = config["cv_status"]
    elif fault == "missing":
        states.clear()
    elif fault in ("stale", "future"):
        point["last_reported"] = datetime.fromtimestamp(
            NOW + (1 if fault == "future" else -61), UTC
        ).isoformat()
    elif fault == "naive":
        point["last_reported"] = "2026-10-22T18:00:00"
    elif fault == "invalid":
        point["state"] = "unknown"
    elif fault == "error":
        point["hc_report_error"] = "failed"
    result = gas_screening(config, states, NOW)
    assert (result["status"] == "available") is (fault in (None, "active"))
    if fault in (None, "active"):
        assert result["active"] is (fault == "active")
    else:
        assert "active" not in result


@pytest.mark.parametrize("fault", [None, "late_on", "missing", "restart", "gap", "changed"])
def test_delayed_dhw_review_after_heating_ends(tmp_path, fault):
    def screening(_minute):
        return dict(status="available", active=False, identity="sensor.dhw")

    model = run(CvWarmupEvidence(Store(tmp_path / "hc.sqlite")), gas_screening=screening)
    end = NOW + 1500
    original = model.view(end)["latest"]
    assert original["gas_screening"]["provisional"] is True
    assert model.view(end)["pending_gas_reviews"] == 1
    if fault == "restart":
        model = CvWarmupEvidence(model.store)
    for offset in (30, 60, 90):
        if fault == "gap" and offset < 90:
            continue
        point = screening(0)
        if offset == 60:
            if fault == "late_on":
                point["active"] = True
            elif fault == "missing":
                point = {}
            elif fault == "changed":
                point["identity"] = "other"
        model.screen(point, end + offset)
    record = model.view(end + 90)["latest"]
    assert record["gas_screening"]["provisional"] is False
    expected = (
        "dhw_observed"
        if fault == "late_on"
        else "no_dhw_observed"
        if fault is None
        else "incomplete"
    )
    assert record["gas_screening"]["status"] == expected
    assert record["measured_at"] == original["measured_at"]
    assert record["household_gas_delta_m3"] == original["household_gas_delta_m3"]
    assert record["electricity"] == original["electricity"]
    assert record["comparison_eligible"] is False
    assert CvWarmupEvidence(model.store).view(end + 90)["latest"] == record


@pytest.mark.parametrize("missing", [False, True])
def test_dhw_diagnostic_export_preserves_raw_values_and_times(tmp_path, missing):
    import json
    from pathlib import Path

    from picot_hc.core import snapshot

    config = json.loads(
        (Path(__file__).resolve().parents[1] / "options.example.json").read_text(encoding="utf-8")
    )
    config.update(cv_dhw_active="binary_sensor.dhw_status", cv_dhw_diagnostic="sensor.dhw_status")
    states = (
        {}
        if missing
        else {
            "binary_sensor.dhw_status": dict(
                state="on",
                last_changed="2026-10-23T19:00:00+00:00",
                last_updated="2026-10-23T19:00:30+00:00",
                last_reported="2026-10-23T19:00:45+00:00",
                attributes=dict(private_token="never-export"),
            ),
            "sensor.dhw_status": dict(state="tapwater", last_changed="2026-10-23T19:00:01+00:00"),
        }
    )
    data = snapshot(config, states, NOW)
    store = Store(tmp_path / "hc.sqlite")
    store.save(data, 90)
    exported = list(Store(store.path).building_records(NOW))[0]
    observed = exported["dhw_observations"]
    assert "never-export" not in json.dumps(exported)
    if missing:
        assert observed["active"]["quality"] == "missing"
        assert observed["active"]["value"] is None
    else:
        assert observed["active"]["value"] == "on"
        assert observed["active"]["source_changed"] == "2026-10-23T19:00:00+00:00"
        assert observed["active"]["source_reported"] == "2026-10-23T19:00:45+00:00"
        assert observed["diagnostic"]["value"] == "tapwater"
    assert observed["active"]["received"] == NOW
