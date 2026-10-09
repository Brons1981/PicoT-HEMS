from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picot_energy_devices.ev_sessions import EVSessionManager

POWER = "sensor.shellyplugsg3_d885ac1e8c94_vermogen"
SWITCH = "switch.shellyplugsg3_d885ac1e8c94"


class Rig:
    def __init__(self, path: Path):
        self.now = datetime(2026, 10, 10, 10, tzinfo=UTC)
        self.manager = EVSessionManager(
            path, power_entity=POWER, switch_entity=SWITCH, now=lambda: self.now
        )
        self.commands = []

    def tick(self, power=2000, switch="on", seconds=1):
        self.now += timedelta(seconds=seconds)
        return self.manager.tick(
            measured_at=self.now if power is not None else None,
            power_w=power,
            switch_state=switch,
            set_switch=self.commands.append,
        )

    def recognize(self):
        for _ in range(31):
            view = self.tick()
        return view["sessions"][-1]

    def plan(self, duration=3600):
        session = self.recognize()
        self.tick(0, "off")
        self.manager.action({"action": "verify_resume", "confirmed": True})
        start = self.now + timedelta(seconds=60)
        self.manager.action(
            {
                "action": "plan",
                "session_id": session["session_id"],
                "planned_start": start.isoformat(),
                "expected_power_w": 2000,
                "expected_duration_seconds": duration,
            }
        )
        return start


def test_short_spike_does_not_create_session(tmp_path):
    rig = Rig(tmp_path / "db")
    for _ in range(20):
        rig.tick()
    rig.tick(0)
    assert not rig.manager.view()["sessions"]


def test_pauses_and_tail_remain_one_session(tmp_path):
    rig = Rig(tmp_path / "db")
    first = rig.recognize()["session_id"]
    for _ in range(80):
        rig.tick(0)
    rig.tick(1800)
    assert len(rig.manager.view()["sessions"]) == 1
    for _ in range(301):
        rig.tick(0)
    session = rig.manager.view()["sessions"][0]
    assert session["session_id"] == first
    assert session["state"] == "completed"


def test_off_preserves_plan_and_restart_does_not_start_early(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    rig.tick(0, "off")
    new = EVSessionManager(
        tmp_path / "db", power_entity=POWER, switch_entity=SWITCH, now=lambda: rig.now
    )
    assert new.view()["sessions"][-1]["state"] == "planned"
    assert new.snapshot()["session"]["remaining_energy_wh"] == 2000
    assert rig.commands == []
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == [True]
    rig.tick(2000, "on")
    assert rig.manager.view()["sessions"][-1]["state"] == "active"


def test_resume_verification_is_required(tmp_path):
    rig = Rig(tmp_path / "db")
    session = rig.recognize()
    rig.tick(0, "off")
    with pytest.raises(ValueError, match="hervattest"):
        rig.manager.action(
            {
                "action": "plan",
                "session_id": session["session_id"],
                "planned_start": (rig.now + timedelta(hours=1)).isoformat(),
                "expected_power_w": 2000,
                "expected_duration_seconds": 3600,
            }
        )


def test_cancellation_removes_future_demand_and_never_starts(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    session = rig.manager.view()["sessions"][-1]
    rig.manager.action({"action": "cancel", "session_id": session["session_id"]})
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == []
    assert rig.manager.snapshot()["session"]["state"] == "cancelled"


def test_missing_readings_do_not_complete_session_or_invent_energy(tmp_path):
    rig = Rig(tmp_path / "db")
    rig.recognize()
    before = rig.manager.view()["sessions"][-1]["delivered_energy_wh"]
    for _ in range(400):
        rig.tick(None)
    session = rig.manager.view()["sessions"][-1]
    assert session["state"] == "active"
    assert session["delivered_energy_wh"] == before
    rig.tick()
    assert rig.manager.view()["sessions"][-1]["measurement_complete"] is False


def test_end_time_stops_owned_session_and_waits_for_confirmation(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan(duration=60)
    rig.now = start
    rig.tick(0, "off")
    rig.tick(2000, "on")
    rig.now = start + timedelta(seconds=60)
    rig.tick(2000, "on")
    assert rig.commands == [True, False]
    assert rig.manager.view()["sessions"][-1]["state"] != "completed"
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["state"] == "completed"


def test_repeated_report_does_not_integrate_twice(tmp_path):
    rig = Rig(tmp_path / "db")
    rig.recognize()
    report = rig.now
    rig.tick()
    before = rig.manager.view()["sessions"][-1]["delivered_energy_wh"]
    rig.manager.tick(
        measured_at=report, power_w=2000, switch_state="on", set_switch=rig.commands.append
    )
    assert rig.manager.view()["sessions"][-1]["delivered_energy_wh"] == before


def test_manual_off_does_not_fight_user_and_explicit_resume_restarts(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    rig.now = start
    rig.tick(0, "off")
    rig.tick(2000, "on")
    rig.tick(0, "off")
    for _ in range(15):
        rig.tick(0, "off")
    assert rig.commands == [True]
    rig.manager.action({"action": "resume"})
    rig.tick(0, "off")
    assert rig.commands == [True, True]


def test_failed_command_retries_without_losing_plan(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    rig.now = start

    def fail(_enabled):
        raise OSError("HA service unavailable")

    rig.manager.tick(measured_at=rig.now, power_w=0, switch_state="off", set_switch=fail)
    assert rig.manager.view()["sessions"][-1]["error"] == "HA service unavailable"
    assert rig.manager.view()["sessions"][-1]["state"] == "planned"
    rig.tick(0, "off", seconds=5)
    assert rig.commands == []
    rig.tick(0, "off", seconds=5)
    assert rig.commands == [True]


def test_recognition_inclu…14050 tokens truncated…            return ()

        observations: list[HouseholdLoadObservation] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

        for line in lines:
            observation = _decode_observation(line)
            if observation is not None:
                observations.append(observation)
        return tuple(observations)


def _decode_observation(
    line: str,
) -> HouseholdLoadObservation | None:
    try:
        payload: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != 1:
        return None

    power_w = payload.get("power_w")
    external = payload.get("identified_external_power_w", 0.0)
    external_observed = payload.get("external_power_observed", False)
    sampled_at = payload.get("sampled_at")
    raw_evidence_ids = payload.get("evidence_ids")
    method_version = payload.get("method_version")
    if (
        not isinstance(external_observed, bool)
        or isinstance(external, bool)
        or not isinstance(external, (int, float))
        or isinstance(power_w, bool)
        or not isinstance(power_w, (int, float))
        or not isinstance(sampled_at, str)
        or not isinstance(raw_evidence_ids, list)
        or not isinstance(method_version, str)
    ):
        return None

    evidence_ids: list[str] = []
    for evidence_id in raw_evidence_ids:
        if not isinstance(evidence_id, str):
            return None
        evidence_ids.append(evidence_id)

    try:
        parsed_at = datetime.fromisoformat(sampled_at.replace("Z", "+00:00"))
        return HouseholdLoadObservation(
            power_w=float(power_w),
            identified_external_power_w=float(external),
            external_power_observed=external_observed,
            sampled_at=parsed_at,
            evidence_ids=tuple(evidence_ids),
            method_version=method_version,
        )
    except ValueError:
        return None
