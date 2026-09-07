from dataclasses import replace
from datetime import date

import pytest
from test_independent_daily_intent_simulator import _schedule
from test_independent_daily_simulator import START, _household, _storage, _timeline

from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from picot.planner.independent_daily_intent_simulator import IndependentDailyIntentSimulator
from picot.v2.daily_charge_assignment import DailyChargeAssignment


def inputs(soc=0.5, lower=0.0, central=2000.0):
    scenarios = tuple(
        replace(
            _timeline(s),
            timeline=replace(
                _timeline(s).timeline,
                intervals=tuple(
                    replace(
                        i,
                        energy_wh=(
                            lower
                            if s is PVScenario.LOWER
                            else central
                            if s is PVScenario.CENTRAL
                            else central * 2
                        ),
                        confidence=0.02,
                    )
                    for i in _timeline(s).timeline.intervals
                ),
            ),
        )
        for s in PVScenario
    )
    return dict(
        snapshot_id="snapshot-intent",
        household=_household(),
        pv_scenarios=scenarios,
        storage_state=_storage(soc),
        conversion_model=StorageConversionModel(
            model_id="conversion",
            charge_efficiency=1,
            discharge_efficiency=1,
            evidence_ids=("conversion",),
            method_version="test:v1",
        ),
        minimum_storage_energy_wh=816,
        target_storage_energy_wh=8160,
        maximum_charge_input_power_w=2400,
        maximum_discharge_output_power_w=2400,
    )


def test_midpoint_is_simulated_before_charge_power_clipping():
    data = inputs()
    projection = IndependentDailyIntentSimulator().simulate_planning_basis(
        **data, intent_schedule=_schedule(Intent.NOM)
    )
    first = projection.intervals[0]
    # (0 + 2000)/2 PV, minus 100 Wh house = 900 Wh stored. Averaging
    # already-clipped LOWER/CENTRAL trajectories instead gives only 550 Wh.
    assert first.usable_pv_wh == 1000
    assert first.storage_energy_at_end_wh == 4080 + 900
    assert projection.basis_method == "pv-lower-central-arithmetic-midpoint:v1"
    assert data["pv_scenarios"][0].timeline.intervals[0].energy_wh == 0


def discover(**overrides):
    data = inputs(**overrides)
    # The final part of a delivery day; exact day coverage is tested through
    # the input adapter separately. Horizon remains the full physical timeline.
    assignment = DailyChargeAssignment("battery", date(2026, 8, 23), "UTC", START)
    return IndependentDailyChargeWindowDiscoverer().discover_main_charge(
        **data, assignment=assignment
    )


def test_only_routes_reaching_full_inside_their_main_segments_are_admitted():
    result = discover()
    assert result.windows
    for window in result.windows:
        interval = next(i for i in window.projection.intervals if i.ends_at == window.reached_at)
        assert interval.storage_energy_at_end_wh == pytest.approx(8160)
        assert any(s.starts_at <= window.reached_at <= s.ends_at for s in window.main_segments)
        assert window.assignment_id == result.assignment_id


def test_no_pv_still_exposes_each_feasible_grid_start():
    result = discover(lower=0, central=0)
    assert result.windows
    starts = {w.main_segments[0].starts_at for w in result.windows}
    assert START in starts
    assert len(starts) > 1
    assert all(w.family == "grid" for w in result.windows)


def test_pv_only_feasible_uses_no_grid():
    result = discover(soc=0.8)
    assert result.windows
    assert all(w.family == "pv" for w in result.windows)
    assert all(
        sum(i.grid_to_storage_input_wh for i in w.projection.intervals) == 0 for w in result.windows
    )


def test_small_gap_is_not_suppressed_for_uncompleted_daily_goal():
    assert discover(soc=0.995, lower=0, central=0).windows


