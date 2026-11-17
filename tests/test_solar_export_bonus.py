import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest
from test_financial_result_ledger import _history, _ledger, _snapshot
from test_independent_daily_tariff_adapter import _snapshot as tariff_snapshot

from picot.domain.solar_export_bonus import SolarExportBonusContext, SolarExportBonusPolicy
from picot.planner.solar_export_bonus import SolarBonusAllowance, bonus_rate, daylight
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.solar_export_bonus_evidence import SolarExportBonusEvidence

START = datetime(2026, 8, 27, 10, tzinfo=UTC)


def policy(used=1000.0, at=START):
    return SolarExportBonusPolicy(True, at, 51.645, 4.60, used, at)


def context(remaining=6500.0):
    return SolarExportBonusContext(policy(), START, ((2026, remaining),), ("baseline",))


@pytest.mark.parametrize(
    "field,value",
    [
        ("latitude", None),
        ("longitude", float("nan")),
        ("annual_exported_kwh", True),
        ("annual_exported_kwh", -1),
        ("latitude", 100),
    ],
)
def test_bad_policy_rejected(field, value):
    with pytest.raises(ValueError):
        replace(policy(), **{field: value})


def test_bonus_is_ten_percent_of_positive_export_only():
    assert bonus_rate(context(), START, START + timedelta(hours=1), 0.20) == pytest.approx(0.02)
    assert bonus_rate(context(), START, START + timedelta(hours=1), -0.20) == 0
    assert bonus_rate(context(), START, START + timedelta(hours=1), 0) == 0
    night = START.replace(hour=0)
    assert bonus_rate(context(), night, night + timedelta(hours=1), 0.20) == 0


def test_daylight_boundary_uses_fraction_and_activation():
    rise, _ = daylight(policy(), START.date())
    ctx = replace(context(), policy=replace(policy(), effective_from=START.replace(hour=0)))
    assert bonus_rate(
        ctx, rise - timedelta(minutes=5), rise + timedelta(minutes=5), 0.20
    ) == pytest.approx(0.01)


def test_allowance_is_quantity_limited_and_independent_per_path():
    allowance = SolarBonusAllowance(context(0.5))
    assert allowance.value(START, START + timedelta(minutes=15), 0.75, 0.02) == pytest.approx(0.01)
    assert (
        allowance.value(START + timedelta(minutes=15), START + timedelta(minutes=30), 1, 0.02) == 0
    )
    assert SolarBonusAllowance(context(0.5)).value(
        START, START + timedelta(minutes=15), 0.75, 0.02
    ) == pytest.approx(0.01)


def test_night_export_consumes_allowance_and_next_year_resets():
    a = SolarBonusAllowance(context(0.5))
    assert a.value(START, START + timedelta(minutes=15), 0.5, 0) == 0
    assert a.value(START, START + timedelta(minutes=15), 0.5, 0.02) == 0
    next_year = START.replace(year=2027)
    assert a.value(next_year, next_year + timedelta(hours=1), 1, 0.02) == pytest.approx(0.02)


def test_unknown_annual_usage_never_assumes_zero():
    ctx = replace(context(), annual_remaining_kwh=(), status="unavailable")
    assert bonus_rate(ctx, START, START + timedelta(hours=1), 0.20) == 0
    assert SolarBonusAllowance(ctx).value(START, START + timedelta(hours=1), 1, 0.02) == 0


@pytest.mark.parametrize("year", [2026, 2027])
def test_adapter_adds_bonus_without_bonus_on_energy_tax(year):
    start = START.replace(year=year)
    p = policy(at=start)
    ctx = SolarExportBonusContext(p, start, ((year, 6500),), ("baseline",))
    snap = tariff_snapshot(start)
    adapter = IndependentDailyTariffAdapter()
    before = adapter.build(snap).intervals[0]
    after = adapter.build(replace(snap, solar_export_bonus=ctx)).intervals[0]
    expected = before.cross_interval_export_eur_per_kwh * 0.1
    assert after.export_eur_per_kwh - before.export_eur_per_kwh == pytest.approx(expected)
    assert after.saldering_tax_eur_per_kwh == before.saldering_tax_eur_per_kwh
    assert after.import_eur_per_kwh == before.import_eur_per_kwh


