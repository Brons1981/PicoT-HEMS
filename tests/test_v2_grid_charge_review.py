from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from picot.v2.contracts import PriceForecastPoint
from picot.v2.grid_charge_review import ReviewSettings, actual_soc_view, review_day
from picot.v2.grid_charge_review_runtime import GridChargeReviewObserver
from picot.v2.power_history import PowerHistoryPoint, PowerHistorySeries, PowerHistorySnapshot
from picot.v2.web_ui import WebViewStore

START = datetime(2026, 9, 10, 22, tzinfo=UTC)
SETTINGS = ReviewSettings(1000, 0.1, 1, 1000, 1000, 1, 1, 0)


def history(*, cloudy: bool = False) -> PowerHistorySnapshot:
    # A 1 kWh battery starts at 20%, charges 600 Wh from grid and 200 Wh
    # from PV, then serves 200 Wh household load. On a sunny day 600 Wh
    # extra PV was exported; without grid charging this could fill the battery.
    powers = {
        "pv_generation": [0, 300 if cloudy else 900, 0, 0],
        "household_load": [0, 100, 200, 200],
        "grid_import": [600, 0, 0, 0],
        "grid_export": [0, 0 if cloudy else 600, 0, 0],
        "battery_charge": [600, 200, 0, 0],
        "battery_discharge": [0, 0, 200, 200],
        "storage_soc": [20, 80, 100, 80],
    }
    return PowerHistorySnapshot(
        START,
        START + timedelta(hours=3),
        "available",
        None,
        tuple(
            PowerHistorySeries(
                role,
                role,
                "sensor." + role,
                "identity",
                tuple(
                    PowerHistoryPoint(START + timedelta(hours=i), v, f"{role}-{i}")
                    for i, v in enumerate(values)
                ),
            )
            for role, values in powers.items()
        ),
    )


def prices() -> tuple[PriceForecastPoint, ...]:
    return tuple(
        PriceForecastPoint(
            str(i), START + timedelta(hours=i), START + timedelta(hours=i + 1), value, 1, "tariff"
        )
        for i, value in enumerate((0.1, 0.3, 0.4))
    )


def evaluate(h: PowerHistorySnapshot, settings: ReviewSettings = SETTINGS):
    return review_day(h, prices(), settings, ((START, START + timedelta(hours=2)),))


def test_sunny_day_reaches_full_without_grid_but_foregone_export_can_cost_more():
    h = history()
    before = repr(h)
    result = evaluate(h)
    assert result["status"] == "available", result
    assert result["pv_only_feasible"] is True
    assert result["pv_only_peak_soc_percent"] == 100
    assert result["avoidable_grid_charge_kwh"] == pytest.approx(0.6)
    assert result["cost_difference_eur"] == pytest.approx(-0.12)
    assert result["replay_closing_soc_percent"] == pytest.approx(80)
    assert repr(h) == before
    assert result["observer_only"] and not result["selection_permitted"]


def test_cloudy_day_cannot_avoid_grid_and_still_reach_daily_goal():
    result = evaluate(history(cloudy=True))
    assert result["status"] == "available", result
    assert result["pv_only_feasible"] is False
    assert result["pv_only_peak_soc_percent"] == 40
    assert result["avoidable_grid_charge_kwh"] == 0


def test_power_limit_prevents_treating_every_exported_kwh_as_recoverable():
    result = evaluate(history(), replace(SETTINGS, charge_power_w=600))
    assert result["status"] == "available", result
    assert result["pv_only_feasible"] is False
    assert 0 < result["avoidable_grid_charge_kwh"] < 0.6


@pytest.mark.parametrize("role", ("storage_soc", "pv_generation", "household_load"))
def test_unavailable_measurements_never_become_zero_or_a_savings_claim(role):
    h = history()
    h = replace(
        h,
        series=tuple(
            replace(
                s,
                points=(
                    s.points[0],
                    PowerHistoryPoint(START + timedelta(minutes=30), float("nan"), "gap"),
                    *s.points[1:],
                ),
            )
            if s.role == role
            else s
            for s in h.series
        ),
    )
    result = evaluate(h)
    assert result["status"] == "incomplete"
    assert result["reason"] == "measurement_unavailable"
    assert "avoidable_grid_charge_kwh" not in result


def test_no_savings_claim_when_bms_soc_and_power_energy_disagree():
    h = history()
    h = replace(
        h,
        series=tuple(
            replace(s, points=(*s.points[:-1], replace(s.points[-1], power_w=50)))
            if s.role == "storage_soc"
            else s
            for s in h.series
        ),
    )
    assert evaluate(h)["reason"] == "flow_soc_mismatch"


