"""Reserve floor is not itself shortage; power limits are not energy shortage."""

from dataclasses import replace

import pytest
from test_daily_main_charge_windows import inputs
from test_independent_daily_intent_simulator import _schedule

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.planner.independent_daily_intent_simulator import IndependentDailyIntentSimulator
from picot.v2.daily_bridge import DailyBridgeState, energy_deficits, needs_bridge_review


@pytest.mark.parametrize(
    "soc,pv,load,expected",
    [
        (0.1, 100, 100, 0),  # exactly reserve, PV covers household
        (0.1, 0, 100, 100),  # reserve protected by grid import, genuine energy shortage
        (1.0, 0, 2000, 0),  # high demand, enough energy; unavoidable power-limited import
    ],
)
def test_energy_shortage_is_separate_from_soc_floor_and_power_limit(soc, pv, load, expected):
    data = inputs(soc=soc, lower=pv, central=pv)
    household = data["household"]
    data["household"] = replace(
        household,
        intervals=tuple(
            replace(i, expected_energy_wh=load if n == 0 else 0)
            for n, i in enumerate(household.intervals)
        ),
    )
    schedule = _schedule(DailyStorageIntent.NOM)
    projection = IndependentDailyIntentSimulator().simulate_planning_basis(
        **data, intent_schedule=schedule
    )
    result = energy_deficits(
        projection, schedule, until=schedule.horizon_end, maximum_discharge_output_power_w=2400
    )
    assert result[0].deficit_wh == expected
    assert projection.intervals[0].storage_energy_at_end_wh >= 816
    if load == 2000:
        assert projection.intervals[0].grid_to_household_wh > 0
    state = DailyBridgeState("next-owner", "active-plan", schedule.horizon_end, result)
    assert not needs_bridge_review(
        result, state, plan_id="active-plan", next_starts_at=schedule.horizon_end
    )
    increased = (replace(result[0], deficit_wh=result[0].deficit_wh + 100), *result[1:])
    assert needs_bridge_review(
        increased, state, plan_id="active-plan", next_starts_at=schedule.horizon_end
    )