def test_full_at_main_start_needs_no_artificial_discharge():
    result = discover(soc=1, lower=0, central=0)
    assert any(
        w.main_segments[0].starts_at == START and w.reached_at == START for w in result.windows
    )


def test_hybrid_keeps_grid_start_inside_pv_window_available():
    result = discover(lower=200, central=200)
    assert result.windows
    assert all(w.family == "hybrid" for w in result.windows)
    assert any(
        s.starts_at == START and s.intent is Intent.GRID_REQUIREMENT
        for w in result.windows
        for s in w.main_segments
    )
    for window in result.windows:
        for segment in window.main_segments:
            if segment.intent is Intent.GRID_REQUIREMENT:
                assert all(
                    i.intent is Intent.GRID_REQUIREMENT
                    for i in window.schedule.intervals
                    if segment.starts_at <= i.starts_at < segment.ends_at
                )


def test_technical_maximum_below_full_is_explicitly_unreachable():
    data = inputs()
    data["target_storage_energy_wh"] = 7752
    result = IndependentDailyChargeWindowDiscoverer().discover_main_charge(
        **data, assignment=DailyChargeAssignment("battery", START.date(), "UTC", START)
    )
    assert result.status == "unreachable"
    assert result.reason == "configured_maximum_conflicts_with_daily_100_percent"
    assert not result.windows


def test_insufficient_remaining_power_is_not_admitted():
    data = inputs(soc=0.1, lower=0, central=0)
    data["maximum_charge_input_power_w"] = 100
    result = IndependentDailyChargeWindowDiscoverer().discover_main_charge(
        **data, assignment=DailyChargeAssignment("battery", START.date(), "UTC", START)
    )
    assert result.status == "unreachable" and not result.windows


def test_retained_route_requires_optimisation_instead_of_silent_rediscovery():
    from picot.v2.daily_charge_assignment import DailyChargeRevisionReason, DailyChargeSegment

    a = DailyChargeAssignment("battery", START.date(), "UTC", START).bind_main_route(
        plan_id="existing",
        segments=(DailyChargeSegment("main", START, _household().horizon_end),),
        at=START,
        reason=DailyChargeRevisionReason.INITIAL,
        evidence_id="selection",
    )
    with pytest.raises(ValueError, match="explicit optimisation"):
        IndependentDailyChargeWindowDiscoverer().discover_main_charge(**inputs(), assignment=a)


def test_adapter_preserves_complete_published_horizon_and_other_day_segments():
    from datetime import timedelta

    from test_independent_daily_reference_adapter import _snapshot

    from picot.domain.daily_reference_intent import (
        DailyReferenceIntentInterval,
        DailyReferenceIntentSchedule,
    )
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    snapshot = _snapshot()
    start = snapshot.captured_at
    a = DailyChargeAssignment("battery", start.date(), "UTC", start)
    original = DailyReferenceIntentSchedule(
        schedule_id="retained",
        snapshot_id=snapshot.snapshot_id,
        horizon_start=start,
        horizon_end=start + timedelta(hours=24),
        intervals=tuple(
            DailyReferenceIntentInterval(
                i.starts_at,
                i.ends_at,
                Intent.GRID_REQUIREMENT
                if i.starts_at >= a.ends_at
                else Intent.HOUSEHOLD_SUPPORT_ONLY,
            )
            for i in snapshot.household_load_forecast.intervals
        ),
        method_version="test:v1",
    )
    result = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot,
        assignment=a,
        retained_schedule=original,
        conversion_model=inputs()["conversion_model"],
    )
    assert result.windows
    for window in result.windows:
        assert window.schedule.horizon_end == start + timedelta(hours=24)
        assert all(
            i == before
            for i, before in zip(window.schedule.intervals, original.intervals, strict=True)
            if i.starts_at >= a.ends_at
        )
        assert all(s.ends_at <= a.ends_at for s in window.main_segments)
        assert window.reached_at <= a.ends_at
    assert snapshot.pv_energy_timeline.intervals[0].forecast_lower_energy_wh == 800


