import copy
from datetime import UTC, datetime

from picot_hc.core import Store
from picot_hc.energy_model import EnergyModel, context
from picot_hc.energy_proposals import ProposalPublisher, Proposals

NOW = 1792692000.0


def sample(seconds=0, watts=600):
    return dict(
        source_id="a" * 64,
        identity="sensors/fan:auto",
        target=20,
        indoor=20,
        outdoor=10,
        power_w=watts,
        energy_wh=10000 + seconds * watts / 3600,
    )


def train(model, now=NOW, watts=600):
    for minute in range(63):
        model.observe(sample(minute * 60, watts), now - 3720 + minute * 60)


def inputs(now=NOW):
    view = dict(
        revision=2,
        settings=dict(enabled=True, learning_enabled=True),
        current=dict(target=20, minimum=19, maximum=21, ends_at=now + 7200),
    )
    plan = dict(enabled=True, preheating=False, learning_status=dict(phase="comfort"))
    outlook = dict(
        status="ready",
        snapshot_id="snapshot",
        generated_at=now,
        valid_until=now + 180,
        replacement_basis=dict(
            source_id="a" * 64, basis_id="b" * 64, starts_at=now, ends_at=now + 7200
        ),
    )
    return view, plan, outlook


def test_meter_sessions_persist_and_need_three_disjoint_periods(tmp_path):
    store = Store(tmp_path / "hc.sqlite")
    model = EnergyModel(store)
    for minute in range(42):
        model.observe(sample(minute * 60), NOW - 3720 + minute * 60)
    assert model.estimate(sample(), NOW)["power_w"] is None
    for minute in range(42, 63):
        model.observe(sample(minute * 60), NOW - 3720 + minute * 60)
    assert model.estimate(sample(), NOW) == dict(
        samples=3, power_w=750, method="measured_steady_heat_upper_margin", margin_fraction=0.25
    )
    restored = EnergyModel(store)
    assert restored.session is None
    assert restored.estimate(sample(), NOW)["samples"] == 3
    assert restored.estimate(dict(sample(), outdoor=14), NOW)["power_w"] is None
    assert restored.estimate(dict(sample(), identity="other-fan"), NOW)["power_w"] is None


def test_counter_reset_gap_drift_and_disagreement_do_not_train(tmp_path):
    for kind in ("reset", "gap", "drift", "disagreement"):
        model = EnergyModel(Store(tmp_path / (kind + ".sqlite")))
        for minute in range(21):
            s = sample(minute * 60)
            time = NOW + minute * 60
            if kind == "reset" and minute >= 10:
                s["energy_wh"] -= 9000
            if kind == "gap" and minute >= 10:
                time += 180
            if kind == "drift":
                s["indoor"] += minute * 0.03
            if kind == "disagreement":
                s["power_w"] = 200
            model.observe(s, time)
        assert model.records == []


def test_generated_request_is_bounded_persisted_and_withdrawn_on_manual_change(tmp_path):
    store = Store(tmp_path / "hc.sqlite")
    sent = []

    class Publisher:
        submit = staticmethod(lambda value: sent.append(copy.deepcopy(value)))

    generator = Proposals(store, Publisher())
    train(generator.model)
    view, plan, outlook = inputs()
    generator.tick(sample(3780), view, plan, outlook, NOW)
    request = sent[-1]["attributes"]
    assert sent[-1]["state"] == "requested"
    # 750 W for the remaining 118 minutes of this comfort window.
    assert request["plans"][0]["slots"][0]["energy_wh"] == 1475
    assert set(request["plans"][0]) == {"plan_id", "non_electric_cost_eur", "slots"}
    assert "beneden" not in str(request)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM hc_energy_proposals").fetchone()[0] == 1
    generator.tick(sample(3840), view, plan, outlook, NOW + 30)
    assert sent[-1]["attributes"]["request_id"] == request["request_id"]
    # Unknown/mixed/manual conditions revoke the request without a climate command.
    generator.tick(None, view, plan, outlook, NOW + 60)
    assert sent[-1]["state"] == "withdrawn"
    generator.tick(sample(3900), view, plan, outlook, NOW + 61)
    assert sent[-1]["state"] == "withdrawn"  # At most one proposal per published basis.


