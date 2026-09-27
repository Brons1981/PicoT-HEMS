from dataclasses import replace
from datetime import timedelta

import pytest
from test_financial_result_ledger import _history

from picot.v2.financial_measurement_inference import infer_financial_measurements
from picot.v2.financial_result_metrics import financial_measurement_coverage
from picot.v2.power_history import PowerHistoryPoint
from picot.v2.review_alignment import _integrals


def _quarter_history(*, variable_pv=True):
    history = _history(pv_generation=1600, household_load=400, grid_import=0,
                       grid_export=0, battery_charge=1000, battery_discharge=0)
    series = []
    for source in history.series:
        points = list(source.points)
        if source.role == "pv_generation" and variable_pv:
            points[1:1] = [PowerHistoryPoint(history.starts_at + timedelta(minutes=m), w,
                                            f"pv-{m}") for m, w in ((2, 800), (8, 1600))]
        if source.role == "household_load":
            points[1:1] = [PowerHistoryPoint(history.starts_at + timedelta(minutes=m), w,
                                            f"load-{m}")
                           for m, w in ((2, float("nan")), (8, 400))]
        series.append(replace(source, points=tuple(points)))
    return replace(history, series=tuple(series))


def _infer(history):
    return infer_financial_measurements(history, pv_maximum_power_w=4200,
        charge_maximum_power_w=2400, discharge_maximum_power_w=2400)


def test_valid_whole_quarter_recovers_negative_subinterval_without_double_counting():
    history = _quarter_history()
    before = repr(history)
    result = _infer(history)
    assert result.inferred_roles == {"household_load"}
    load = next(s for s in result.history.series if s.role == "household_load")
    bounds = [history.starts_at + timedelta(minutes=m) for m in (0, 15, 30)]
    energy, errors = _integrals(load, bounds)
    # Independent arithmetic: PV 1600 W * 9 min + 800 W * 6 min = 320 Wh.
    # Charging 1000 W * 15 min = 250 Wh; the whole household quarter is 70 Wh.
    assert energy == pytest.approx([70, 100])
    assert errors == [None, None]
    assert len(result.inferences) == 1
    assert result.inferences[0]["energy_wh"] == pytest.approx(70)
    assert result.inferences[0]["starts_at"] == bounds[0].isoformat()
    assert result.inferences[0]["ends_at"] == bounds[1].isoformat()
    assert repr(history) == before
    assert not financial_measurement_coverage(result.history)["household_load"]["gap_count"]


def test_two_holes_in_one_quarter_use_the_balance_once():
    h = _quarter_history()
    h = replace(h, series=tuple(replace(s, points=(s.points[0], *(
        PowerHistoryPoint(h.starts_at + timedelta(minutes=m), value, f"hole-{m}")
        for m, value in ((2, float("nan")), (4, 400), (6, float("nan")), (8, 400))
    ), s.points[-1])) if s.role == "household_load" else s for s in h.series))
    result = _infer(h)
    assert len(result.inferences) == 1
    assert result.inferences[0]["energy_wh"] == pytest.approx(70)


@pytest.mark.parametrize("fault", ["negative_quarter", "grid_gap_outside_hole", "open_quarter"])
def test_whole_quarter_requires_complete_nonnegative_closed_evidence(fault):
    h = _quarter_history(variable_pv=False)
    if fault == "negative_quarter":
        h = replace(h, series=tuple(replace(s, points=tuple(replace(p, power_w=500)
            for p in s.points)) if s.role == "pv_generation" else s for s in h.series))
    elif fault == "grid_gap_outside_hole":
        h = replace(h, series=tuple(replace(s, points=(s.points[0],
            PowerHistoryPoint(h.starts_at + timedelta(minutes=1), float("nan"), "grid-out"),
            PowerHistoryPoint(h.starts_at + timedelta(minutes=1, seconds=30), 0, "grid-back"),
            s.points[-1])) if s.role == "grid_import" else s for s in h.series))
    else:
        end = h.starts_at + timedelta(minutes=10)
        h = replace(h, ends_at=end, series=tuple(replace(s, points=tuple(
            p for p in s.points if p.sampled_at <= end)) for s in h.series))
    result = _infer(h)
    assert "household_load" not in result.inferred_roles
    assert financial_measurement_coverage(result.history)["household_load"]["gap_count"]