def test_adapter_rejects_unpublished_day_and_missing_pv_ranges():
    from test_independent_daily_reference_adapter import _snapshot

    from picot.v2.independent_daily_reference_adapter import (
        DailyReferenceInputError,
        IndependentDailyReferenceAdapter,
    )

    snapshot = _snapshot()
    next_day = DailyChargeAssignment("battery", date(2026, 8, 24), "UTC", snapshot.captured_at)
    with pytest.raises(DailyReferenceInputError, match="prices_incomplete"):
        IndependentDailyReferenceAdapter().main_charge_windows(
            snapshot=snapshot, assignment=next_day, conversion_model=inputs()["conversion_model"]
        )
    a = replace(next_day, delivery_date=snapshot.captured_at.date())
    with pytest.raises(DailyReferenceInputError, match="range_incomplete"):
        IndependentDailyReferenceAdapter().main_charge_windows(
            snapshot=_snapshot(complete_range=False),
            assignment=a,
            conversion_model=inputs()["conversion_model"],
        )


def test_adapter_supports_full_36_hour_horizon_without_deadline_truncation():
    from datetime import timedelta

    from test_independent_daily_reference_adapter import _snapshot

    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    snapshot = _snapshot()
    start = snapshot.captured_at
    household = snapshot.household_load_forecast
    pv = snapshot.pv_energy_timeline
    snapshot = replace(
        snapshot,
        price_points=(replace(snapshot.price_points[0], ends_at=start + timedelta(hours=36)),),
        household_load_forecast=replace(
            household,
            intervals=tuple(
                replace(
                    household.intervals[0],
                    interval_id=f"load-{i}",
                    starts_at=start + timedelta(minutes=15 * i),
                    ends_at=start + timedelta(minutes=15 * (i + 1)),
                )
                for i in range(144)
            ),
        ),
        pv_energy_timeline=replace(
            pv,
            intervals=tuple(
                replace(
                    pv.intervals[-1],
                    interval_id=f"pv-{i}",
                    starts_at=start + timedelta(minutes=30 * i),
                    ends_at=start + timedelta(minutes=30 * (i + 1)),
                )
                for i in range(72)
            ),
        ),
    )
    a = DailyChargeAssignment("battery", date(2026, 8, 24), "Europe/Amsterdam", start)
    result = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot, assignment=a, conversion_model=inputs()["conversion_model"]
    )
    assert result.windows
    assert all(len(w.projection.intervals) == 144 for w in result.windows)
    assert all(w.schedule.horizon_end == start + timedelta(hours=36) for w in result.windows)
    assert all(
        a.starts_at <= s.starts_at < s.ends_at <= a.ends_at
        for w in result.windows
        for s in w.main_segments
    )
    # Every feasible candidate has projected reserve/grid demand before its
    # main charge too: reaching 100% never erases preceding household needs.
    assert any(
        i.grid_to_household_wh > 0
        for i in result.windows[-1].projection.intervals
        if i.starts_at < a.starts_at
    )