def test_full_outside_main_window_does_not_count_as_daily_goal():
    h = history()
    result = review_day(h, prices(), SETTINGS, ((START, START + timedelta(minutes=30)),))
    assert result["status"] == "incomplete"
    assert result["reason"] == "reference_replay_not_feasible"


def test_export_is_preserved_and_not_counted_as_avoidable_grid_energy():
    h = history()
    h = replace(
        h,
        series=tuple(
            replace(
                s,
                points=tuple(
                    replace(p, power_w=500)
                    if i == 2 and s.role in ("battery_discharge", "grid_export")
                    else replace(p, power_w=(0 if i >= 2 else p.power_w))
                    if s.role == "household_load"
                    else replace(p, power_w=50)
                    if s.role == "storage_soc" and i == 3
                    else p
                    for i, p in enumerate(s.points)
                ),
            )
            for s in h.series
        ),
    )
    result = evaluate(h)
    assert result["status"] == "available", result
    assert result["preserved_battery_export_kwh"] == pytest.approx(0.5)
    assert result["replay_closing_soc_percent"] == pytest.approx(50)


def test_actual_soc_is_raw_percent_and_preserves_breaks():
    h = history()
    soc = next(s for s in h.series if s.role == "storage_soc")
    h = replace(
        h,
        series=(
            replace(
                soc,
                points=(soc.points[0], replace(soc.points[1], power_w=float("nan")), soc.points[2]),
            ),
        ),
    )
    view = actual_soc_view(h)
    assert [p["soc_percent"] for p in view["points"]] == [20, None, 100]
    json.dumps(view, allow_nan=False)


def test_passive_overlay_keeps_original_plan_and_curve():
    store = WebViewStore()
    plan = {
        "chosen_plan": {"plan_id": "kept"},
        "soc_timeline": [{"at": START.isoformat(), "soc_percent": 42}],
    }
    store.publish({"planning_status": plan})
    store.publish_grid_charge_review({"actual_soc": actual_soc_view(history()), "days": []})
    assert json.loads(store.latest_json())["planning_status"] == plan
    store.publish({"planning_status": plan})
    assert json.loads(store.latest_json())["grid_charge_review"]["actual_soc"]["points"]


def test_observer_persists_review_and_finalizes_after_midnight(tmp_path):
    from test_financial_result_ledger import _snapshot

    from picot.v2.daily_charge_assignment import (
        DailyChargeAssignment,
        DailyChargeRevisionReason,
        DailyChargeSegment,
    )

    recorded = []

    class Reader:
        def read(self, **kwargs):
            assert kwargs["preserve_unavailable"] is True
            end = kwargs["ends_at"]
            # Keep the remaining day at 80% without further flows.
            base = history()
            return replace(
                base,
                ends_at=end,
                series=tuple(
                    replace(
                        s,
                        points=(
                            *s.points[:-1],
                            replace(s.points[-1], power_w=80 if s.role == "storage_soc" else 0),
                            PowerHistoryPoint(end, 80 if s.role == "storage_soc" else 0, "closing"),
                        ),
                    )
                    for s in base.series
                ),
            )

    def observer():
        return GridChargeReviewObserver(
            path=tmp_path / "review.json",
            reader=Reader(),
            specs=(),
            soc_entity_id="sensor.soc",
            attach_household=lambda h: h,
            publish=recorded.append,
            charge_efficiency=1,
            discharge_efficiency=1,
            wear_eur_per_kwh=0,
        )

    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        captured_at=START + timedelta(hours=3),
        current_storage_states=(
            replace(snapshot.current_storage_states[0], usable_capacity_wh=1000),
        ),
        storage_physical_limits=(
            replace(
                snapshot.storage_physical_limits[0],
                maximum_charge_input_power_w=1000,
                maximum_discharge_output_power_w=1000,
            ),
        ),
    )
    owner = DailyChargeAssignment("battery", date(2026, 9, 11), "Europe/Amsterdam", START)
    owner = owner.bind_main_route(
        plan_id="original",
        segments=(DailyChargeSegment("main", START, START + timedelta(hours=2)),),
        at=START,
        reason=DailyChargeRevisionReason.INITIAL,
        evidence_id="original-evidence",
    )
    rates = (
        *prices(),
        PriceForecastPoint(
            "tail", START + timedelta(hours=3), START + timedelta(days=1), 0.2, 1, "tariff"
        ),
    )
    obs = observer()
    obs.refresh(snapshot, rates, (owner,), ())
    assert recorded[-1]["days"][0]["finalized"] is False
    restarted = observer()
    restarted.refresh(
        replace(snapshot, captured_at=START + timedelta(days=1, minutes=5)), (), (owner,), ()
    )
    day = next(d for d in recorded[-1]["days"] if d["day"] == "2026-09-11")
    assert day["finalized"] is True
    assert day["status"] == "available", day
    assert day["avoidable_grid_charge_kwh"] == pytest.approx(0.6)
    assert day["route_plan_id"] == "original"


