from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_financial_result_ledger import _history, _snapshot

from picot.v2.financial_measurement_inference import (
    FinancialNightWindow,
    financial_night_windows,
    infer_financial_measurements,
)
from picot.v2.financial_measurement_observer import FinancialMeasurementObserver
from picot.v2.financial_result_ledger import FinancialPhysicalContext, FinancialResultLedger
from picot.v2.financial_result_metrics import financial_measurement_coverage
from picot.v2.grid_charge_review import ReviewSettings
from picot.v2.power_history import PowerHistoryPoint, PowerHistorySeries, numeric_power_history
from picot.v2.pv_solar_history import SolarContextObservation, SolarHistoryReadResult


def test_financial_coverage_combines_one_continuous_outage(tmp_path):
    history = _history(pv_generation=0, household_load=100, grid_import=100,
                       grid_export=0, battery_charge=0, battery_discharge=0)
    pv = history.series[0]
    points = (
        PowerHistoryPoint(history.starts_at, float("nan"), "off-1"),
        PowerHistoryPoint(history.starts_at + timedelta(minutes=20), float("nan"), "off-2"),
        PowerHistoryPoint(history.starts_at + timedelta(minutes=40), float("nan"), "off-3"),
        pv.points[-1],
    )
    raw = replace(history, series=(replace(pv, points=points), *history.series[1:]))
    view = FinancialResultLedger(state_path=tmp_path / "ledger.json").update(
        _snapshot(), history, measurement_history=raw,
    )
    coverage = view["today"]["financial_metrics"]["measurement_coverage"]["pv_generation"]
    assert coverage["gap_count"] == 1
    assert coverage["gaps"][0]["duration_seconds"] == 3600


def _base():
    return _history(pv_generation=0, household_load=100, grid_import=100,
                    grid_export=0, battery_charge=0, battery_discharge=0)


def _gap(history, role, *, seconds=0.4, minute=30, close=True):
    start = history.starts_at + timedelta(minutes=minute)
    return replace(history, series=tuple(
        replace(s, points=(
            s.points[0], PowerHistoryPoint(start, float("nan"), "unavailable"),
            *((PowerHistoryPoint(start + timedelta(seconds=seconds), s.points[0].power_w,
                                 "restored"), s.points[-1]) if close else ()),
        )) if s.role == role else s for s in history.series
    ))


def _infer(history, **kwargs):
    return infer_financial_measurements(
        history, charge_maximum_power_w=2400, discharge_maximum_power_w=2400,
        **{"pv_maximum_power_w": 4200, **kwargs},
    )


def _solar(history, elevation=-20):
    at = history.starts_at - timedelta(minutes=30)
    points = []
    while at <= history.ends_at:
        points.append(SolarContextObservation(str(at), at, 180, elevation,
                                              history.ends_at + timedelta(hours=6)))
        at += timedelta(minutes=15)
    return SolarHistoryReadResult("sun.sun", history.starts_at - timedelta(minutes=30),
                                  history.ends_at, "available", None, tuple(points), "test-solar")


def _night_history():
    h = _base()
    return replace(h, series=tuple(
        replace(s, points=(PowerHistoryPoint(h.starts_at, float("nan"), "night-unavailable"),
                           s.points[-1])) if s.role == "pv_generation" else
        replace(s, history_semantics="sampled_linear", points=(
            replace(s.points[0], sampled_at=h.starts_at - timedelta(hours=1)), s.points[-1],
        )) if s.role == "household_load" else s for s in h.series
    ))


def test_night_reconstructs_missing_household_from_equal_energy_intervals():
    h = _night_history()
    before = repr(h)
    result = _infer(h, night_windows=financial_night_windows(_solar(h), h.starts_at, h.ends_at))
    assert result.inferred_roles == {"pv_generation", "household_load"}
    assert result.uncertainty_wh == 0
    assert not any(c["gap_count"] for role, c in financial_measurement_coverage(
        result.history
    ).items() if role != "storage_soc")
    household = next(s for s in result.history.series if s.role == "household_load")
    assert FinancialResultLedger._integrate(household, h.starts_at, h.ends_at) == pytest.approx(100)
    assert repr(h) == before


