import pytest
from picot_hc.core import Store
from picot_hc.cv_auxiliary import assumptions
from picot_hc.cv_maintenance import CvMaintenance
from picot_hc.cv_warmup import CvWarmupEvidence
from test_cv_auxiliary import config
from test_cv_warmup import NOW


def collect(model, offset=0, fault=None):
    view = dict(
        revision=1, settings=dict(enabled=True, learning_enabled=True), current=dict(target=20)
    )
    plan = dict(
        enabled=True,
        owned=dict(cv=dict(command="c")),
        desired=dict(cv=20),
        sources=dict(cv=dict(state="heat", temperature=20, pending=False)),
    )
    commands = [dict(id="c", source="cv", field="heating", status="confirmed", origin="schedule")]
    for second in range(0, 1321, 30):
        now = NOW + offset + second
        screen = dict(status="available", identity="dhw", active=False)
        if fault == "dhw" and second == 1260:
            screen["active"] = True
        model.evidence.screen(screen, now)
        sample = dict(
            identity="same",
            indoor=20,
            outdoor=10,
            target=20,
            gas_m3=100 + second / 7200,
            gas_reported_at=now,
            gas_screening=screen,
            auxiliary_assumptions=assumptions(config()),
        )
        if second == 600:
            if fault == "gap":
                sample = None
            elif fault == "counter":
                sample["gas_m3"] = 99
            elif fault == "temperature":
                sample["indoor"] = 19
            elif fault == "revision":
                view["revision"] = 2
            elif fault == "restart":
                model = CvMaintenance(model.evidence.store)
            elif fault == "manual":
                commands[0]["origin"] = "manual"
        model.observe(sample, view, plan, commands, now)
    return model, sample


def test_three_disjoint_reviewed_sessions_form_rate_and_survive_restart(tmp_path):
    model = CvMaintenance(Store(tmp_path / "hc.sqlite"))
    for offset in (0, 1800, 3600):
        model, sample = collect(model, offset)
    loaded = CvMaintenance(model.evidence.store)
    value = loaded.estimate(sample, NOW + 4920)
    assert value["samples"] == 3
    assert value["gas_m3_per_hour"] == pytest.approx(0.625)
    assert value["power_w"] == 125
    assert value["execution_authorized"] is False
    assert loaded.session is None
    assert CvWarmupEvidence(model.evidence.store).records == []


@pytest.mark.parametrize(
    "fault", ["gap", "counter", "temperature", "revision", "restart", "manual", "dhw"]
)
def test_invalid_period_or_late_dhw_cannot_support_a_plan(tmp_path, fault):
    model, sample = collect(CvMaintenance(Store(tmp_path / "hc.sqlite")), fault=fault)
    assert model.estimate(sample, NOW + 1320)["samples"] == 0


def test_pending_review_is_not_counted_and_no_data_is_not_zero(tmp_path):
    model, sample = collect(CvMaintenance(Store(tmp_path / "hc.sqlite")))
    record = model.evidence.records[0]
    record["gas_screening"]["provisional"] = True
    assert model.estimate(sample, NOW + 1320)["samples"] == 0
    assert model.estimate(None, NOW + 1320)["gas_m3_per_hour"] is None
