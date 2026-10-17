"""The daily full-charge obligation must not end later PV self-consumption."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_charge_windows import inputs
from test_independent_daily_simulator import START

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
)
from picot.domain.daily_reference_intent import (
    DailyStorageIntent as Intent,
)
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from picot.v2.daily_charge_assignment import DailyChargeAssignment


def late_pv_inputs(soc=0.9):
    data = inputs(soc=soc, lower=0, central=0)
    # First half-hour reaches full using the grid; house demand then creates
    # room for 400 Wh PV surplus in each of two later half-hours.
    data["pv_scenarios"] = tuple(replace(s, timeline=replace(
        s.timeline, intervals=tuple(replace(i, energy_wh=500 if n in (5, 7) else 0)
                                    for n, i in enumerate(s.timeline.intervals)),
    )) for s in data["pv_scenarios"])
    return data


def first_window(data, **kwargs):
    result = IndependentDailyChargeWindowDiscoverer().discover_main_charge(
        **data, assignment=DailyChargeAssignment("battery", START.date(), "UTC", START),
        **kwargs,
    )
    return next(w for w in result.windows if w.main_segments[0].starts_at == START)


@pytest.mark.parametrize("soc", [0.9, 1.0])
def test_later_surplus_is_captured_without_extending_daily_obligation(soc):
    data = late_pv_inputs(soc)
    window = first_window(data)
    assert window.reached_at <= data["household"].intervals[0].ends_at
    assert all(s.ends_at <= data["household"].intervals[0].ends_at
               for s in window.main_segments)
    assert window.schedule.intervals[5].intent is Intent.NOM
    assert window.schedule.intervals[7].intent is Intent.NOM
    assert window.projection.intervals[5].pv_to_storage_input_wh == pytest.approx(400)
    assert window.projection.intervals[7].pv_to_storage_input_wh == pytest.approx(
        100 if soc == 0.9 else 200)
    assert window.schedule.intervals[6].intent is Intent.HOUSEHOLD_SUPPORT_ONLY
    assert all(i.grid_to_storage_input_wh == 0 for i in window.projection.intervals[1:])


@pytest.mark.parametrize("intent", [Intent.STANDBY, Intent.GRID_REQUIREMENT, Intent.STORAGE_EXPORT])
def test_later_existing_actions_are_not_replaced(intent):
    data = late_pv_inputs(soc=1.0)
    h = data["household"]
    schedule = DailyReferenceIntentSchedule(
        "retained", data["snapshot_id"], h.horizon_start, h.horizon_end,
        tuple(DailyReferenceIntentInterval(i.starts_at, i.ends_at,
              intent if n == 5 else Intent.HOUSEHOLD_SUPPORT_ONLY,
              storage_export_target_wh=100 if n == 5 and intent is Intent.STORAGE_EXPORT else 0)
              for n, i in enumerate(h.intervals)), "test:v1",
    )
    window = first_window(data, retained_schedule=schedule)
    assert window.schedule.intervals[5].intent is intent
    assert window.schedule.intervals[7].intent is Intent.NOM


def test_protected_pv_interval_is_not_replaced():
    data = late_pv_inputs()
    protected = data["household"].intervals[5]
    window = first_window(data, protected_intervals=((protected.starts_at, protected.ends_at),))
    assert window.schedule.intervals[5].intent is Intent.HOUSEHOLD_SUPPORT_ONLY
    assert window.schedule.intervals[7].intent is Intent.NOM


def test_ev_consumption_does_not_become_storage_surplus():
    data = late_pv_inputs(soc=1.0)
    data["household"] = replace(data["household"], intervals=tuple(
        replace(i, expected_energy_wh=600, battery_excluded_energy_wh=500)
        if n == 5 else i for n, i in enumerate(data["household"].intervals)))
    window = first_window(data)
    assert window.schedule.intervals[5].intent is Intent.HOUSEHOLD_SUPPORT_ONLY
    assert window.projection.intervals[5].pv_to_storage_input_wh == 0
    assert window.schedule.intervals[7].intent is Intent.NOM


@pytest.mark.parametrize("basis,expected", [
    ("lower", Intent.HOUSEHOLD_SUPPORT_ONLY),
    ("mean-lower-central", Intent.HOUSEHOLD_SUPPORT_ONLY),
    ("central", Intent.NOM), ("upper", Intent.NOM),
])
def test_post_goal_capture_uses_selected_forecast_basis(basis, expected):
    data = late_pv_inputs(soc=1.0)
    data["pv_scenarios"] = tuple(replace(s, planning_basis=basis, timeline=replace(
        s.timeline, intervals=tuple(replace(i, energy_wh={
            "lower": 0, "central": 200, "upper": 400,
        }[s.scenario.value]) if n == 5 else i
            for n, i in enumerate(s.timeline.intervals)),
    )) for s in data["pv_scenarios"])
    assert first_window(data).schedule.intervals[5].intent is expected


def test_pipeline_recalculation_retains_post_goal_capture_and_main_ownership(tmp_path, monkeypatch):
    from test_daily_main_active_pipeline import setup
    from test_daily_main_charge_selection import snapshot_for_main
    from test_daily_main_route_optimisation import fresh

    from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = snapshot_for_main()
    source = replace(source,
        price_points=(
            replace(source.price_points[0], point_id="cheap-early",
                    ends_at=source.captured_at + timedelta(hours=1), value_eur_per_kwh=0.10),
            replace(source.price_points[0], point_id="expensive-later",
                    starts_at=source.captured_at + timedelta(hours=1), value_eur_per_kwh=0.60),
        ),
        current_storage_states=tuple(replace(s, current_soc=0.9)
                                     for s in source.current_storage_states),
        pv_energy_timeline=replace(source.pv_energy_timeline, intervals=tuple(
            replace(p, pv_energy_wh=500 if n in (5, 7) else 0,
                    forecast_lower_energy_wh=500 if n in (5, 7) else 0,
                    forecast_central_energy_wh=500 if n in (5, 7) else 0,
                    forecast_upper_energy_wh=500 if n in (5, 7) else 0)
            for n, p in enumerate(source.pv_energy_timeline.intervals))),
    )
    first = pipeline.run(planning_input=recover(source))
    assert first.execution_plan_set.plans, first.evaluation.reason
    source = fresh(source, tag="post-goal-rebuild")
    store.request_daily_recalculation(request_id="post-goal", requested_at=source.captured_at)
    rebuilt = pipeline.run(planning_input=recover(source))
    assert store.daily_recalculation_status()["status"] == "completed"
    plan = rebuilt.execution_plan_set.plans[0]
    day = next(a for a in store.load_daily_assignments()
               if a.delivery_date == source.captured_at.date())
    last_main = max(s.ends_at for s in day.main_segments)
    captures = [s for s in plan.segments if s.starts_at >= last_main
                and s.primitive is Primitive.BALANCE_BIDIRECTIONAL]
    assert captures
    assert all(s.main_assignment_id is None for s in captures)
    projection, _ = IndependentDailyReferenceAdapter().committed_plan_projection(
        snapshot=recover(source), plan=plan, conversion_model=inputs()["conversion_model"],
    )
    assert sum(i.pv_to_storage_input_wh for i in projection.intervals
               if i.starts_at >= last_main) > 0
    saved = store._path.read_bytes()
    again = pipeline.run(planning_input=recover(source))
    assert again.execution_plan_set.plans[0] == plan
    assert store._path.read_bytes() == saved