@pytest.mark.parametrize("solar_status,elevation", [("unavailable", -20), ("available", 20)])
def test_clock_time_and_forecasts_never_substitute_for_night_evidence(solar_status, elevation):
    h = _night_history()
    solar = replace(_solar(h, elevation), status=solar_status)
    result = _infer(h, night_windows=financial_night_windows(solar, h.starts_at, h.ends_at))
    assert financial_measurement_coverage(result.history)["pv_generation"]["gap_count"] == 1
    assert "pv_generation" not in result.inferred_roles


def test_positive_pv_measurements_are_retained_inside_a_night_window():
    h = _history(pv_generation=100, household_load=100, grid_import=0,
                 grid_export=0, battery_charge=0, battery_discharge=0)
    result = _infer(h, night_windows=(FinancialNightWindow(h.starts_at, h.ends_at, ("sun",)),))
    assert result.history == h
    assert not result.inferred_roles


def test_small_battery_gap_has_a_physical_error_bound():
    h = _gap(_base(), "battery_discharge")
    result = _infer(h)
    assert result.inferred_roles == {"battery_discharge"}
    assert result.uncertainty_wh == pytest.approx(2400 * 0.4 / 3600)
    assert not financial_measurement_coverage(result.history)["battery_discharge"]["gap_count"]


@pytest.mark.parametrize("role,seconds,close,pv_limit", [
    ("battery_discharge", 121, True, 4200),
    ("battery_discharge", 0.4, False, 4200),
    ("grid_import", 0.4, True, 4200),
    ("pv_generation", 60, True, 0),
    ("pv_generation", 120, True, 4200),  # 140 Wh exceeds the per-gap energy budget.
])
def test_open_large_unbounded_and_grid_gaps_remain_missing(role, seconds, close, pv_limit):
    result = _infer(_gap(_base(), role, seconds=seconds, close=close),
                    pv_maximum_power_w=pv_limit)
    assert role not in result.inferred_roles
    assert financial_measurement_coverage(result.history)[role]["gap_count"]


def test_cumulative_uncertainty_budget_blocks_many_individually_small_gaps():
    h = _base()
    pv = h.series[0]
    points = [pv.points[0]]
    for minute in range(2, 18, 2):
        at = h.starts_at + timedelta(minutes=minute)
        points.extend([PowerHistoryPoint(at, float("nan"), "gap"),
                       PowerHistoryPoint(at + timedelta(seconds=60), 0, "resume")])
    points.append(pv.points[-1])
    h = replace(h, series=(replace(pv, points=tuple(points)), *h.series[1:]))
    result = _infer(h)
    assert "pv_generation" not in result.inferred_roles
    assert result.uncertainty_wh == 0
    assert len(result.rejected) == 8
    assert {r["kind"] for r in result.rejected} == {"daily_uncertainty_limit_exceeded"}


def test_negative_household_balance_is_not_clipped_or_declared_measured():
    h = _night_history()
    h = replace(h, series=tuple(replace(s, points=tuple(replace(p, power_w=1000)
                   for p in s.points)) if s.role == "battery_charge" else s for s in h.series))
    result = _infer(h, night_windows=(FinancialNightWindow(h.starts_at, h.ends_at, ("sun",)),))
    assert financial_measurement_coverage(result.history)["household_load"]["gap_count"]
    assert "household_load" not in result.inferred_roles
    assert any(r["kind"] == "negative_household_energy_balance" for r in result.rejected)


def test_solar_crossing_is_interpolated_and_sparse_solar_data_is_not_a_whole_night():
    h = _base()
    solar = _solar(h)
    at = h.starts_at
    left = replace(solar.observations[0], sampled_at=at, solar_elevation_degrees=-1)
    right = replace(left, sampled_at=at + timedelta(minutes=10), solar_elevation_degrees=1,
                    evidence_id="right")
    windows = financial_night_windows(replace(solar, observations=(left, right)),
                                      h.starts_at, h.ends_at)
    assert len(windows) == 1
    assert windows[0].ends_at == at + timedelta(minutes=5)
    assert not financial_night_windows(
        replace(solar, observations=(left, replace(right, sampled_at=at + timedelta(hours=1)))),
        h.starts_at, h.ends_at,
    )


