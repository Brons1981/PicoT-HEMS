import pytest
from picot_hc.core import Store
from picot_hc.cv_auxiliary import assumptions, estimate
from picot_hc.cv_warmup import CvWarmupEvidence
from test_cv_warmup import NOW, run


def config():
    return dict(
        cv_auxiliary_mode="estimated",
        cv_auxiliary_running_w=100,
        cv_auxiliary_postrun_w=50,
        cv_auxiliary_postrun_seconds=300,
    )


def test_auxiliary_estimate_separates_running_and_single_future_tail():
    result = estimate(assumptions(config()), 3600)
    assert result["energy_wh"] == 100
    assert result["postrun_energy_wh"] == pytest.approx(50 / 12)
    assert result["total_energy_if_stopped_wh"] == pytest.approx(100 + 50 / 12)
    assert result["measured"] is False
    assert result["forecast_eligible"] is False
    assert result["postrun_included_in_energy_wh"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("cv_auxiliary_mode", "measured"),
        ("cv_auxiliary_running_w", 0),
        ("cv_auxiliary_running_w", True),
        ("cv_auxiliary_running_w", float("nan")),
        ("cv_auxiliary_running_w", 2001),
        ("cv_auxiliary_postrun_w", -1),
        ("cv_auxiliary_postrun_seconds", 3601),
        ("cv_power", "sensor.cv"),
        ("cv_energy", "sensor.cv"),
    ],
)
def test_invalid_or_meter_configuration_does_not_silently_estimate(field, value):
    options = config()
    options[field] = value
    assert assumptions(options) is None
    assert estimate(assumptions(options), 3600)["status"] == "unavailable"


def test_old_configuration_requires_explicit_estimated_mode():
    assert assumptions({}) is None
    assert estimate(assumptions(config()), -1)["status"] == "unavailable"


@pytest.mark.parametrize("changed", [False, True])
def test_full_cv_session_stores_assumptions_without_fabricating_measurement(tmp_path, changed):
    def parameters(minute):
        settings = config()
        if changed and minute == 5:
            settings["cv_auxiliary_running_w"] = 200
        return assumptions(settings)

    model = run(CvWarmupEvidence(Store(tmp_path / "hc.sqlite")), auxiliary=parameters)
    record = model.view(NOW + 1500)["latest"]
    assert record["electricity_measured"] is False
    assert record["comparison_eligible"] is False
    value = record["electricity"]
    if changed:
        assert value["status"] == "incomplete_or_unavailable"
    else:
        assert value["status"] == "estimated"
        assert value["energy_wh"] == pytest.approx(100 * 25 / 60)
        assert value["postrun_energy_wh"] == pytest.approx(50 / 12)
        assert value["assumptions"] == parameters(0)
    assert CvWarmupEvidence(model.store).view(NOW + 1500)["latest"] == record