def test_raw_export_tracker_persists_and_conservatively_bounds_gap(tmp_path):
    path = tmp_path / "bonus.json"
    e = SolarExportBonusEvidence(path)
    e.configure(policy(7498))
    e.observe(_history(grid_export=1000))
    end = START + timedelta(hours=1)
    assert e.context(end).annual_remaining_kwh == ((2026, 1.0),)
    restored = SolarExportBonusEvidence(path)
    restored.configure(policy(7498))
    assert restored.context(end).annual_remaining_kwh == ((2026, 1.0),)
    bounded = restored.context(end + timedelta(minutes=15), maximum_unobserved_export_power_w=2000)
    assert bounded.annual_remaining_kwh == ((2026, 0.5),)
    assert bounded.reason == "bounded_unobserved_export"
    assert restored.context(end + timedelta(minutes=15)).status == "unavailable"


def test_inferred_export_cannot_update_planning_allowance(tmp_path):
    e = SolarExportBonusEvidence(tmp_path / "bonus.json")
    e.configure(policy(7498))
    e.observe(replace(_history(grid_export=1000), method_version="financial-inferred:v1"))
    assert e.context(START).annual_remaining_kwh == ((2026, 2),)
    assert e.context(START + timedelta(hours=1)).status == "unavailable"


def test_new_year_can_restart_raw_allowance_without_prior_year_gap(tmp_path):
    tracker = SolarExportBonusEvidence(tmp_path / "bonus.json")
    tracker.configure(policy(7499))
    history = _history(grid_export=1000)
    shift = datetime(2026, 12, 31, 23, tzinfo=UTC) - START
    history = replace(
        history,
        starts_at=history.starts_at + shift,
        ends_at=history.ends_at + shift,
        series=tuple(
            replace(s, points=tuple(replace(p, sampled_at=p.sampled_at + shift) for p in s.points))
            for s in history.series
        ),
    )
    tracker.observe(history)
    assert tracker.context(history.ends_at).annual_remaining_kwh == ((2027, 7499),)


