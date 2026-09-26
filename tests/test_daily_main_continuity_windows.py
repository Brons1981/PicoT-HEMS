"""Physical bounds on continuing an already protected charging action."""

from test_daily_main_charge_windows import inputs
from test_independent_daily_intent_simulator import _schedule
from test_independent_daily_simulator import INTERVAL, START

from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from picot.v2.daily_charge_assignment import DailyChargeAssignment


def test_predicted_full_does_not_shorten_the_protected_prefix():
    end = START + 2 * INTERVAL
    result = IndependentDailyChargeWindowDiscoverer().discover_main_charge(
        **inputs(soc=0.99, lower=0, central=0),
        assignment=DailyChargeAssignment("battery", START.date(), "UTC", START),
        required_grid_until=end,
    )
    window, = result.windows
    assert window.reached_at < end
    assert window.main_segments[0].ends_at == end
    assert all(i.intent is Intent.GRID_REQUIREMENT for i in window.schedule.intervals
               if i.starts_at < end)


def test_continuity_does_not_overwrite_protected_foreign_intervals():
    result = IndependentDailyChargeWindowDiscoverer().discover_main_charge(
        **inputs(soc=0.99),
        assignment=DailyChargeAssignment("battery", START.date(), "UTC", START),
        required_grid_until=START + 2 * INTERVAL,
        protected_intervals=((START + INTERVAL, START + 2 * INTERVAL),),
    )
    assert not result.windows
    assert result.reason == "required_grid_continuity_not_covered"


def test_continuity_cannot_make_insufficient_charging_capacity_feasible():
    data = inputs(soc=0.1, lower=0, central=0)
    data["maximum_charge_input_power_w"] = 100
    result = IndependentDailyChargeWindowDiscoverer().discover_main_charge(
        **data,
        assignment=DailyChargeAssignment("battery", START.date(), "UTC", START),
        required_grid_until=START + INTERVAL,
        retained_schedule=_schedule(Intent.HOUSEHOLD_SUPPORT_ONLY),
    )
    assert not result.windows
    assert result.status == "unreachable"
