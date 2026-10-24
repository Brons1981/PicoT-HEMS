import copy

import pytest
from picot_hc.core import Store
from picot_hc.energy_proposals import Proposals
from picot_hc.warmup_energy import WarmupEnergy
from test_energy_proposals import NOW, inputs, sample


def setup(tmp_path, now=NOW):
    sent = []

    class Publisher:
        submit = staticmethod(lambda value: sent.append(copy.deepcopy(value)))

    store = Store(tmp_path / "hc.sqlite")
    generator, warmup = Proposals(store, Publisher()), WarmupEnergy(store)
    # Real observations: three complete runs and three steady periods per target.
    runs = sorted(
        (now - 86400 * (day + 1) - (target - 19) * 7200, target)
        for target in (19.5, 20, 20.5)
        for day in range(3)
    )
    for start, target in runs:
        window = dict(starts_at=start + 3600, target=target)
        view = dict(revision=1, settings=dict(enabled=True, learning_enabled=True), next=window)
        plan = dict(enabled=True, preheating=True, learning_status=dict(phase="preheat"))
        for minute in range(33):
            s = dict(
                sample(minute * 60, 1200),
                target=target,
                indoor=min(target, 18 + (target - 18) * minute / 30),
            )
            warmup.observe(s, view, plan, start + minute * 60)
        for minute in range(21):
            generator.model.observe(
                dict(sample(minute * 60), target=target, indoor=target), start + 2000 + minute * 60
            )
    view, plan, outlook = inputs(now)
    view.update(
        current=None,
        next=dict(
            starts_at=now + 3600, ends_at=now + 10800, minimum=19, maximum=21, target=20, hard=False
        ),
    )
    plan.update(
        preheating=True,
        learning_status=dict(phase="preheat"),
        sources=dict(beneden=dict(temperature_supported=True, minimum=16, maximum=30, step=0.5)),
    )
    return generator, warmup, view, plan, outlook, sent


def test_batch_contains_measured_comfort_variants_same_window_and_no_device_data(tmp_path):
    generator, warmup, view, plan, outlook, sent = setup(tmp_path)
    current = dict(sample(), indoor=18)
    generator.tick(None, view, plan, outlook, NOW, warmup=warmup, warmup_sample=current)
    assert sent[-1]["state"] == "requested"
    request = sent[-1]["attributes"]
    assert len(request["plans"]) == 3
    assert generator.view(NOW)["targets"] == [20, 19.5, 20.5]
    for candidate in request["plans"]:
        assert len(candidate["slots"]) == 2
        assert candidate["slots"][0]["energy_wh"] == pytest.approx(800)
        # Hold through the available HEMS horizon, beyond the old 15-minute prefix.
        assert candidate["slots"][1]["energy_wh"] == pytest.approx(975)
        assert candidate["slots"][0]["ends_at"] == candidate["slots"][1]["starts_at"]
    assert "target" not in str(request) and "beneden" not in str(request)
    generator.tick(None, view, plan, outlook, NOW + 30, warmup=warmup, warmup_sample=current)
    assert sent[-1]["attributes"]["request_id"] == request["request_id"]
    generator.tick(None, view, plan, outlook, NOW + 60, warmup=warmup, warmup_sample=None)
    assert sent[-1]["state"] == "withdrawn"


@pytest.mark.parametrize("case", ["hard", "step", "deadline", "missing", "schema", "basis"])
def test_bounds_and_missing_evidence_control_which_candidates_are_offered(tmp_path, case):
    generator, warmup, view, plan, outlook, sent = setup(tmp_path)
    expected = 0
    if case == "hard":
        view["next"]["hard"] = True
        expected = 1
    if case == "step":
        plan["sources"]["beneden"]["step"] = 1
        expected = 1
    if case == "deadline":
        view["next"]["starts_at"] = NOW + 1200
    if case == "missing":
        generator.model.records = []
    if case == "schema":
        view["settings"]["enabled"] = False
    if case == "basis":
        outlook["replacement_basis"]["source_id"] = "b" * 64
    generator.tick(
        None, view, plan, outlook, NOW, warmup=warmup, warmup_sample=dict(sample(), indoor=18)
    )
    if expected:
        assert len(sent[-1]["attributes"]["plans"]) == expected
    else:
        assert sent[-1]["state"] == "withdrawn"
