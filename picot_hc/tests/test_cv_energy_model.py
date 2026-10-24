import copy

import pytest
from picot_hc.core import Store
from picot_hc.cv_auxiliary import assumptions
from picot_hc.cv_energy_model import estimate
from picot_hc.cv_warmup import CvWarmupEvidence
from test_cv_auxiliary import config
from test_cv_warmup import NOW, run


def evidence(tmp_path):
    model = run(
        CvWarmupEvidence(Store(tmp_path / "hc.sqlite")),
        auxiliary=lambda _: assumptions(config()),
        gas_screening=lambda _: dict(status="available", identity="dhw", active=False),
    )
    for second in (1530, 1560, 1590):
        model.screen(dict(status="available", identity="dhw", active=False), NOW + second)
    original = model.records[0]
    records = []
    for day in range(3):
        record = copy.deepcopy(original)
        record["command_id"] = f"run-{day}"
        for key in (
            "start",
            "measured_at",
            "stable_at",
            "gas_start_reported_at",
            "gas_end_reported_at",
        ):
            record[key] -= day * 86400
        for key in ("checked_at", "review_until"):
            record["gas_screening"][key] -= day * 86400
        records.append(record)
    sample = dict(
        indoor=18,
        outdoor=10,
        target=20,
        identity="same",
        auxiliary_assumptions=assumptions(config()),
        gas_screening=dict(status="available", identity="dhw", active=False),
    )
    return model, records, sample


def test_screened_estimate_includes_stability_and_one_separate_tail(tmp_path):
    model, records, sample = evidence(tmp_path)
    model.save(records, [])
    loaded = CvWarmupEvidence(model.store)
    value = estimate(loaded.records, sample, NOW + 1600, gas_price=1.4)
    assert value["status"] == "estimated"
    assert value["samples"] == 3
    assert value["gas_m3"] == pytest.approx(0.625)
    assert value["gas_cost_eur"] == pytest.approx(0.875)
    # 25 minutes including the final gas report, with 25% margin.
    assert value["duration_seconds"] == 1875
    assert value["electricity"]["energy_wh"] == pytest.approx(100 * 1875 / 3600)
    assert value["electricity"]["postrun_energy_wh"] == pytest.approx(50 * 300 / 3600)
    assert value["heating_only_confirmed"] is False
    assert value["comparison_eligible"] is False
    assert value["execution_authorized"] is False
    shown = loaded.view(NOW + 1600, sample, gas_price=1.4)
    assert shown["energy_estimate"] == value
    assert shown["comparison_eligible"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "pending",
        "dhw",
        "gap",
        "restart",
        "old_counter",
        "future_counter",
        "duplicate",
        "old",
        "future",
        "identity",
        "dhw_identity",
        "outdoor",
        "target",
        "indoor",
        "assumptions",
        "nan",
        "review_time",
        "incomplete_end",
    ],
)
def test_bad_or_unmatched_session_cannot_complete_three_run_evidence(tmp_path, fault):
    _, records, sample = evidence(tmp_path)
    record = records[0]
    if fault == "pending":
        record["gas_screening"]["provisional"] = True
    elif fault == "dhw":
        record["gas_screening"]["status"] = "dhw_observed"
    elif fault == "gap":
        record["gas_screening"]["polling_complete"] = False
    elif fault == "restart":
        record["gas_screening"]["status"] = "incomplete"
    elif fault == "old_counter":
        record["gas_start_reported_at"] -= 61
    elif fault == "future_counter":
        record["gas_start_reported_at"] += 1
    elif fault == "duplicate":
        record["command_id"] = records[1]["command_id"]
    elif fault == "old":
        record["measured_at"] -= 8 * 86400
    elif fault == "future":
        record["measured_at"] = NOW + 1601
    elif fault == "identity":
        record["identity"] = "other"
    elif fault == "dhw_identity":
        record["gas_screening"]["identity"] = "different-dhw-sensor"
    elif fault in ("outdoor", "target", "indoor"):
        record[fault] += 2
    elif fault == "assumptions":
        record["electricity"]["assumptions"]["running_power_w"] = 200
    elif fault == "nan":
        record["household_gas_delta_m3"] = float("nan")
    elif fault == "review_time":
        record["gas_screening"]["checked_at"] = record["measured_at"] + 89
    else:
        record["gas_end_reported_at"] = record["stable_at"] - 1
    value = estimate(records, sample, NOW + 1600, gas_price=1.4)
    assert value["status"] == "collecting"
    assert value["gas_m3"] is None


@pytest.mark.parametrize("price", [None, -1, True, float("nan"), float("inf")])
def test_invalid_price_does_not_make_gas_free(tmp_path, price):
    _, records, sample = evidence(tmp_path)
    value = estimate(records, sample, NOW + 1600, gas_price=price)
    assert value["status"] == "estimated"
    assert value["gas_cost_eur"] is None
