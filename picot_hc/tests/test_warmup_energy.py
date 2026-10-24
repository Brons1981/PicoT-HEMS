import pytest
from picot_hc.core import Store
from picot_hc.warmup_energy import WarmupEnergy
from test_energy_proposals import NOW, sample


def inputs(deadline):
    return (
        dict(
            revision=1,
            settings=dict(enabled=True, learning_enabled=True),
            next=dict(starts_at=deadline, target=20),
            current=None,
        ),
        dict(enabled=True, preheating=True, learning_status=dict(phase="preheat")),
    )


def run(model, start, *, fault=None):
    view, plan = inputs(start + 3600)
    for minute in range(33):
        s = dict(sample(minute * 60, 1200), indoor=min(20, 18 + minute / 15))
        if fault == "counter":
            s["power_w"] = 100
        if fault == "source" and minute >= 15:
            s["identity"] = "other"
        if fault == "gap" and minute == 15:
            s = None
        if fault == "schema" and minute >= 15:
            view["revision"] = 2
        if fault == "reset" and minute >= 15:
            s["energy_wh"] -= 9000
        if fault == "weather" and minute >= 15:
            s["outdoor"] = 14
        model.observe(s, view, plan, start + minute * 60)


def test_measured_warmups_require_matching_evidence_and_survive_restart(tmp_path):
    store = Store(tmp_path / "hc.sqlite")
    model = WarmupEnergy(store)
    run(model, NOW - 3 * 86400)
    run(model, NOW - 2 * 86400)
    query = dict(sample(), indoor=18)
    assert model.estimate(query, NOW)["energy_wh"] is None
    run(model, NOW - 86400)
    estimate = model.estimate(query, NOW)
    # 32 minutes at 1.2 kW = 640 Wh; conservative margin 25%.
    assert estimate["energy_wh"] == pytest.approx(800)
    assert estimate["duration_seconds"] == 2400
    restored = WarmupEnergy(store)
    assert restored.session is None
    assert restored.estimate(query, NOW) == estimate
    for changed in (
        dict(query, indoor=17),
        dict(query, outdoor=14),
        dict(query, identity="other"),
        dict(query, target=21),
    ):
        assert restored.estimate(changed, NOW)["energy_wh"] is None
    assert restored.estimate(query, NOW + 8 * 86400)["energy_wh"] is None


@pytest.mark.parametrize("fault", ["counter", "source", "gap", "schema", "reset", "weather"])
def test_interrupted_or_contaminated_warmup_cannot_become_complete(tmp_path, fault):
    model = WarmupEnergy(Store(tmp_path / "hc.sqlite"))
    run(model, NOW, fault=fault)
    assert model.records == []


def test_disabled_learning_and_incomplete_restart_do_not_train(tmp_path):
    store = Store(tmp_path / "hc.sqlite")
    model = WarmupEnergy(store)
    view, plan = inputs(NOW + 3600)
    model.observe(dict(sample(), indoor=18), view, plan, NOW)
    restored = WarmupEnergy(store)
    restored.observe(dict(sample(60), indoor=18.2), view, plan, NOW + 60)
    assert restored.session is None
    assert restored.records == []
    view["settings"]["learning_enabled"] = False
    model.observe(dict(sample(60), indoor=19), view, plan, NOW + 60)
    assert model.session is None
    assert model.records == []


def test_completion_across_comfort_boundary_is_one_measurement(tmp_path):
    model = WarmupEnergy(Store(tmp_path / "hc.sqlite"))
    view, plan = inputs(NOW + 1800)
    for minute in range(35):
        if minute == 30:
            view["current"], view["next"] = view["next"], None
            plan.update(preheating=False, learning_status=dict(phase="comfort"))
        model.observe(
            dict(sample(minute * 60, 1200), indoor=min(20, 18 + minute / 15)),
            view,
            plan,
            NOW + minute * 60,
        )
    assert len(model.records) == 1
    assert model.records[0]["used_wh"] == pytest.approx(640)
