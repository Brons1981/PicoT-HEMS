import json
from datetime import UTC, datetime, timedelta

import pytest

from picot_energy_devices.ev_sessions import EVSessionManager
from picot_energy_devices.regulation import RegulationSnapshotStore
from picot_energy_devices.runtime import ev_poll_once, regulation_poll_once
from picot_energy_devices.shelly_ev import ShellyEVSource

URL = "http://192.168.6.113/rpc/Switch.GetStatus?id=0"


def response(monkeypatch, *, power=2334.7, output=True):
    payload = {"id": 0, "output": output, "apower": power, "aenergy": {"total": 216504.068}}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def geturl(self):
            return URL

        def read(self, _limit):
            return json.dumps(payload).encode()

    def get(request, *, timeout):
        assert request.full_url == URL
        assert not request.has_header("Authorization")
        assert timeout == 2
        return Reply()

    monkeypatch.setattr("picot_energy_devices.shelly_ev.urlopen", get)


def test_shared_local_report_preserves_time_and_detects_stop(monkeypatch):
    response(monkeypatch)
    source = ShellyEVSource(URL)
    source.poll_once()
    first = source.read()
    assert first.power.watts == 2334.7
    assert first.energy_wh == 216504.068
    assert source.read() is first
    response(monkeypatch, power=0, output=False)
    source.poll_once()
    stopped = source.read()
    assert not stopped.output
    assert stopped.power.watts == 0
    assert stopped.switch_changed_at > first.switch_changed_at


def test_timeout_discards_previous_report_and_invalid_values_block(monkeypatch):
    response(monkeypatch)
    source = ShellyEVSource(URL)
    source.poll_once()

    def fail(*_, **__):
        raise TimeoutError("test timeout")

    monkeypatch.setattr("picot_energy_devices.shelly_ev.urlopen", fail)
    source.poll_once()
    with pytest.raises(ValueError, match="ev_local_api_unavailable"):
        source.read()
    response(monkeypatch, power=float("nan"))
    source.poll_once()
    with pytest.raises(ValueError, match="invalid power"):
        source.read()
    response(monkeypatch, power=2300, output=False)
    source.poll_once()
    with pytest.raises(ValueError, match="inconsistent off/power"):
        source.read()


def test_cached_local_report_is_not_refreshed(monkeypatch):
    response(monkeypatch)
    source = ShellyEVSource(URL)
    source.poll_once()
    from dataclasses import replace

    local = source.read()
    source.observation = replace(local, power=replace(
        local.power, reported_at=datetime.now(UTC) - timedelta(seconds=4)
    ))
    with pytest.raises(ValueError, match="ev_local_api_stale"):
        source.read()


def test_local_measurement_drives_real_session_and_regulation(monkeypatch, tmp_path):
    response(monkeypatch)
    source = ShellyEVSource(URL)
    source.poll_once()

    class Client:
        def state(self, entity):
            assert entity in {"sensor.raw", "sensor.battery"}
            return {"state": "258" if entity == "sensor.raw" else "-2394",
                    "last_reported": datetime.now(UTC).isoformat(),
                    "attributes": {"unit_of_measurement": "W"}}

        def publish_ev_session(self, snapshot):
            self.session = snapshot

        def publish_regulation_shadow(self, result):
            self.shadow = result

        def publish_regulation_policy(self, result):
            self.policy = result

    client = Client()
    manager = EVSessionManager(tmp_path / "ev.db", power_entity="sensor.ev",
                               switch_entity="switch.ev")
    ev_poll_once(manager, client, source)
    assert client.session["session"]["expected_power_w"] == 2334.7
    assert client.session["ev_measurement_source"] == "local_rpc"
    snapshots = RegulationSnapshotStore(control_enabled=True)
    for _ in range(3):
        source.poll_once()
        regulation_poll_once(client=client, raw_entity="sensor.raw",
                             battery_entity="sensor.battery", ev_entity="sensor.ev",
                             ev_source=source, snapshots=snapshots)
    assert client.policy["status"] == "ready"
    assert client.policy["candidate_w"] == -2094
    assert client.policy["ev_measurement_source"] == "local_rpc"
    response(monkeypatch, power=0, output=False)
    source.poll_once()
    regulation_poll_once(client=client, raw_entity="sensor.raw",
                         battery_entity="sensor.battery", ev_entity="sensor.ev",
                         ev_source=source, snapshots=snapshots)
    assert client.policy["candidate_w"] == 258
    ev_poll_once(manager, client, source)
    assert client.session["session"]["switch_state"] == "off"
    assert len(manager.view()["sessions"]) == 1
    source.observation = None
    source.error = "ev_local_api_unavailable"
    regulation_poll_once(client=client, raw_entity="sensor.raw",
                         battery_entity="sensor.battery", ev_entity="sensor.ev",
                         ev_source=source, snapshots=snapshots)
    assert client.policy["status"] == "blocked"
    assert client.policy["candidate_w"] is None
    assert client.policy["reason"] == "ev_local_api_unavailable"


@pytest.mark.parametrize("url", ["https://example.com", "http://user:pass@host/rpc/Switch.GetStatus?id=0",
                                 "http://host/rpc/Switch.Set?id=0&on=true"])
def test_source_is_read_only_fixed_rpc(url):
    with pytest.raises(ValueError):
        ShellyEVSource(url)