@pytest.mark.parametrize("elevation,age_minutes,admitted", [
    (-6, 15, True), (-6, 16, False), (-1, 1, False), (-200, 1, False),
])
def test_unfinished_night_tail_requires_recent_valid_deep_night(elevation, age_minutes, admitted):
    h = _base()
    solar = _solar(h)
    last = replace(solar.observations[-1], sampled_at=h.ends_at-timedelta(minutes=age_minutes),
                   solar_elevation_degrees=elevation)
    windows = financial_night_windows(replace(solar, observations=(last,)), h.starts_at, h.ends_at)
    assert bool(windows) == admitted


@pytest.mark.parametrize("day,hours", [(datetime(2026, 3, 29), 23), (datetime(2026, 10, 25), 25)])
def test_inference_uses_elapsed_time_over_dutch_dst_days(day, hours):
    tz = ZoneInfo("Europe/Amsterdam")
    start = day.replace(tzinfo=tz)
    end = (day + timedelta(days=1)).replace(tzinfo=tz)
    h = _base()
    h = replace(h, starts_at=start, ends_at=end, series=tuple(
        replace(s, points=(replace(s.points[0], sampled_at=start),
                           replace(s.points[-1], sampled_at=end))) for s in h.series
    ))
    result = _infer(h)
    assert (result.history.ends_at - result.history.starts_at).total_seconds() == hours * 3600
    assert result.history.starts_at.tzinfo == UTC


class _SolarReader:
    def __init__(self, solar):
        self.solar, self.calls = solar, 0

    def read(self, **kwargs):
        self.calls += 1
        return self.solar


def _with_soc(h):
    return replace(h, series=(*h.series, PowerHistorySeries(
        "soc", "storage_soc", "sensor.soc", "identity",
        (PowerHistoryPoint(h.starts_at, 50, "soc-start"),
         PowerHistoryPoint(h.ends_at, 50, "soc-end")),
    )))


def test_observer_persists_derived_values_without_changing_original_inventory(tmp_path):
    h = _with_soc(_gap(_base(), "battery_discharge"))
    ledger = FinancialResultLedger(state_path=tmp_path / "ledger.json")
    numeric = replace(numeric_power_history(h), series=tuple(
        s for s in numeric_power_history(h).series if s.role != "storage_soc"
    ))
    snapshot = _snapshot()
    before = ledger.update(snapshot, numeric, measurement_history=h)
    inventory = ledger.storage_energy_inventory()
    solar_reader = _SolarReader(_solar(h))
    observer = FinancialMeasurementObserver(ledger=ledger, solar_reader=solar_reader,
        publish=lambda _: None, pv_maximum_power_w=4200)
    settings = ReviewSettings(8160, .1, 1, 2400, 2400, 1, 1, .05)
    snapshot_before = repr(snapshot)
    observer(snapshot, h, snapshot.price_points, settings, False)
    view = ledger.dashboard_view()
    assert view["today"]["financial_metrics"]["status"] == "estimated"
    values = view["today"]["financial_metrics"]["values"]
    assert values["grid_import_cost_eur"]["status"] == "available"
    assert values["battery_wear_eur"]["status"] == "estimated"
    assert values["battery_wear_eur"]["value_eur"] == 0
    assert view["cumulative"]["estimated_battery_days"] == 1
    assert ledger.storage_energy_inventory() == inventory
    assert repr(snapshot) == snapshot_before
    assert FinancialResultLedger(state_path=tmp_path / "ledger.json").dashboard_view() == view
    refreshed = ledger.update(snapshot, numeric, measurement_history=h)
    assert refreshed == view
    ignored = {"financial_metrics", "financial_estimate", "financial_inference_status"}
    assert {k: v for k, v in refreshed["today"].items() if k not in ignored} == {
        k: v for k, v in before["today"].items() if k not in ignored}
    observer(snapshot, h, snapshot.price_points, settings, False)
    assert solar_reader.calls == 1