def test_no_proposal_without_schema_learning_matching_basis_and_time(tmp_path):
    class Publisher:
        def __init__(self):
            self.sent = []

        def submit(self, value):
            self.sent.append(value)

    for change in ("schema", "learning", "basis", "short_window", "old_basis", "preheat"):
        publisher = Publisher()
        generator = Proposals(Store(tmp_path / (change + ".sqlite")), publisher)
        train(generator.model)
        view, plan, outlook = inputs()
        if change == "schema":
            view["settings"]["enabled"] = False
        if change == "learning":
            view["settings"]["learning_enabled"] = False
        if change == "basis":
            outlook["replacement_basis"]["source_id"] = "c" * 64
        if change == "short_window":
            view["current"]["ends_at"] = NOW + 300
        if change == "old_basis":
            outlook["generated_at"] = NOW - 90
        if change == "preheat":
            plan["preheating"] = True
        generator.tick(sample(3780), view, plan, outlook, NOW)
        assert publisher.sent[-1]["state"] == "withdrawn", change


def test_context_requires_fresh_dedicated_meter_and_cv_off():
    config = dict(zones=[dict(id="beneden", energy="sensor.energy")])
    states = {
        "sensor.energy": dict(
            state="10",
            last_reported=datetime.fromtimestamp(NOW, UTC).isoformat(),
            attributes={"unit_of_measurement": "kWh"},
        )
    }
    plan = dict(
        enabled=True,
        desired=dict(beneden=20),
        owned=dict(beneden=dict(released=False)),
        learning_context=dict(valid=True, indoor=20, outdoor=10, identity="fan"),
        sources=dict(
            beneden=dict(state="heat", temperature=20, available=True, pending=False),
            cv=dict(state="off", available=True, pending=False),
        ),
    )
    meter = dict(status="available", power_w=600, source_id="a" * 64)
    assert context(config, states, plan, meter, NOW)["energy_wh"] == 10000
    plan["learning_context"]["indoor"] = 18
    assert context(config, states, plan, meter, NOW) is None
    assert context(config, states, plan, meter, NOW, steady=False)["indoor"] == 18
    plan["sources"]["cv"]["state"] = "heat"
    assert context(config, states, plan, meter, NOW, steady=False) is None
    assert context(config, states, plan, meter, NOW) is None
    plan["sources"]["cv"]["state"] = "off"
    plan["learning_context"]["indoor"] = 20
    assert context(config, states, plan, meter, NOW + 91, steady=False) is None
    assert context(config, states, plan, meter, NOW + 91) is None
    plan["sources"]["beneden"]["pending"] = True
    assert context(config, states, plan, meter, NOW) is None


def test_publisher_keeps_only_latest_queued_value_and_recovers_after_failure(monkeypatch):
    import picot_hc.energy_proposals as module

    queued, calls = [], []

    class Thread:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            queued.append(self.target)

    monkeypatch.setattr(module, "Thread", Thread)

    def send(url, token, path, payload):
        calls.append((path, payload))
        if len(calls) == 1:
            raise OSError("offline")

    monkeypatch.setattr(module, "ha_request", send)
    publisher = ProposalPublisher("http://fake/api", "test")
    publisher.submit(dict(state="requested", attributes=dict(request_id="one")))
    publisher.submit(dict(state="withdrawn", attributes={}))
    assert len(queued) == 1
    queued.pop()()
    assert calls[0][1]["state"] == "withdrawn"
    assert not publisher.running
    publisher.submit(dict(state="withdrawn", attributes={}))
    queued.pop()()
    assert len(calls) == 2
    publisher.submit(dict(state="withdrawn", attributes={}))
    assert queued == []
