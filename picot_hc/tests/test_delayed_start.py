import copy

import pytest
from picot_hc.core import Store
from picot_hc.delayed_start import StandbyEvidence, candidates
from picot_hc.energy_model import EnergyModel
from picot_hc.startup_energy import StartupEnergy
from test_energy_proposals import NOW, sample, train
from test_startup_energy import run


def evidence(tmp_path, now=NOW):
    store = Store(tmp_path / "hc.sqlite")
    startup, steady, standby = StartupEnergy(store), EnergyModel(store), StandbyEvidence()
    for day in (3, 2, 1):
        run(startup, now - day * 86400)
    train(steady, now)
    s = dict(sample(), indoor=18, power_w=10)
    for minute in range(16):
        standby.observe(dict(s, energy_wh=10000 + minute / 6), now - 900 + minute * 60)
    view = dict(
        revision=1,
        settings=dict(enabled=True, learning_enabled=True),
        current=None,
        next=dict(
            starts_at=now + 5400, ends_at=now + 18000, target=20, minimum=19, maximum=21, hard=True
        ),
    )
    plan = dict(
        enabled=True,
        preheating=False,
        desired={},
        zones=dict(beneden=dict(target=17)),
        learning_status=dict(phase="fixed", cooling_rate=0.2, cooling_samples=3),
        sources=dict(
            beneden=dict(
                state="off",
                pending=False,
                available=True,
                temperature_supported=True,
                minimum=16,
                maximum=30,
                step=0.5,
            ),
            cv=dict(state="off", pending=False, available=True),
        ),
    )
    return startup, steady, standby, s, view, plan


def test_start_times_include_waiting_full_start_and_holding(tmp_path):
    startup, steady, standby, s, view, plan = evidence(tmp_path)
    options = candidates(
        s, view, plan, startup.model, steady, standby.estimate(NOW), NOW, NOW + 900, NOW + 6300
    )
    assert [p["heat_starts_at"] - NOW for p in options] == [900, 1800, 2700]
    for p in options:
        assert p["reaches_at"] <= view["next"]["starts_at"]
        assert p["slots"][0]["starts_at"] == NOW + 900
        assert p["slots"][-1]["ends_at"] == NOW + 6300
        for left, right in zip(p["slots"], p["slots"][1:], strict=False):
            assert left["ends_at"] == right["starts_at"]
    assert options[1]["slots"][0]["energy_wh"] == pytest.approx(3.625)
    assert options[1]["slots"][1]["energy_wh"] == pytest.approx(818.75)
    assert options[1]["slots"][2]["energy_wh"] == pytest.approx(406.25)


@pytest.mark.parametrize("case", ["floor", "cooling", "startup", "standby", "active", "pending"])
def test_incomplete_evidence_or_unsafe_waiting_blocks_candidates(tmp_path, case):
    startup, steady, standby, s, view, plan = evidence(tmp_path)
    if case == "floor":
        plan["zones"]["beneden"]["target"] = 18
    if case == "cooling":
        plan["learning_status"]["cooling_rate"] = None
    if case == "startup":
        startup.model.records = []
    if case == "standby":
        standby.observe(None, NOW)
    if case == "active":
        plan["sources"]["beneden"]["state"] = "heat"
    if case == "pending":
        plan["sources"]["beneden"]["pending"] = True
    assert (
        candidates(
            s, view, plan, startup.model, steady, standby.estimate(NOW), NOW, NOW + 900, NOW + 6300
        )
        == []
    )


def test_standby_requires_continuous_consistent_measured_energy():
    model = StandbyEvidence()
    s = dict(sample(), power_w=10)
    for minute in range(16):
        model.observe(dict(s, energy_wh=10000 + minute / 6), NOW - 900 + minute * 60)
    assert model.estimate(NOW) == pytest.approx(14.5)
    assert model.estimate(NOW + 91) is None
    broken = copy.deepcopy(s)
    broken["energy_wh"] = 0
    model.observe(broken, NOW + 30)
    assert model.estimate(NOW + 30) is None
