from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from test_financial_result_ledger import _history, _snapshot
from test_v2_financial_measurement_inference import _solar, _SolarReader, _with_soc

from picot.v2.financial_measurement_inference import infer_financial_measurements
from picot.v2.financial_measurement_observer import FinancialMeasurementObserver
from picot.v2.financial_result_ledger import FinancialResultLedger
from picot.v2.financial_result_metrics import financial_measurement_coverage
from picot.v2.grid_charge_review import ReviewSettings
from picot.v2.power_history import PowerHistoryPoint, numeric_power_history


def _many_gaps():
    h = _history(pv_generation=0, household_load=100, grid_import=100,
                 grid_export=0, battery_charge=0, battery_discharge=0)
    end = h.starts_at + timedelta(hours=4)
    return replace(h, ends_at=end, series=tuple(
        replace(s, history_semantics="sampled_linear", points=tuple(
            PowerHistoryPoint(h.starts_at + timedelta(minutes=m), 100, f"load-{m}")
            for m in range(0, 241, 10)
        )) if s.role == "household_load" else
        replace(s, points=(s.points[0], replace(s.points[-1], sampled_at=end)))
        for s in h.series
    ))


def test_all_gaps_are_reconstructed_even_when_the_diagnostic_list_is_truncated():
    h = _many_gaps()
    before = repr(h)
    result = infer_financial_measurements(h, pv_maximum_power_w=4200,
        charge_maximum_power_w=2400, discharge_maximum_power_w=2400)
    assert result.raw_coverage["household_load"]["omitted_gap_count"] == 4
    assert not financial_measurement_coverage(result.history)["household_load"]["gap_count"]
    load = next(s for s in result.history.series if s.role == "household_load")
    assert FinancialResultLedger._integrate(load, h.starts_at, h.ends_at) == pytest.approx(400)
    assert repr(h) == before


def test_real_source_failure_after_twentieth_gap_is_not_hidden():
    h = _many_gaps()
    at = h.starts_at + timedelta(hours=3, minutes=35)
    h = replace(h, series=tuple(replace(s, points=(s.points[0],
        PowerHistoryPoint(at, float("nan"), "grid-out"),
        PowerHistoryPoint(at + timedelta(minutes=1), 100, "grid-back"), s.points[-1],
    )) if s.role == "grid_import" else s for s in h.series))
    result = infer_financial_measurements(h, pv_maximum_power_w=4200,
        charge_maximum_power_w=2400, discharge_maximum_power_w=2400)
    assert financial_measurement_coverage(result.history)["household_load"]["gap_count"]
    assert result.rejected
    assert any(datetime.fromisoformat(r["starts_at"]) <= at
               < datetime.fromisoformat(r["ends_at"]) for r in result.rejected)


@pytest.mark.parametrize("real_gap", [None, "earlier", "current_quarter"])
def test_open_quarter_does_not_hide_valid_closed_results_or_real_source_gaps(tmp_path, real_gap):
    h = _with_soc(_many_gaps())
    end = h.starts_at + timedelta(hours=3, minutes=6)
    h = replace(h, ends_at=end, series=tuple(replace(s, points=tuple(
        p for p in s.points if p.sampled_at <= end)) for s in h.series))
    if real_gap:
        at = h.starts_at + (timedelta(minutes=20) if real_gap == "earlier"
                           else timedelta(hours=3, minutes=1))
        h = replace(h, series=tuple(replace(s, points=(*s.points,
            PowerHistoryPoint(at, float("nan"), "grid-out"),
            PowerHistoryPoint(at + timedelta(minutes=2), 100, "grid-back"),
        )) if s.role == "grid_import" else s for s in h.series))
    snapshot = _snapshot()
    snapshot = replace(snapshot, captured_at=end, price_points=tuple(
        replace(p, ends_at=end) for p in snapshot.price_points))
    ledger = FinancialResultLedger(state_path=tmp_path / "ledger.json")
    numeric = numeric_power_history(h)
    numeric = replace(numeric, series=tuple(s for s in numeric.series if s.role != "storage_soc"))
    initial = ledger.update(snapshot, numeric, measurement_history=h)
    # A pre-fix incomplete estimate for the same observation must not block
    # replacing it with complete results through the last closed quarter.
    ledger.store_financial_estimate(initial["today"]["day"],
        initial["today"]["financial_metrics"], {"attempted_at": end.isoformat()})
    observer = FinancialMeasurementObserver(ledger=ledger, night_reader=_SolarReader(_solar(h)),
        publish=lambda _: None, pv_maximum_power_w=4200)
    observer(snapshot, h, snapshot.price_points,
             ReviewSettings(8160, .1, 1, 2400, 2400, 1, 1, .05), False)
    metrics = ledger.dashboard_view()["today"]["financial_metrics"]
    if real_gap:
        assert metrics["values"]["net_picot_value_eur"]["status"] == "incomplete"
    else:
        assert metrics["status"] == "estimated"
        assert metrics["ends_at"] == (h.starts_at + timedelta(hours=3)).isoformat()
        assert metrics["pending_period"]["ends_at"] == end.isoformat()
        assert metrics["values"]["grid_import_cost_eur"]["value_eur"] == pytest.approx(.075)
