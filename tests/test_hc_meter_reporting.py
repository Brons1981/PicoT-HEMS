"""Fresh source reports distinguish unchanged readings from stale HA JSON."""
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from picot_hc.core import fetch_states
from picot_hc.energy_measurement import measurement

METER = "sensor.kwh_meter_airco_vermogen"
NOW = datetime(2026, 10, 24, 21, 1, tzinfo=UTC).timestamp()
CONFIG = {"zones": [{"id": "beneden", "power": METER,
                    "energy": "sensor.kwh_meter_airco_energie_import", "device": "climate.airco"}]}


def state(at, value="0"):
    stamp = datetime.fromtimestamp(at, UTC).isoformat()
    return dict(entity_id=METER, state=value, last_updated=stamp, last_reported=stamp,
                attributes={"unit_of_measurement": "W"})


def read(cached, report):
    replies = [[cached], report]
    class Opener:
        def open(self, request, timeout):
            if request.full_url.endswith("/template"):
                assert METER in json.loads(request.data)["template"]
            value = replies.pop(0)
            if isinstance(value, Exception):
                raise value
            return io.StringIO(json.dumps(value))
    with patch("picot_hc.core.build_opener", return_value=Opener()):
        return fetch_states("http://ha.invalid", "test", [METER])


def test_unchanged_zero_uses_actual_source_report_not_cached_change_time():
    states = read(state(NOW-600), [state(NOW-5)])
    result = measurement(CONFIG, states, NOW)
    assert result["status"] == "available" and result["power_w"] == 0
    assert result["measured_at"] == state(NOW-5)["last_reported"]


@pytest.mark.parametrize("report", [[], OSError("offline"), [{"entity_id": METER}]])
def test_failed_report_cannot_reuse_even_recent_cached_zero(report):
    result = measurement(CONFIG, read(state(NOW-5), report), NOW)
    assert result["status"] == "unavailable"
    assert result["power_w"] is None
    assert result["reason"] == "source_report_unavailable"


@pytest.mark.parametrize("age,value,reason", [
    (61,"0","source_report_stale"), (61,"750","source_report_stale"),
    (-1,"0","source_report_future"), (5,"unavailable","source_unavailable"),
    (5,"nan","source_value_invalid"), (5,"-1","source_value_invalid"),
])
def test_real_outage_or_old_reading_stays_unknown_with_explicit_reason(age,value,reason):
    result = measurement(CONFIG, read(state(NOW-600), [state(NOW-age,value)]), NOW)
    assert result["status"] == "unavailable" and result["power_w"] is None
    assert result["reason"] == reason
    assert result["error"]



def test_controller_requests_meter_report_alongside_temperatures(tmp_path):
    from picot_hc.control import Control
    from picot_hc.core import Store
    config = json.loads((Path(__file__).parents[1] / "picot_hc/options.example.json").read_text())
    zone = next(z for z in config["zones"] if z["id"] == "beneden")
    zone["power"] = METER
    ctl = Control(config, Store(tmp_path / "hc.sqlite3"), "http://ha.invalid", "test")
    assert METER in ctl.report_entities
    assert set(ctl.temperature_entities) <= set(ctl.report_entities)


def test_hc_failure_reason_survives_hems_source_boundary():
    from picot.v2.planning_input import HomeAssistantStateReader, SourceBinding
    value = measurement(CONFIG, {METER: state(NOW-61)}, NOW)
    payload = dict(state=value["status"], attributes=value,
                   last_updated=datetime.fromtimestamp(NOW, UTC).isoformat())
    with patch("picot.v2.planning_input.urlopen",
               return_value=io.BytesIO(json.dumps(payload).encode())):
        source = HomeAssistantStateReader("test").read(SourceBinding(
            "energy_devices", "controlled_load_measurement", "sensor.picot_hc_load_measurement"))
    assert source.availability == "unavailable"
    assert source.error == ("De laatste bronrapportage van de aircovermogensmeter "
                            "is ouder dan 60 seconden.")
    assert source.external_load_payload is None
