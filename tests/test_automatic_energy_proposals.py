from picot.v2.energy_outlook import ENTITY, outlook
from picot.v2.energy_portfolio import assess
from picot_hc.core import Store
from picot_hc.energy_outlook import read_outlook
from picot_hc.energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY, read_assessment
from picot_hc.energy_proposals import Proposals
from test_daily_main_charge_windows import inputs as configuration
from test_delayed_start import evidence as delayed_evidence
from test_energy_proposals import inputs, sample, train
from test_ev_deadline_advice import scenario
from test_load_replacement import basis_for
from test_warmup_plans import setup as warmup_setup


def test_learned_hc_request_reaches_real_hems_assessment_without_execution(tmp_path):
    retained, snapshot, _ = scenario(tmp_path, soc=0.9)
    untouched = retained._load_payload()
    basis = basis_for(snapshot)
    value = outlook(snapshot, configuration()["conversion_model"])
    value["replacement_basis"] = basis.public()
    now = snapshot.captured_at.timestamp()
    received = read_outlook({ENTITY: dict(state="ready", attributes=value)}, now)
    sent = []

    class Publisher:
        def submit(self, payload):
            sent.append(payload)

    generator = Proposals(Store(tmp_path / "hc.sqlite"), Publisher())
    train(generator.model, now=now)
    view, plan, _ = inputs(now)
    generator.tick(sample(3780), view, plan, received, now)
    request = sent[-1]["attributes"]
    assert sent[-1]["state"] == "requested"
    answer = assess(snapshot, request, configuration()["conversion_model"], replacement_basis=basis)
    assert answer["status"] in ("selected", "rejected"), answer
    assert answer["scope"] == "replacement_demand_on_retained_route"
    assert answer["execution_authorized"] is False
    assert retained._load_payload() == untouched
    feedback = read_assessment(
        {
            REQUEST_ENTITY: sent[-1],
            RESPONSE_ENTITY: dict(state=answer["status"], attributes=answer),
        },
        now,
    )
    assert feedback["status"] == answer["status"]
    generator.tick(None, view, plan, received, now + 30)
    assert sent[-1]["state"] == "withdrawn"
    feedback = read_assessment(
        {
            REQUEST_ENTITY: sent[-1],
            RESPONSE_ENTITY: dict(state=answer["status"], attributes=answer),
        },
        now + 30,
    )
    assert feedback["status"] == "waiting"


def test_measured_warmup_batch_is_assessed_on_retained_route(tmp_path):
    retained, snapshot, _ = scenario(tmp_path, soc=0.9)
    before = retained._load_payload()
    basis = basis_for(snapshot)
    value = outlook(snapshot, configuration()["conversion_model"])
    value["replacement_basis"] = basis.public()
    now = snapshot.captured_at.timestamp()
    received = read_outlook({ENTITY: dict(state="ready", attributes=value)}, now)
    generator, warmup, view, plan, _, sent = warmup_setup(tmp_path, now)
    generator.tick(
        None, view, plan, received, now, warmup=warmup, warmup_sample=dict(sample(), indoor=18)
    )
    assert sent[-1]["state"] == "requested"
    request = sent[-1]["attributes"]
    assert len(request["plans"]) == 3
    answer = assess(snapshot, request, configuration()["conversion_model"], replacement_basis=basis)
    assert answer["status"] in ("selected", "rejected"), answer
    assert answer["execution_authorized"] is False
    assert retained._load_payload() == before
    feedback = read_assessment(
        {
            REQUEST_ENTITY: sent[-1],
            RESPONSE_ENTITY: dict(state=answer["status"], attributes=answer),
        },
        now,
    )
    assert feedback["status"] == answer["status"]


def test_start_time_choices_reach_hems_without_changing_retained_route(tmp_path):
    retained, snapshot, _ = scenario(tmp_path, soc=0.9)
    before = retained._load_payload()
    basis = basis_for(snapshot)
    value = outlook(snapshot, configuration()["conversion_model"])
    value["replacement_basis"] = basis.public()
    now = snapshot.captured_at.timestamp()
    received = read_outlook({ENTITY: dict(state="ready", attributes=value)}, now)
    startup, steady, standby, s, view, plan = delayed_evidence(tmp_path, now)
    for point in standby.points:
        point["time"] -= 60
    s["energy_wh"] = standby.points[-1]["energy_wh"] + 1 / 6
    sent = []

    class Publisher:
        submit = staticmethod(sent.append)

    generator = Proposals(Store(tmp_path / "hc.sqlite"), Publisher())
    generator.model, generator.standby = steady, standby
    generator.tick(None, view, plan, received, now, startup=startup, idle_sample=s)
    assert sent[-1]["state"] == "requested"
    assert len(sent[-1]["attributes"]["plans"]) == 4
    assert generator.view(now)["kind"] == "delayed_start"
    request = sent[-1]["attributes"]
    generator.tick(
        None,
        view,
        plan,
        received,
        now + 30,
        startup=startup,
        idle_sample=dict(s, energy_wh=s["energy_wh"] + 1 / 12),
    )
    assert sent[-1]["state"] == "requested"
    assert sent[-1]["attributes"]["request_id"] == request["request_id"]
    assert "target" not in str(request) and "beneden" not in str(request)
    answer = assess(snapshot, request, configuration()["conversion_model"], replacement_basis=basis)
    assert answer["status"] in ("selected", "rejected"), answer
    assert answer["execution_authorized"] is False
    assert retained._load_payload() == before
    feedback = read_assessment(
        {
            REQUEST_ENTITY: sent[-1],
            RESPONSE_ENTITY: dict(state=answer["status"], attributes=answer),
        },
        now,
    )
    assert feedback["status"] == answer["status"]
    plan["zones"]["beneden"]["target"] = 17.95
    generator.tick(
        None,
        view,
        plan,
        received,
        now + 60,
        startup=startup,
        idle_sample=dict(s, energy_wh=s["energy_wh"] + 1 / 6),
    )
    assert sent[-1]["state"] == "withdrawn"
