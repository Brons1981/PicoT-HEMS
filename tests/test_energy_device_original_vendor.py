"""Execute original licensed NOM templates; no production vendor wrapper."""

import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment

ROOT = Path(__file__).parents[1]
SOURCE = json.loads((ROOT / "tests/fixtures/zendure_original_nom.json").read_text())
ENV = Environment()


def states(grid, battery, charging=0, discharging=0):
    return {
        "sensor.p1_aansturing_vermogen": grid,
        "sensor.zendure_2400_ac_vermogen_aansturing": battery,
        "sensor.zendure_2400_ac_ingesteld_oplaadvermogen": charging,
        "sensor.zendure_2400_ac_ingesteld_ontlaadvermogen": discharging,
        "input_number.zendure_2400_ac_max_oplaadvermogen": 2400,
        "input_number.zendure_2400_ac_max_ontlaadvermogen": 2400,
        "input_number.zendure_2400_ac_oplaadmarge": 50,
        "input_number.zendure_2400_ac_ontlaadmarge": 5,
    }


def render(template, values):
    return (
        ENV.from_string(template)
        .render(
            states=lambda entity: str(values.get(entity, "unknown")),
            this=SimpleNamespace(attributes=SimpleNamespace(current=0)),
        )
        .strip()
    )


@pytest.mark.parametrize(
    "branch,grid,battery,charging,discharging,target",
    [
        (0, 200, 0, 0, 0, 153),
        (1, 2000, -200, 0, 200, 2205),
        (2, -800, 0, 0, 0, 562),
        (3, 0, 800, 800, 0, 750),
    ],
)
def test_original_command_templates(branch, grid, battery, charging, discharging, target):
    action = next(
        x
        for x in SOURCE["nom"][branch]["sequence"]
        if x.get("action", "").startswith("rest_command.")
    )
    template = action["data"].get("inputLimit", action["data"].get("outputLimit"))
    assert int(render(template, states(grid, battery, charging, discharging))) == target


def test_original_emergency_waits_one_minute_and_is_not_a_new_guard():
    conditions = SOURCE["emergency"]["conditions"]
    unavailable = next(
        c for c in conditions if c.get("entity_id") == "sensor.p1_aansturing_vermogen"
    )
    assert unavailable["for"] == {"hours": 0, "minutes": 1, "seconds": 0}
    assert unavailable["state"] == ["unavailable", "unknown"]
    assert SOURCE["emergency"]["sequence"][0]["action"] == "rest_command.zendure_stop_met_alles"
    assert not (ROOT / "homeassistant/energy_devices/zendure_ev_guarded_test.yaml").exists()
    assert not (ROOT / "homeassistant/energy_devices/build_guarded_zendure.py").exists()


def test_rest_sensor_marks_missing_or_invalid_json_power_unavailable():
    text = (ROOT / "homeassistant/energy_devices/ct_regulation_rest_fragment.yaml").read_text()
    template = re.search(r'availability: "(.*)"', text).group(1)

    def is_number(value):
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    compiled = ENV.from_string(template)
    assert compiled.render(is_number=is_number) == "False"
    for payload in ({}, {"total_act_power": None}, {"total_act_power": "unknown"}):
        assert compiled.render(value_json=payload, is_number=is_number) == "False"
    for value in (0, -800, 200):
        assert compiled.render(value_json={"total_act_power": value}, is_number=is_number) == "True"