@pytest.mark.parametrize("price", [0, .25, -.25])
def test_night_observer_recovers_benefits_but_keeps_the_original_day_incomplete(tmp_path, price):
    h = _with_soc(_night_history())
    ledger = FinancialResultLedger(state_path=tmp_path / "ledger.json")
    raw = replace(numeric_power_history(h), series=tuple(
        s for s in numeric_power_history(h).series if s.role != "storage_soc"
    ))
    snapshot = _snapshot(price=price)
    ledger.update(snapshot, raw, measurement_history=h)
    observer = FinancialMeasurementObserver(ledger=ledger, solar_reader=_SolarReader(_solar(h)),
        publish=lambda _: None, pv_maximum_power_w=4200)
    observer(snapshot, h, snapshot.price_points, ReviewSettings(8160, .1, 1, 2400, 2400, 1, 1, .05),
             False)
    day = ledger.dashboard_view()["today"]
    assert day["status"] == "incomplete"
    assert day["financial_metrics"]["status"] == "estimated"
    assert day["financial_metrics"]["values"]["net_battery_value_eur"]["value_eur"] == 0
    assert day["financial_metrics"]["values"]["grid_import_cost_eur"]["value_eur"] == round(
        .1 * price, 4,
    )
    assert ledger.storage_energy_inventory() is None


def test_observed_power_above_declared_bound_disables_gap_inference():
    h = _gap(_base(), "pv_generation", seconds=60)
    pv = h.series[0]
    h = replace(h, series=(replace(pv, points=(*pv.points[:-1],
        replace(pv.points[-1], power_w=5000))), *h.series[1:]))
    result = _infer(h)
    assert "pv_generation" not in result.inferred_roles
    assert result.rejected[0]["kind"] == "physical_power_bound_exceeded"


def test_historical_closing_soc_does_not_inherit_todays_ha_read_envelope(tmp_path):
    h = _with_soc(_gap(_base(), "battery_discharge"))
    ledger = FinancialResultLedger(state_path=tmp_path / "ledger.json")
    original = _snapshot()
    numeric = replace(numeric_power_history(h), series=tuple(
        s for s in numeric_power_history(h).series if s.role != "storage_soc"
    ))
    ledger.update(original, numeric, measurement_history=h)
    now = original.captured_at + timedelta(days=1)
    current = replace(original, captured_at=now, horizon_end=now + timedelta(hours=1),
        current_storage_states=(replace(original.current_storage_states[0], measured_at=now,
            state_valid_since=now - timedelta(minutes=1), state_read_at=now),))
    before = repr(current)
    observer = FinancialMeasurementObserver(ledger=ledger, solar_reader=_SolarReader(_solar(h)),
        publish=lambda _: None, pv_maximum_power_w=4200)
    observer(current, h, original.price_points, ReviewSettings(8160, .1, 1, 2400, 2400, 1, 1, .05),
             False)
    assert ledger.dashboard_view()["today"]["financial_metrics"]["status"] == "estimated"
    assert repr(current) == before


def test_display_tariff_integration_preserves_dense_history_amounts(tmp_path):
    from picot.v2.financial_measurement_observer import _tariff_integrated_history

    history, snapshot = _base(), _snapshot()
    history = replace(history, series=tuple(
        replace(series, points=tuple(
            PowerHistoryPoint(history.starts_at + timedelta(seconds=second),
                              float((second * (role_index + 1) * 137) % 2401),
                              f"dense:{role_index}:{second}")
            for second in range(3601)
        )) for role_index, series in enumerate(history.series)
    ))
    bounds = [history.starts_at, history.starts_at + timedelta(seconds=1023.25),
              history.starts_at + timedelta(minutes=41), history.ends_at]
    prices = tuple(replace(snapshot.price_points[0], point_id=f"price-{index}",
                           starts_at=start, ends_at=end, value_eur_per_kwh=rate)
                   for index, (start, end, rate) in enumerate(zip(
                       bounds, bounds[1:], [.35, 0, -.15], strict=False)))
    ledger = FinancialResultLedger(state_path=tmp_path / "ledger.json",
                                  charge_efficiency=.91, discharge_efficiency=.91)
    context = FinancialPhysicalContext(history.ends_at, snapshot.current_storage_states,
                                       snapshot.storage_physical_limits)
    before = repr(history)
    compact = _tariff_integrated_history(
        history, ledger._price_segments(prices, history.starts_at, history.ends_at),
    )
    assert all(len(s.points) == len(prices) for s in compact.series)
    assert repr(history) == before
    original = ledger.evaluate_display_history(context, history, prices)
    integrated = ledger.evaluate_display_history(context, compact, prices)
    assert original["status"] == "available"
    assert {key: value for key, value in original.items() if key != "coverage_by_role"} == {
        key: value for key, value in integrated.items() if key != "coverage_by_role"}


