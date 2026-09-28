"""Local bridge repairs preserve modes and require a household basis for standby."""

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario

from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.planner.market_revision_candidates import market_revision_windows
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


@pytest.mark.parametrize("soc,household_need", [(0.65, True), (0.9, False)])
def test_night_bridge_does_not_repaint_surroundings_or_use_standby_only_for_trade(
    tmp_path, soc, household_need,
):
    _, snapshot, plan = scenario(tmp_path, soc=soc)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    _, baseline = adapter.committed_plan_projection(
        snapshot=snapshot, plan=plan, conversion_model=conversion,
    )
    trigger = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion).trigger
    assert trigger is not None
    windows = adapter.bridge_windows(
        snapshot=snapshot, trigger=trigger, conversion_model=conversion,
        revision_schedule=baseline,
    )
    assert windows.windows
    assert not any(i.intent is Intent.NOM for w in windows.windows for i in w.schedule.intervals)
    standby = tuple(w for w in windows.windows
                    if any(i.intent is Intent.STANDBY for i in w.schedule.intervals))
    assert bool(standby) is household_need
    if household_need:
        # A single local support interval must be possible without altering the
        # household support or committed export modes around it.
        assert any(sum(a != b for a, b in zip(
            w.schedule.intervals, baseline.intervals, strict=True,
        )) == 1 for w in standby)
    for w in windows.windows:
        for before, after in zip(baseline.intervals, w.schedule.intervals, strict=True):
            if before.intent is Intent.STORAGE_EXPORT:
                assert before == after
            if after.intent is not Intent.STORAGE_EXPORT:
                assert after.storage_export_target_wh == 0


def test_removed_night_export_returns_to_household_support(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion).trigger
    windows = market_revision_windows(snapshot=snapshot, trigger=trigger,
                                      conversion_model=conversion)
    removed = tuple(w for w in windows.windows if all(
        i.intent is not Intent.STORAGE_EXPORT for i in w.schedule.intervals))
    assert removed
    assert all(i.intent is not Intent.NOM for w in removed for i in w.schedule.intervals)
