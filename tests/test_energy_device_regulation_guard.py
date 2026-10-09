from datetime import UTC, datetime, timedelta

import pytest

from picot_energy_devices.home_assistant import HomeAssistantClient
from picot_energy_devices.regulation import PowerReport, RegulationObserver, RegulationSnapshotStore
from picot_energy_devices.regulation_guard import CorrectionGuard
from picot_energy_devices.runtime import regulation_poll_once

NOW = datetime(2026, 10, 9, 22, tzinfo=UTC)


def result(seconds=0, candidate=200):
    when = NOW + timedelta(seconds=seconds)
    return dict(status="ready", candidate_w=candidate, raw_grid_w=candidate + 2300,
                evaluated_at=when.isoformat(), source_measured_at=when.isoformat(),
                source_ages_seconds=[0, 0], fallback="none")


def check(guard, seconds, *, candidate=200, offered=200, blocked=False):
    value = result(seconds, candidate)
    if blocked:
        value.update(status="blocked", candidate_w=None, reason="missing_source")
    return guard.check(result=value, offered_w=offered, now=NOW + timedelta(seconds=seconds))


@pytest.mark.parametrize("delay", [0, 1, 4, 5])
def test_fast_ev_oven_and_pv_steps_allow_consumer_transfer_delay(delay):
    guard = CorrectionGuard(enabled=True)
    candidates = []
    observer = RegulationObserver()
    for second in range(180):
        # EV starts/stops and steps; thermostat cycles; PV changes direction.
        ev = [0, 2300, 1200, 2300][(second // 7) % 4]
        house = 200 + (2200 if second % 30 < 15 else 0)
        pv = [0, 3000, 800, 4000][(second // 11) % 4]
        battery = [0, -200, 800][(second // 5) % 3]
        when = NOW + timedelta(seconds=second)
        value = observer.evaluate(PowerReport(house + ev - pv + battery, when),
                                  PowerReport(battery, NOW - timedelta(hours=1)),
                                  PowerReport(ev, when), now=when)
        candidates.append(value["candidate_w"])
        offered = candidates[max(0, second - delay)]
        output = guard.check(result=value, offered_w=offered, now=when)
        assert output["correction_guard"] != "latched"
        assert output["candidate_w"] == candidates[-1]
    assert guard.latched_reason is None


def test_persistent_wrong_correction_latches_and_never_auto_recovers(tmp_path):
    path = tmp_path / "guard.json"
    guard = CorrectionGuard(enabled=True, path=path)
    check(guard, 0)
    for second in range(1, 31):
        assert check(guard, second, offered=2500)["status"] == "ready"
    value = check(guard, 31, offered=2500)
    assert value["reason"] == "offered_correction_mismatch"
    assert value["candidate_w"] is None
    assert check(guard, 32)["fallback"] == "latched_raw_fallback"
    restarted = CorrectionGuard(enabled=True, path=path)
    assert check(restarted, 33)["status"] == "blocked"
    CorrectionGuard(enabled=False, path=path)
    assert not path.exists()
    assert CorrectionGuard(enabled=True, path=path).latched_reason is None


def test_transient_mismatch_is_reset_by_a_matching_offer():
    guard = CorrectionGuard(enabled=True)
    check(guard, 0)
    for second in range(1, 100):
        offered = 200 if second % 20 == 0 else 2500
        assert check(guard, second, offered=offered)["status"] == "ready"


@pytest.mark.parametrize("missing_offer", [False, True])
def test_missing_measurement_is_bounded_and_latched(missing_offer):
    guard = CorrectionGuard(enabled=True)
    check(guard, 0)
    deadline = 11 if missing_offer else 10
    for second in range(1, deadline):
        output = check(guard, second, offered=None if missing_offer else 200,
                       blocked=not missing_offer)
        assert output["correction_guard"] != "latched"
    assert check(guard, deadline, offered=None if missing_offer else 200,
                 blocked=not missing_offer)["reason"] == "persistent_measurement_loss"
    assert check(guard, 12)["status"] == "blocked"



def test_already_ageing_source_cannot_restart_the_missing_measurement_grace():
    guard = CorrectionGuard(enabled=True)
    value = result(3)
    value.update(source_measured_at=NOW.isoformat(), source_ages_seconds=[3, 0])
    guard.check(result=value, offered_w=200, now=NOW + timedelta(seconds=3))
    assert check(guard, 9, blocked=True)["correction_guard"] != "latched"
    assert check(guard, 10, blocked=True)["reason"] == "persistent_measurement_loss"

def test_short_measurement_gap_recovers_without_changing_measurement_time():
    store = RegulationSnapshotStore(control_enabled=True, measurement_grace_seconds=10,
                                    minimum_ready_reports=1)
    store.update(result())
    for second in range(1, 10):
        value = result(second)
        value.update(status="blocked", candidate_w=None)
        store.update(value)
        snapshot = store.read(now=NOW + timedelta(seconds=second))
        assert snapshot["total_act_power"] == 200
        assert snapshot["measured_at"] == NOW.isoformat()
        assert snapshot["source_ages_seconds"] == [second, second]
    store.update(result(10, 500))
    assert store.read(now=NOW + timedelta(seconds=10))["total_act_power"] == 500


def test_hold_expires_without_refresh_and_never_overrides_latched_fallback():
    store = RegulationSnapshotStore(control_enabled=True, measurement_grace_seconds=10,
                                    minimum_ready_reports=1)
    store.update(result())
    assert store.read(now=NOW + timedelta(seconds=4)) is None  # producer died
    for second in range(1, 12):
        value = result(second)
        value.update(status="blocked", candidate_w=None)
        store.update(value)
        assert (store.read(now=NOW + timedelta(seconds=second)) is not None) == (second <= 10)
    store.update(result(12))
    value = result(13)
    value.update(status="blocked", candidate_w=None, fallback="latched_raw_fallback")
    store.update(value)
    assert store.read(now=NOW + timedelta(seconds=13)) is None


def test_corrupt_persisted_guard_stays_on_raw(tmp_path):
    path = tmp_path / "guard.json"
    path.write_text("bad json")
    guard = CorrectionGuard(enabled=True, path=path)
    assert check(guard, 0)["reason"] == "guard_state_unreadable"


def test_runtime_reads_actual_consumer_and_holds_then_latches_missing_source(monkeypatch):
    class Client:
        unavailable = False

        def state(self, entity):
            if self.unavailable and entity == "sensor.ev":
                raise OSError("source unavailable")
            return {"state": {"sensor.raw": "2500", "sensor.battery": "0",
                              "sensor.ev": "2300", "sensor.ct": "200"}[entity],
                    "last_reported": (NOW - timedelta(hours=1) if entity == "sensor.battery"
                                      else clock.when).isoformat(),
                    "attributes": {"unit_of_measurement": "W"}}

        measurement = staticmethod(HomeAssistantClient.measurement)

        def publish_regulation_shadow(self, value):
            self.shadow = value

        def publish_regulation_policy(self, value):
            self.policy = value

    class Clock:
        when = NOW

        @classmethod
        def now(cls, tz):
            return cls.when

    clock = Clock
    monkeypatch.setattr("picot_energy_devices.runtime.datetime", clock)
    client = Client()
    guard = CorrectionGuard(enabled=True)
    store = RegulationSnapshotStore(control_enabled=True, measurement_grace_seconds=10,
                                    minimum_ready_reports=1)
    for second in range(13):
        clock.when = NOW + timedelta(seconds=second)
        client.unavailable = second >= 1
        regulation_poll_once(client=client, raw_entity="sensor.raw",
                             battery_entity="sensor.battery",
                             ev_entity="sensor.ev", offered_entity="sensor.ct", guard=guard,
                             snapshots=store)
        if second == 0:
            assert client.policy["candidate_w"] == 200
        if second == 5:
            assert client.policy["holding_measurement"] is True
            assert client.policy["measured_at"] == NOW.isoformat()
        if second >= 10:
            assert client.policy["reason"] == "persistent_measurement_loss"
            assert store.read(now=clock.when) is None