def test_delayed_observer_preserves_newer_raw_result_and_expires_stale_estimates(tmp_path):
    from threading import Event, Thread

    h = _with_soc(_gap(_base(), "battery_discharge"))
    ledger = FinancialResultLedger(state_path=tmp_path / "ledger.json")
    raw = replace(numeric_power_history(h), series=tuple(
        s for s in numeric_power_history(h).series if s.role != "storage_soc"
    ))
    snapshot = _snapshot()
    ledger.update(snapshot, raw, measurement_history=h)
    entered, resume = Event(), Event()

    class Reader(_SolarReader):
        def read(self, **kwargs):
            entered.set()
            assert resume.wait(5)
            return super().read(**kwargs)

    observer = FinancialMeasurementObserver(ledger=ledger, solar_reader=Reader(_solar(h)),
        publish=lambda _: None, pv_maximum_power_w=4200)
    worker = Thread(target=observer, args=(snapshot, h, snapshot.price_points,
                    ReviewSettings(8160, .1, 1, 2400, 2400, 1, 1, .05), False))
    worker.start()
    try:
        assert entered.wait(5)
        later = replace(snapshot, captured_at=snapshot.captured_at + timedelta(minutes=1))
        ledger.update(later, replace(raw, ends_at=later.captured_at),
                      measurement_history=replace(h, ends_at=later.captured_at))
    finally:
        resume.set()
        worker.join(5)
    assert not worker.is_alive()
    view = ledger.dashboard_view()
    assert view["today"]["ends_at"] == later.captured_at.isoformat()
    assert view["today"]["financial_metrics"]["ends_at"] == h.ends_at.isoformat()
    assert view["today"]["financial_metrics"]["status"] == "estimated"
    much_later = replace(snapshot, captured_at=snapshot.captured_at + timedelta(minutes=16))
    view = ledger.update(much_later, replace(raw, ends_at=much_later.captured_at),
                         measurement_history=replace(h, ends_at=much_later.captured_at))
    assert view["today"]["financial_metrics"]["status"] != "estimated"
    assert view["today"]["financial_inference_status"]["reason"] == "financial_inference_stale"


@pytest.mark.parametrize("failure", ["prices", "soc", "settings", "transport", "duplicate"])
def test_observer_failures_never_turn_missing_values_into_full_results(tmp_path, failure):
    h = _with_soc(_gap(_base(), "battery_discharge"))
    ledger = FinancialResultLedger(state_path=tmp_path / "ledger.json")
    raw = replace(numeric_power_history(h), series=tuple(
        s for s in numeric_power_history(h).series if s.role != "storage_soc"
    ))
    snapshot = _snapshot()
    ledger.update(snapshot, raw, measurement_history=h)
    inventory = ledger.storage_energy_inventory()

    class Reader(_SolarReader):
        def read(self, **kwargs):
            if failure == "transport":
                raise TimeoutError("test")
            return super().read(**kwargs)

    if failure == "soc":
        h = replace(h, series=tuple(s for s in h.series if s.role != "storage_soc"))
    elif failure == "duplicate":
        h = replace(h, series=(*h.series, h.series[0]))
    observer = FinancialMeasurementObserver(ledger=ledger, solar_reader=Reader(_solar(h)),
        publish=lambda _: None, pv_maximum_power_w=4200)
    observer(snapshot, h, () if failure == "prices" else snapshot.price_points,
             ReviewSettings(8160, .1, 1, 2400, 2400, 1, 1, .05), failure == "settings")
    view = ledger.dashboard_view()
    assert view["today"]["financial_metrics"]["status"] != "estimated"
    assert ledger.storage_energy_inventory() == inventory
    if failure != "prices":
        assert view["today"]["financial_inference_status"]["status"] == "unavailable"
