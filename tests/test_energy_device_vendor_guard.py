import copy
import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import yaml
from jinja2 import Environment

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "guard_builder", ROOT / "homeassistant/energy_devices/build_guarded_zendure.py"
)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
NOW = datetime(2026, 10, 8, 17, tzinfo=UTC)


def stamp(value, default=0):
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return default


def evaluate_guard(
    policy_state="enabled",
    policy_age=0,
    battery_age=0,
    p1_age=0,
    status="ready",
    derived_age=0,
    selected="sensor.ct_shelly_pro_3em_api",
):
    policy = (
        SimpleNamespace(
            state=policy_state,
            attributes={
                "status": status,
                "measured_at": (NOW - timedelta(seconds=policy_age)).isoformat(),
            },
        )
        if policy_state
        else None
    )
    states = SimpleNamespace(
        input_text=SimpleNamespace(afwijkende_p1_sensor=SimpleNamespace(state=selected)),
        sensor=SimpleNamespace(
            picot_ev_regulation_policy=policy,
            p1_aansturing_vermogen=SimpleNamespace(
                state="0", last_reported=NOW - timedelta(seconds=derived_age)
            ),
            ct_shelly_pro_3em_api=SimpleNamespace(
                state="0",
                last_reported=NOW - timedelta(seconds=p1_age),
                attributes={"measured_at": (NOW - timedelta(seconds=p1_age)).isoformat()},
            ),
            zendure_2400_ac_vermogen_aansturing=SimpleNamespace(
                state="750", last_reported=NOW - timedelta(seconds=battery_age)
            ),
        ),
    )
    return (
        Environment()
        .from_string(BUILDER.GUARD)
        .render(states=states, now=lambda: NOW, as_timestamp=stamp)
        .strip()
        == "True"
    )


class VendorGuardTests(unittest.TestCase):
    def test_ready_allows_original_controller(self):
        self.assertFalse(evaluate_guard())
        self.assertFalse(evaluate_guard(policy_state="disabled", battery_age=100))
        self.assertFalse(evaluate_guard(derived_age=3600))

    def test_stale_missing_future_or_blocked_policy_stops(self):
        for args in [
            {"policy_age": 4},
            {"battery_age": 4},
            {"p1_age": 4},
            {"policy_state": None},
            {"status": "blocked"},
            {"battery_age": -1},
            {"selected": "sensor.homewizard_p1_vermogen"},
        ]:
            self.assertTrue(evaluate_guard(**args), args)

    def test_generated_automation_contains_original_branches_and_only_stop_action(self):
        document = yaml.safe_load(
            (ROOT / "homeassistant/energy_devices/zendure_ev_guarded_test.yaml").read_text()
        )
        nom = next(x for x in document["actions"] if x.get("alias") == "NOM Aansturing")
        self.assertEqual(len(nom["default"][0]["choose"]), 4)
        self.assertEqual(
            nom["choose"][0]["sequence"][0]["action"], "rest_command.zendure_stop_met_alles"
        )
        with self.assertRaises(ValueError):
            BUILDER.guarded(copy.deepcopy(document))
        modes = nom["choose"][0]["conditions"][1]["state"]
        self.assertNotIn("Snel opladen", modes)
        self.assertNotIn("Snel ontladen", modes)


if __name__ == "__main__":
    unittest.main()