def dev243_snapshot_and_conversion():
    """Numerical diagnostic subset with explicit test capability metadata."""
    import json
    from datetime import datetime, timedelta
    from math import sqrt
    from pathlib import Path

    from test_independent_daily_reference_adapter import _snapshot

    data = json.loads(
        (Path(__file__).parent / "fixtures/dev243_main_charge_inputs.json").read_text()
    )
    snapshot = _snapshot(current_soc=data["soc"])
    at = datetime.fromisoformat(data["captured_at"])
    capabilities = snapshot.capability_snapshot_set
    household = snapshot.household_load_forecast
    pv = snapshot.pv_energy_timeline
    snapshot = replace(
        snapshot,
        captured_at=at,
        horizon_end=at + timedelta(hours=36),
        capability_snapshot_set=replace(
            capabilities,
            captured_at=at,
            capabilities=tuple(replace(c, fresh_at=at) for c in capabilities.capabilities),
        ),
        current_storage_states=(replace(snapshot.current_storage_states[0], measured_at=at),),
        price_points=tuple(
            replace(
                snapshot.price_points[0],
                point_id=f"price-{n}",
                starts_at=datetime.fromisoformat(start),
                ends_at=datetime.fromisoformat(end),
                value_eur_per_kwh=price,
            )
            for n, (start, end, price) in enumerate(data["prices"])
        ),
        household_load_forecast=replace(
            household,
            intervals=tuple(
                replace(
                    household.intervals[0],
                    interval_id=f"load-{n}",
                    starts_at=datetime.fromisoformat(start),
                    ends_at=datetime.fromisoformat(end),
                    expected_energy_wh=energy,
                    confidence=confidence,
                )
                for n, (start, end, energy, confidence) in enumerate(data["load"])
            ),
        ),
        pv_energy_timeline=replace(
            pv,
            intervals=tuple(
                replace(
                    pv.intervals[0],
                    interval_id=f"pv-{n}",
                    starts_at=datetime.fromisoformat(start),
                    ends_at=datetime.fromisoformat(end),
                    pv_energy_wh=central,
                    forecast_lower_energy_wh=lower,
                    forecast_central_energy_wh=central,
                    forecast_upper_energy_wh=upper,
                    confidence=confidence,
                )
                for n, (start, end, lower, central, upper, confidence) in enumerate(data["pv"])
            ),
        ),
    )
    efficiency = sqrt(data["round_trip_efficiency"])
    conversion = replace(
        inputs()["conversion_model"], charge_efficiency=efficiency, discharge_efficiency=efficiency
    )
    return snapshot, conversion


def test_dev243_numeric_inputs_keep_midday_grid_charge_available():
    """Actual numeric inputs at the adapter seam, not an execution/HA replay."""
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    snapshot, conversion = dev243_snapshot_and_conversion()
    a = DailyChargeAssignment("battery", date(2026, 9, 8), "Europe/Amsterdam", snapshot.captured_at)
    result = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot, assignment=a, conversion_model=conversion
    )
    assert result.windows
    assert all(w.family == "hybrid" for w in result.windows)
    assert any(
        s.intent is Intent.GRID_REQUIREMENT
        and s.starts_at.date() == date(2026, 9, 8)
        and 9 <= s.starts_at.hour < 13
        for w in result.windows
        for s in w.main_segments
    )
    assert all(w.reached_at <= a.ends_at for w in result.windows)
    assert all(
        w.projection.intervals[0].storage_energy_at_start_wh == pytest.approx(0.91 * 8160)
        for w in result.windows
    )
    # Baseline plus a bounded binary duration search for each remaining start.
    assert result.simulation_count < 1200


def test_completed_goal_does_not_restart_price_or_forecast_discovery():
    from test_independent_daily_reference_adapter import _snapshot

    from picot.v2.daily_charge_assignment import DailyChargeRevisionReason, DailyChargeSegment
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    snapshot = _snapshot()
    at = snapshot.captured_at
    a = DailyChargeAssignment("battery", at.date(), "UTC", at).bind_main_route(
        plan_id="existing",
        segments=(DailyChargeSegment("main", at, _household().horizon_end),),
        at=at,
        reason=DailyChargeRevisionReason.INITIAL,
        evidence_id="selection",
    )
    a = a.observe_completion(
        measured_at=at,
        soc=1,
        evidence_id="actual-full",
        plan_id="existing",
        segment_id="main",
        execution_allowed=True,
    )
    result = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=replace(snapshot, price_points=(), pv_energy_timeline=None),
        assignment=a,
        conversion_model=inputs()["conversion_model"],
    )
    assert result.status == "completed"
    assert result.simulation_count == 0
    assert result.windows == ()
