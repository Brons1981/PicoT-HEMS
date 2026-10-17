from datetime import timedelta

from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import scenario
from test_ev_direct_start import profile
from test_ev_sessions import Rig

from picot.v2.ev_deadline_runtime import EVDeadlineAdvisor


def setup_request(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    rig = Rig(tmp_path / "ev")
    rig.now = snapshot.captured_at
    profile(rig)
    rig.manager.action({"action": "request_advice", "required_energy_wh": 1000,
                        "ready_by": (rig.now + timedelta(hours=22)).isoformat()})
    return rig, snapshot


def test_request_real_hems_assessment_and_return_to_dashboard_state(tmp_path):
    rig, snapshot = setup_request(tmp_path)
    advisor = EVDeadlineAdvisor(
        read=rig.manager.advice_exchange, publish=rig.manager.receive_advice,
        configuration=lambda _: inputs()["conversion_model"], now=lambda: rig.now,
    )
    advisor.refresh(snapshot)
    advice = rig.manager.view()["charging_advice"]
    assert advice["status"] == "ready", advice
    assert advice["scheduled_energy_wh"] == 1000
    assert advice["snapshot_id"] == snapshot.snapshot_id
    assert rig.manager.view()["sessions"] == []
    assert rig.commands == []


def test_cancel_while_assessing_prevents_publication(tmp_path):
    rig, snapshot = setup_request(tmp_path)
    published = []

    def configuration(_):
        rig.manager.action({"action": "cancel_advice"})
        return inputs()["conversion_model"]

    advisor = EVDeadlineAdvisor(read=rig.manager.advice_exchange, publish=published.append,
                                configuration=configuration, now=lambda: rig.now)
    advisor.refresh(snapshot)
    assert published == []


def test_stale_planning_input_does_not_produce_new_advice(tmp_path):
    rig, snapshot = setup_request(tmp_path)
    rig.now += timedelta(minutes=3)
    published = []
    advisor = EVDeadlineAdvisor(
        read=rig.manager.advice_exchange, publish=published.append,
        configuration=lambda _: inputs()["conversion_model"], now=lambda: rig.now,
    )
    advisor.refresh(snapshot)
    assert published == []
