"""User market conditions consume the same conserved physics and settlement."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_independent_daily_simulator import _household, _storage, _timeline

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.domain.market_user_rule import (
    MarketPricePart,
    MarketPriceWindow,
    MarketSpreadEvidence,
    MarketUserRule,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_intent_simulator import IndependentDailyIntentSimulator
from picot.planner.market_route_admission import MarketRecoverySegment, assess_market_route

AT = datetime(2026, 9, 9, 12, tzinfo=UTC)


def inputs(*, recovery=False, pv=False, soc=1.0, export_target=1200.0, load=600.0):
    h = _household()
    h = replace(
        h,
        created_at=AT,
        horizon_start=AT,
        horizon_end=AT + timedelta(hours=3),
        intervals=tuple(
            replace(
                h.intervals[0],
                starts_at=AT + timedelta(hours=n),
                ends_at=AT + timedelta(hours=n + 1),
                expected_energy_wh=load,
            )
            for n in range(3)
        ),
    )
    scenarios = []
    for scenario in PVScenario:
        p = _timeline(scenario)
        scenarios.append(
            replace(
                p,
                timeline=replace(
                    p.timeline,
                    created_at=AT,
                    horizon_start=h.horizon_start,
                    horizon_end=h.horizon_end,
                    intervals=tuple(
                        replace(
                            p.timeline.intervals[0],
                            starts_at=i.starts_at,
                            ends_at=i.ends_at,
                            energy_wh=3000.0 if pv and n == 1 else 0,
                        )
                        for n, i in enumerate(h.intervals)
                    ),
                ),
            )
        )

    def projection(trade):
        schedule = DailyReferenceIntentSchedule(
            "trade" if trade else "baseline",
            "snapshot",
            h.horizon_start,
            h.horizon_end,
            tuple(
                DailyReferenceIntentInterval(
                    i.starts_at,
                    i.ends_at,
                    DailyStorageIntent.STORAGE_EXPORT
                    if trade and n == 0
                    else DailyStorageIntent.NOM
                    if pv and n == 1
                    else DailyStorageIntent.GRID_REQUIREMENT
                    if n == 1
                    else DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
                    export_target if trade and n == 0 else 0,
                )
                for n, i in enumerate(h.intervals)
            ),
            "test",
        )
        return IndependentDailyIntentSimulator().simulate_planning_basis(
            snapshot_id="snapshot",
            household=h,
            pv_scenarios=tuple(scenarios),
            storage_state=replace(_storage(soc), measured_at=AT),
            conversion_model=StorageConversionModel("model", 1, 1, ("efficiency",), "test"),
            intent_schedule=schedule,
            minimum_storage_energy_wh=816,
            target_storage_energy_wh=8160,
            maximum_charge_input_power_w=2400,
            maximum_discharge_output_power_w=2400,
        )

    rule = MarketUserRule("market", 1, 1200 / 8160, 0.2, recovery)
    assignment = MarketDailyAssignment(rule, "battery", AT.date(), "UTC", AT, 8160)
    spread = MarketSpreadEvidence(
        "market",
        1,
        "snapshot",
        1200,
        "model",
        ("efficiency",),
        2400,
        2400,
        MarketPriceWindow(
            (MarketPricePart(AT, AT + timedelta(hours=1), 1200, 0.6, ("price",)),), False
        ),
        MarketPriceWindow(
            (
                MarketPricePart(
                    AT + timedelta(hours=1), AT + timedelta(hours=1.5), 1200, 0.1, ("price",)
                ),
            ),
            True,
        ),
        0.2,
    )
    tariffs = DailyReferenceTariffSchedule(
        "tariffs",
        "snapshot",
        h.horizon_start,
        h.horizon_end,
        tuple(
            DailyReferenceTariffInterval(
                i.starts_at, i.ends_at, 0.1, 0.6 if n == 0 else 0.4 if pv else 0.1, 1, ("price",)
            )
            for n, i in enumerate(h.intervals)
        ),
        "test",
    )
    return dict(
        assignment=assignment,
        spread=spread,
        baseline=projection(False),
        proposed=projection(True),
        minimum_storage_energy_wh=816,
        tariffs=tariffs,
        recovery_segments=(
            MarketRecoverySegment(
                "original-main", AT + timedelta(hours=1), AT + timedelta(hours=2), 8160
            ),
        ),
    )


def test_recovery_off_does_not_require_future_prices_or_recovery_proof():
    args = inputs()
    args.update(tariffs=None, recovery_segments=())
    result = assess_market_route(**args)
    assert result.status == "admissible"
    assert result.net_margin_eur_per_export_kwh is None


def test_recovery_on_requires_real_future_goal_and_prices():
    args = inputs(recovery=True)
    assert (
        assess_market_route(**(args | {"recovery_segments": ()})).status == "insufficient_evidence"
    )
    assert (
        assess_market_route(**(args | {"tariffs": None})).reason
        == "actual_recovery_prices_unavailable"
    )


def test_grid_recovery_and_wear_are_counted_once():
    result = assess_market_route(**inputs(recovery=True), wear_eur_per_export_kwh=0.05)
    assert result.status == "admissible"
    assert result.recovery_assignment_id == "original-main"
    assert result.incremental_cash_eur == pytest.approx(0.6)
    assert result.incremental_net_profit_eur == pytest.approx(0.54)
    assert result.net_margin_eur_per_export_kwh == pytest.approx(0.45)


def test_pv_recovery_uses_lost_export_not_fictitious_import_cost():
    result = assess_market_route(**inputs(recovery=True, pv=True))
    assert result.status == "admissible"
    assert result.incremental_cash_eur == pytest.approx(0.24)
    assert result.net_margin_eur_per_export_kwh == pytest.approx(0.2)


@pytest.mark.parametrize("parameters", [{"soc": 0.15}, {"load": 2000}])
def test_soc_or_shared_power_shortage_does_not_shrink_requested_volume(parameters):
    result = assess_market_route(**inputs(**parameters))
    assert result.status == "rejected"
    assert result.reason == "requested_export_not_physically_deliverable"
    assert result.expected_export_wh < 1200


def test_recovery_full_but_margin_insufficient_is_rejected():
    result = assess_market_route(**inputs(recovery=True), wear_eur_per_export_kwh=0.48)
    assert result.status == "rejected"
    assert result.reason == "recovery_net_margin_not_met"


def test_price_condition_remains_separate_with_recovery_off():
    args = inputs()
    args["assignment"] = replace(
        args["assignment"], rule=replace(args["assignment"].rule, minimum_spread_eur_per_kwh=0.8)
    )
    args["spread"] = replace(args["spread"], minimum_spread_eur_per_kwh=0.8)
    assert assess_market_route(**args).reason == "user_spread_not_met"


def test_exact_execution_duration_accounts_for_household_share():
    from picot.planner.mep_candidate_outcomes import _execution_path_intervals

    args = inputs()
    proposed = args["proposed"]
    schedule = DailyReferenceIntentSchedule(
        proposed.intent_schedule_id,
        proposed.snapshot_id,
        proposed.intervals[0].starts_at,
        proposed.intervals[-1].ends_at,
        tuple(
            DailyReferenceIntentInterval(
                i.starts_at,
                i.ends_at,
                DailyStorageIntent.STORAGE_EXPORT
                if n == 0
                else DailyStorageIntent.GRID_REQUIREMENT
                if n == 1
                else DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
                1200 if n == 0 else 0,
            )
            for n, i in enumerate(proposed.intervals)
        ),
        "test",
    )
    pieces = _execution_path_intervals(
        schedule, maximum_discharge_output_power_w=2400, projection=proposed
    )
    export = pieces[0]
    # At 600W household demand, 1800W remains for grid export: 1200Wh takes 40 minutes.
    assert export.ends_at - export.starts_at == timedelta(minutes=40)
    assert pieces[1].intent is DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
    assert sum((p.ends_at - p.starts_at).total_seconds() for p in pieces) == 3 * 3600
    assert (2400 - 600) * (export.ends_at - export.starts_at).total_seconds() / 3600 == 1200
