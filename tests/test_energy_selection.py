import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from picot.v2.energy_portfolio_runtime import PortfolioAdvisor
from picot.v2.energy_selection import validate_selection
from picot_hc.core import Store
from picot_hc.energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY
from picot_hc.energy_selection import Selection
from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import scenario
from test_load_replacement import basis_for, proposal


def setup(tmp_path):
    retained, snapshot, _ = scenario(tmp_path, soc=0.9)
    basis = basis_for(snapshot)
    request = proposal(snapshot, basis)
    answers, messages = [], []
    clock = [snapshot.captured_at]
    worker = PortfolioAdvisor(
        lambda: request,
        answers.append,
        lambda s: inputs()["conversion_model"],
        now=lambda: clock[0],
        read_selection=lambda: (
            messages[-1]["attributes"]
            if messages and messages[-1]["state"] == "confirmed"
            else None
        ),
    )
    worker.refresh(snapshot, basis)
    assert answers[-1]["status"] == "selected"
    states = {
        REQUEST_ENTITY: dict(state="requested", attributes=request),
        RESPONSE_ENTITY: dict(state="selected", attributes=answers[-1]),
    }
    local = SimpleNamespace(
        pending=request,
        local=dict(
            expires=clock[0].timestamp() + 120,
            action="continue_warmup",
            candidates=[dict(plan_id="hold", target=20, slots=request["plans"][0]["slots"])],
        ),
    )
    store = Store(tmp_path / "hc.sqlite")

    class Publisher:
        submit = staticmethod(messages.append)

    selector = Selection(store, Publisher())
    return retained, snapshot, basis, worker, clock, states, local, store, selector, messages


def test_hems_choice_is_persisted_and_acknowledged_without_execution(tmp_path):
    retained, snapshot, basis, worker, clock, states, local, store, selector, messages = setup(
        tmp_path
    )
    before = retained._load_payload()
    now = clock[0].timestamp()
    selector.tick(states, local, now, True)
    first = copy.deepcopy(messages[-1])
    assert first["state"] == "confirmed"
    assert first["attributes"]["selected_plan_id"] == "hold"
    assert "target" not in first["attributes"]
    selector.tick(states, local, now + 30, True)
    assert messages[-1] == first
    worker.refresh(snapshot, basis)
    assert worker.confirmed_selection == first["attributes"]
    assert worker.confirmed_selection["execution_authorized"] is False
    assert retained._load_payload() == before
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM hc_energy_selection").fetchone()[0] == 1
    assert Selection(store, selector.publisher).view(now)["status"] == "waiting"
    clock[0] += timedelta(seconds=121)
    worker.refresh(snapshot, basis)
    assert worker.confirmed_selection is None
    assert selector.view(now + 121)["status"] == "waiting"
    local.pending = None
    selector.tick(states, local, now + 121, True)
    assert messages[-1]["state"] == "withdrawn"


@pytest.mark.parametrize(
    "fault", ["fingerprint", "choice", "execution", "local", "withdrawn", "connection"]
)
def test_invalid_or_unmatched_choices_are_not_confirmed(tmp_path, fault):
    _, _, _, _, clock, states, local, _, selector, messages = setup(tmp_path)
    answer = states[RESPONSE_ENTITY]["attributes"]
    if fault == "fingerprint":
        answer["request_fingerprint"] = "bad"
    if fault == "choice":
        answer["selected_plan_id"] = "unknown"
    if fault == "execution":
        answer["execution_authorized"] = True
    if fault == "local":
        local.local["candidates"] = []
    if fault == "withdrawn":
        states[REQUEST_ENTITY]["state"] = "withdrawn"
    selector.tick(states, local, clock[0].timestamp(), fault != "connection")
    assert messages[-1]["state"] == "withdrawn"


def test_hems_rejects_modified_or_expired_confirmation(tmp_path):
    _, _, _, worker, clock, states, local, _, selector, messages = setup(tmp_path)
    selector.tick(states, local, clock[0].timestamp(), True)
    value = messages[-1]["attributes"]
    for field, bad in [
        ("selected_plan_id", "other"),
        ("request_fingerprint", "bad"),
        ("execution_authorized", True),
        ("revision", 999),
    ]:
        assert (
            validate_selection(
                dict(value, **{field: bad}), local.pending, worker.last_answer, clock[0]
            )
            is None
        )
    assert (
        validate_selection(
            value, local.pending, worker.last_answer, clock[0] + timedelta(seconds=120)
        )
        is None
    )


def test_cancelled_or_expiring_during_read_cannot_be_confirmed(tmp_path):
    _, _, _, worker, clock, states, local, _, selector, _ = setup(tmp_path)
    selector.tick(states, local, clock[0].timestamp(), True)
    worker.read = lambda: None
    worker.confirm_selection(local.pending)
    assert worker.confirmed_selection is None

    def slow_read():
        clock[0] += timedelta(seconds=121)
        return local.pending

    worker.read = slow_read
    worker.confirm_selection(local.pending)
    assert worker.confirmed_selection is None


def test_confirmation_is_read_between_minute_outlook_updates(tmp_path, monkeypatch):
    from picot.v2.energy_outlook_runtime import EnergyOutlookPublisher

    _, snapshot, basis, advisor, clock, states, local, _, selector, _ = setup(tmp_path)
    published, reads = [], []
    original = advisor.read_selection

    def read_selection():
        reads.append(clock[0])
        return original()

    advisor.read_selection = read_selection

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("picot.v2.energy_outlook_runtime.Thread", ImmediateThread)
    publisher = EnergyOutlookPublisher(
        published.append,
        lambda s: inputs()["conversion_model"],
        now=lambda: clock[0],
        portfolio=advisor,
    )
    publisher.submit(snapshot, replacement_basis=basis)
    clock[0] += timedelta(seconds=30)
    selector.tick(states, local, clock[0].timestamp(), True)
    publisher.submit(snapshot, replacement_basis=basis)
    assert advisor.confirmed_selection is not None
    assert len(published) == 1
    count = len(reads)
    publisher.submit(snapshot, replacement_basis=basis)
    assert len(reads) == count


def test_start_permit_requires_confirmed_choice_and_keeps_original_expiry(tmp_path):
    _, snapshot, basis, worker, clock, states, local, _, selector, _ = setup(tmp_path)
    permits = []
    worker.publish_permit = permits.append
    worker.poll_selection()
    assert permits[-1]["state"] == "withdrawn"
    selector.tick(states, local, clock[0].timestamp(), True)
    worker.poll_selection()
    first = copy.deepcopy(permits[-1])
    assert first["state"] == "permitted"
    assert first["attributes"]["execution_authorized"] is True
    assert first["attributes"]["contract"] == "hc-energy-start-permit:v1"
    assert first["attributes"]["valid_until"] == selector.current["message"]["valid_until"]
    assert worker.last_answer["execution_authorized"] is False
    clock[0] += timedelta(seconds=30)
    worker.refresh(snapshot, basis)
    assert permits[-1] == first
    clock[0] += timedelta(seconds=91)
    worker.poll_selection()
    assert permits[-1]["state"] == "withdrawn"


def test_cancelled_request_withdraws_start_permit(tmp_path):
    _, _, _, worker, clock, states, local, _, selector, _ = setup(tmp_path)
    permits = []
    worker.publish_permit = permits.append
    selector.tick(states, local, clock[0].timestamp(), True)
    worker.poll_selection()
    assert permits[-1]["state"] == "permitted"
    worker.read = lambda: None
    worker.poll_selection()
    assert permits[-1]["state"] == "withdrawn"
