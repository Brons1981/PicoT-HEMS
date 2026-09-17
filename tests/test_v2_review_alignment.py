from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.power_history import PowerHistoryPoint, PowerHistorySeries, PowerHistorySnapshot
from picot.v2.review_alignment import aligned_measurements

START = datetime(2026, 9, 17, 10, tzinfo=UTC)


def history():
    flows = {
        "pv_generation": [(0, 0), (5, 1200)],
        "grid_import": [(0, 0)],
        "grid_export": [(0, 0)],
        "battery_charge": [(0, 500)],
        "battery_discharge": [(0, 0)],
    }
    return PowerHistorySnapshot(
        START,
        START + timedelta(minutes=15),
        "available",
        None,
        tuple(
            PowerHistorySeries(
                role,
                role,
                "sensor." + role,
                "identity",
                tuple(
                    PowerHistoryPoint(START + timedelta(minutes=m), value, f"{role}:{m}")
                    for m, value in points
                ),
            )
            for role, points in flows.items()
        ),
    )


def test_staggered_updates_integrated_without_clamping_negative_instantaneous_load():
    h = history()
    before = repr(h)
    result = aligned_measurements(h)
    # PV: 1200 W * 10/60 h = 200 Wh. Charge: 500 W * 15/60 h = 125 Wh.
    # First five minutes have a negative instantaneous balance; clipping it
    # would wrongly report 116.67 Wh instead of the 75 Wh interval balance.
    assert result["total_household_energy_wh"] == pytest.approx(75)
    assert result["status"] == "derived"
    assert result["strict_replay_permitted"] is False
    assert result["selection_permitted"] is False
    assert repr(h) == before


def test_negative_quarter_stays_invalid_and_is_not_zeroed():
    h = history()
    h = replace(
        h,
        series=tuple(
            replace(s, points=s.points[:1]) if s.role == "pv_generation" else s for s in h.series
        ),
    )
    result = aligned_measurements(h)
    assert result["status"] == "partial"
    assert result["total_household_energy_wh"] is None
    i = result["intervals"][0]
    assert i["household_balance_wh"] == -125
    assert i["household_energy_wh"] is None


def test_unavailable_flow_does_not_invalidate_following_recovered_quarter():
    h = history()
    h = replace(
        h,
        ends_at=START + timedelta(minutes=30),
        series=tuple(
            replace(
                s,
                points=(
                    *s.points,
                    PowerHistoryPoint(START + timedelta(minutes=10), float("nan"), "gap"),
                    PowerHistoryPoint(START + timedelta(minutes=15), 1200, "restored"),
                ),
            )
            if s.role == "pv_generation"
            else s
            for s in h.series
        ),
    )
    result = aligned_measurements(h)
    assert result["invalid_interval_count"] == 1
    assert result["derived_interval_count"] == 1
    assert result["intervals"][0]["energy_wh"]["pv_generation"] is None
    assert result["intervals"][1]["household_energy_wh"] == pytest.approx(175)
    assert result["total_household_energy_wh"] is None


def test_partial_quarters_use_exact_times_and_unchanged_states_remain_valid():
    h = history()
    h = replace(h, starts_at=START + timedelta(minutes=7), ends_at=START + timedelta(minutes=20))
    result = aligned_measurements(h)
    assert len(result["intervals"]) == 2
    assert result["total_household_energy_wh"] == pytest.approx(700 * 13 / 60)


def test_no_missing_anchor_or_duplicate_role_can_be_silently_used():
    h = history()
    unanchored = replace(h, starts_at=START - timedelta(seconds=1))
    assert aligned_measurements(unanchored)["intervals"][0]["status"] == "invalid"
    ambiguous = replace(h, series=(*h.series, h.series[0]))
    assert aligned_measurements(ambiguous)["reason"] == "missing_or_ambiguous_flow_series"
    assert aligned_measurements(replace(h, error="TimeoutError"))["status"] == "unavailable"