def test_missing_tariffs_and_missing_main_membership_fail_closed():
    assert (
        review_day(history(), (), SETTINGS, ((START, START + timedelta(hours=2)),))["reason"]
        == "price_coverage_incomplete"
    )
    assert review_day(history(), prices(), SETTINGS, ())["reason"] == "main_window_evidence_missing"


def test_daily_peak_alone_cannot_hide_a_lower_closing_inventory():
    values = {
        "pv_generation": [0, 0, 0, 0],
        "household_load": [600, 0, 0, 0],
        "grid_import": [0, 500, 0, 0],
        "grid_export": [0, 0, 0, 0],
        "battery_charge": [0, 500, 0, 0],
        "battery_discharge": [600, 0, 0, 0],
        "storage_soc": [100, 40, 90, 90],
    }
    h = replace(
        history(),
        series=tuple(
            replace(
                s,
                points=tuple(replace(p, power_w=values[s.role][i]) for i, p in enumerate(s.points)),
            )
            for s in history().series
        ),
    )
    result = evaluate(h)
    assert result["status"] == "available", result
    assert result["pv_only_peak_soc_percent"] == 100
    assert result["pv_only_feasible"] is False
    assert result["avoidable_grid_charge_kwh"] == 0


def test_conversion_losses_reduce_removable_grid_energy():
    h = history()
    changes = {
        "battery_charge": [600, 400, 0, 0],
        "grid_export": [0, 400, 0, 0],
        "storage_soc": [20, 68, 100, 75],
    }
    h = replace(
        h,
        series=tuple(
            replace(
                s,
                points=tuple(
                    replace(p, power_w=changes[s.role][i]) for i, p in enumerate(s.points)
                ),
            )
            if s.role in changes
            else s
            for s in h.series
        ),
    )
    result = evaluate(h, replace(SETTINGS, charge_efficiency=0.8, discharge_efficiency=0.8))
    assert result["status"] == "available", result
    assert result["pv_only_feasible"] is False
    assert 0.39 < result["avoidable_grid_charge_kwh"] <= 0.4
    assert result["replay_closing_soc_percent"] >= 75


def test_frozen_pv_comparison_uses_only_same_closed_intervals():
    from picot.v2.daily_pv_comparison import DailyPVComparisonBasis, DailyPVReferenceInterval

    basis = DailyPVComparisonBasis(
        "assignment",
        "original-snapshot",
        START,
        START,
        START + timedelta(hours=3),
        tuple(
            DailyPVReferenceInterval(
                START + timedelta(hours=i),
                START + timedelta(hours=i + 1),
                200,
                400,
                ("original-solcast",),
            )
            for i in range(3)
        ),
    )
    h = replace(history(), ends_at=START + timedelta(hours=2, minutes=30))
    result = GridChargeReviewObserver._pv_comparison(h, basis)
    assert result["status"] == "available"
    assert result["actual_kwh"] == 0.9
    assert result["expected_kwh"] == 0.6
    assert result["difference_kwh"] == 0.3
    assert result["ends_at"] == (START + timedelta(hours=2)).isoformat()


def test_background_worker_never_queues_overlapping_or_same_period_work(tmp_path, monkeypatch):
    from test_financial_result_ledger import _snapshot

    import picot.v2.grid_charge_review_runtime as runtime

    jobs = []

    class Thread:
        def __init__(self, *, target, name, daemon):
            assert daemon
            self.target = target

        def start(self):
            jobs.append(self.target)

    monkeypatch.setattr(runtime, "Thread", Thread)
    observer = GridChargeReviewObserver(
        path=tmp_path / "r.json",
        reader=None,
        specs=(),
        soc_entity_id="sensor.soc",
        attach_household=lambda h: h,
        publish=lambda v: None,
        charge_efficiency=1,
        discharge_efficiency=1,
        wear_eur_per_kwh=0,
    )
    monkeypatch.setattr(observer, "refresh", lambda *args: (_ for _ in ()).throw(OSError()))
    snapshot = _snapshot()
    observer.submit(snapshot, (), (), ())
    observer.submit(
        replace(snapshot, captured_at=snapshot.captured_at + timedelta(minutes=6)), (), (), ()
    )
    assert len(jobs) == 1
    jobs[0]()
    assert observer.lock.locked() is False
    assert observer.due(snapshot.captured_at) is False
    assert observer.due(snapshot.captured_at + timedelta(minutes=6)) is True