def test_measured_bonus_uses_cap_and_metrics_match_ledger(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.configure_solar_export_bonus(policy(7499.5))
    history = _history(
        pv_generation=1000,
        household_load=0,
        grid_import=0,
        grid_export=1000,
        battery_charge=0,
        battery_discharge=0,
    )
    ledger.observe_solar_export_bonus(history)
    today = ledger.update(_snapshot(), history)["today"]
    # Base import .25; supplier export .1391506; half a kWh has bonus.
    bonus = 0.5 * (0.25 - (0.09161 + 0.01653) * 1.21 + 0.02) * 0.1
    assert today["solar_export_bonus_eur"] == pytest.approx(round(bonus, 4))
    assert today["grid_export_revenue_eur"] == pytest.approx(round(0.25 + bonus, 4))
    assert (
        today["financial_metrics"]["values"]["grid_export_revenue_eur"]["value_eur"]
        == today["grid_export_revenue_eur"]
    )


def test_wear_change_preserves_earlier_half_hour_and_restart(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.configure_wear(0.01, START + timedelta(minutes=30))
    history = _history(
        pv_generation=0,
        household_load=1000,
        grid_import=0,
        grid_export=0,
        battery_charge=0,
        battery_discharge=1000,
    )
    today = ledger.update(_snapshot(), history)["today"]
    assert today["battery_wear_eur"] == pytest.approx(0.03)
    assert today["financial_metrics"]["values"]["battery_wear_eur"]["value_eur"] == pytest.approx(
        0.03
    )
    restored = _ledger(tmp_path)
    restored.configure_wear(0.01, START + timedelta(hours=1))
    assert restored.update(_snapshot(), history)["today"]["battery_wear_eur"] == pytest.approx(0.03)


def test_planning_settlement_caps_bonus_on_every_independent_path():
    from test_independent_daily_financial_settlement import _tariffs
    from test_independent_daily_simulator import _simulate

    from picot.planner.independent_daily_financial_settlement import (
        IndependentDailyFinancialSettlement,
    )

    simulation = _simulate()
    tariffs = _tariffs()
    p = policy(at=tariffs.horizon_start)
    ctx = SolarExportBonusContext(p, tariffs.horizon_start, ((2026, 0.1),), ("baseline",))
    bonus_tariffs = replace(
        tariffs,
        solar_export_bonus=ctx,
        intervals=tuple(
            replace(t, export_eur_per_kwh=t.export_eur_per_kwh + 0.02, solar_bonus_eur_per_kwh=0.02)
            for t in tariffs.intervals
        ),
    )
    settlement = IndependentDailyFinancialSettlement()
    before = settlement.settle(simulation=simulation, tariffs=tariffs)
    after = settlement.settle(simulation=simulation, tariffs=bonus_tariffs)
    for old, new, physical in zip(before.paths, after.paths, simulation.trajectories, strict=True):
        exported = (
            sum(x.pv_to_grid_wh + x.storage_to_grid_output_wh for x in physical.intervals) / 1000
        )
        assert new.grid_export_result_eur - old.grid_export_result_eur == pytest.approx(
            min(exported, 0.1) * 0.02
        )


def test_disabling_bonus_does_not_remove_previously_earned_half_hour(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.configure_solar_export_bonus(policy())
    half = START + timedelta(minutes=30)
    ledger.configure_solar_export_bonus(replace(policy(), enabled=False, effective_from=half))
    history = _history(
        pv_generation=1000,
        household_load=0,
        grid_import=0,
        grid_export=1000,
        battery_charge=0,
        battery_discharge=0,
    )
    ledger.observe_solar_export_bonus(history)
    today = ledger.update(_snapshot(), history)["today"]
    expected = 0.5 * (0.25 - (0.09161 + 0.01653) * 1.21 + 0.02) * 0.1
    assert today["solar_export_bonus_eur"] == pytest.approx(round(expected, 4))


def test_corrupt_bonus_sidecar_does_not_interrupt_ordinary_accounting(tmp_path):
    path = tmp_path / "bonus.json"
    path.write_text("not json")
    evidence = SolarExportBonusEvidence(path)
    evidence.configure(policy())
    assert evidence.context(START + timedelta(days=3)).status == "unavailable"


@pytest.mark.parametrize(
    "corruption", ["cursor", "exported_kwh", "openings", "before_anchor", "wrong_year", "archive"]
)
def test_incomplete_matching_policy_sidecar_cannot_interrupt_planning(tmp_path, corruption):
    path = tmp_path / "bonus.json"
    state = {
        "policy": json.dumps(asdict(policy()), default=str, sort_keys=True),
        "cursor": START.isoformat(),
        "exported_kwh": 1000,
        "openings": {},
    }
    if corruption == "before_anchor":
        state["cursor"] = (START - timedelta(days=1)).isoformat()
    elif corruption == "wrong_year":
        state["cursor"] = START.replace(year=2027).isoformat()
    elif corruption == "archive":
        state["archives"] = [{}]
    else:
        del state[corruption]
    path.write_text(json.dumps(state))
    evidence = SolarExportBonusEvidence(path)
    evidence.configure(policy())
    ctx = evidence.context(START + timedelta(hours=1))
    assert ctx.status == "unavailable"
    assert ctx.reason == "annual_export_coverage_incomplete"
    assert evidence.context(START).annual_remaining_kwh == ((2026, 6500),)


def test_bonus_uses_export_register_not_quarter_import_offset():
    from picot.domain.daily_reference_simulation import DailyReferenceInterval
    from picot.domain.daily_reference_tariff import DailyReferenceTariffInterval
    from picot.planner.independent_daily_financial_settlement import (
        IndependentDailyFinancialSettlement,
    )

    end = START + timedelta(minutes=15)
    physical = DailyReferenceInterval(
        START,
        end,
        household_demand_wh=500,
        usable_pv_wh=1000,
        pv_to_household_wh=0,
        pv_to_storage_input_wh=0,
        pv_to_grid_wh=1000,
        grid_to_household_wh=500,
        grid_to_storage_input_wh=0,
        storage_to_household_output_wh=0,
        storage_charge_loss_wh=0,
        storage_discharge_loss_wh=0,
        storage_energy_at_start_wh=1000,
        storage_energy_at_end_wh=1000,
        confidence=1,
        evidence_ids=("physical",),
    )
    base = DailyReferenceTariffInterval(START, end, 0.30, 0.20, 1, ("tariff",))
    bonus = replace(base, export_eur_per_kwh=0.22, solar_bonus_eur_per_kwh=0.02)
    settle = IndependentDailyFinancialSettlement()
    before = settle._settle_intervals(
        (physical,), tariffs_by_physical_interval={(START, end): (base,)}
    )
    after = settle._settle_intervals(
        (physical,),
        tariffs_by_physical_interval={(START, end): (bonus,)},
        solar_export_bonus=context(),
    )
    assert after[0].grid_export_result_eur - before[0].grid_export_result_eur == pytest.approx(0.02)


def test_two_pv_charge_intervals_share_one_counterfactual_allowance():
    from test_independent_daily_simulator import _timeline

    from picot.domain.daily_reference_simulation import (
        DailyPlanningProjection,
        DailyReferenceInterval,
        PVScenario,
    )
    from picot.domain.daily_reference_tariff import (
        DailyReferenceTariffInterval,
        DailyReferenceTariffSchedule,
    )
    from picot.planner.independent_daily_financial_settlement import (
        IndependentDailyFinancialSettlement,
    )

    intervals = tuple(
        DailyReferenceInterval(
            START + timedelta(minutes=30 * n),
            START + timedelta(minutes=30 * (n + 1)),
            household_demand_wh=0,
            usable_pv_wh=1000,
            pv_to_household_wh=0,
            pv_to_storage_input_wh=1000,
            pv_to_grid_wh=0,
            grid_to_household_wh=0,
            grid_to_storage_input_wh=0,
            storage_to_household_output_wh=0,
            storage_charge_loss_wh=0,
            storage_discharge_loss_wh=0,
            storage_energy_at_start_wh=1000 + 1000 * n,
            storage_energy_at_end_wh=2000 + 1000 * n,
            confidence=1,
            evidence_ids=("physical",),
        )
        for n in range(2)
    )
    template = _timeline(PVScenario.CENTRAL).timeline
    timeline = replace(
        template,
        horizon_start=START,
        horizon_end=intervals[-1].ends_at,
        intervals=tuple(
            replace(template.intervals[0], starts_at=i.starts_at, ends_at=i.ends_at, energy_wh=1000)
            for i in intervals
        ),
    )
    projection = DailyPlanningProjection(
        "snapshot-test", "two-pv-charges", timeline, intervals, "test"
    )
    tariffs = DailyReferenceTariffSchedule(
        "tariffs",
        projection.snapshot_id,
        START,
        intervals[-1].ends_at,
        tuple(
            DailyReferenceTariffInterval(
                i.starts_at, i.ends_at, 0.30, 0.22, 1, ("tariff",), solar_bonus_eur_per_kwh=0.02
            )
            for i in intervals
        ),
        "test",
        solar_export_bonus=context(1),
    )
    result = IndependentDailyFinancialSettlement().settle_planning_basis(
        projection=projection, tariffs=tariffs
    )
    # Two kWh stored; only one kWh could receive the 2-cent export bonus.
    assert result.acquisition_cost_eur == pytest.approx(0.42)
    assert sum(i.pv_storage_opportunity_cost_eur for i in result.intervals) == pytest.approx(0.42)


def test_measured_pv_lots_share_one_counterfactual_allowance(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.configure_solar_export_bonus(policy(7499))
    history = _history(
        pv_generation=2000,
        household_load=0,
        grid_import=0,
        grid_export=0,
        battery_charge=2000,
        battery_discharge=0,
    )
    snapshot = _snapshot()
    price = snapshot.price_points[0]
    half = START + timedelta(minutes=30)
    snapshot = replace(
        snapshot,
        price_points=(
            replace(price, ends_at=half),
            replace(price, starts_at=half, point_id="second"),
        ),
    )
    ledger.observe_solar_export_bonus(history)
    today = ledger.update(snapshot, history)["today"]
    lots = today["storage_energy_inventory"]["lots"]
    acquired = sum(lot["acquisition_cost_eur"] for lot in lots if lot["source"] == "pv")
    bonus_one_kwh = (0.25 - (0.09161 + 0.01653) * 1.21 + 0.02) * 0.1
    assert acquired == pytest.approx(0.5 + bonus_one_kwh)
