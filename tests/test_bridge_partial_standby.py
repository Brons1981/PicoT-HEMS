"""Bridge repairs must offer bounded, partial multi-price standby windows."""

from dataclasses import replace

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario

from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


@pytest.mark.parametrize("revision", [False, True])
@pytest.mark.parametrize("pv_surplus", [False, True])
def test_partial_standby_crosses_price_boundaries_without_moving_commitments(
    tmp_path, revision, pv_surplus,
):
    _, snapshot, plan = scenario(tmp_path, soc=0.65)
    snapshot = replace(snapshot, price_points=tuple(
        replace(p, value_eur_per_kwh=0.1 + n * 0.001)
        for n, p in enumerate(snapshot.price_points)))
    if pv_surplus:
        snapshot = replace(snapshot, pv_energy_timeline=replace(snapshot.pv_energy_timeline,
            intervals=tuple(replace(i, pv_energy_wh=500, forecast_lower_energy_wh=500,
                                    forecast_central_energy_wh=500, forecast_upper_energy_wh=500)
                            if n == 20 else i
                            for n, i in enumerate(snapshot.pv_energy_timeline.intervals))))
    before = (tmp_path / 'plans.json').read_bytes()
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    _, baseline = adapter.committed_plan_projection(
        snapshot=snapshot, plan=plan, conversion_model=conversion)
    trigger = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion).trigger
    assert trigger is not None
    windows = adapter.bridge_windows(snapshot=snapshot, trigger=trigger,
                                     conversion_model=conversion,
                                     revision_schedule=baseline if revision else None)
    free = [i for i in baseline.intervals if i.ends_at <= trigger.next_starts_at
            and i.intent is not Intent.STORAGE_EXPORT]
    partial = [w for w in windows.windows if
               1 < sum(i.intent is Intent.STANDBY for i in w.schedule.intervals) < len(free)
               and not any(i.intent is Intent.GRID_REQUIREMENT
                           and i.ends_at <= trigger.next_starts_at for i in w.schedule.intervals)]
    assert partial, "Only a single-price interval or full bridge standby was offered"
    for window in partial:
        changed = [n for n, (a, b) in enumerate(zip(
            baseline.intervals, window.schedule.intervals, strict=True))
            if a != b and b.intent is Intent.STANDBY]
        assert changed == list(range(changed[0], changed[-1] + 1))
        assert all(window.schedule.intervals[n].intent is Intent.STANDBY for n in changed)
        if pv_surplus:
            assert window.schedule.intervals[20].intent is not Intent.STANDBY
        # Net supply at the SOC floor is normal; a cheap block need not erase
        # every later projected energy deficit. Physical SOC bounds still hold.
        assert min(i.storage_energy_at_end_wh for i in window.projection.intervals) >= 816 - 1e-6
        for a, b in zip(baseline.intervals, window.schedule.intervals, strict=True):
            if a.starts_at >= trigger.next_starts_at or a.intent is Intent.STORAGE_EXPORT:
                assert a == b
    # Search remains bounded by starts times logarithmic lengths, not all O(n^2) spans.
    assert windows.simulation_count < 25 * len(free)
    assert (tmp_path / 'plans.json').read_bytes() == before


