from dataclasses import replace
from datetime import timedelta

import pytest
from test_independent_daily_reference_adapter import _conversion, _snapshot

from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.domain.storage_energy_inventory import (
    StorageEnergyInventory,
    StorageEnergyLot,
)
from picot.planner.market_daily_evaluation_engine import MarketDailyEvaluationEngine
from picot.planner.market_daily_planner import MarketDailyPlanner, MarketTradingPolicy


def test_mep_trading_threshold_applies_margin_before_fixed_wear() -> None:
    policy = MarketTradingPolicy(
        margin_fraction=0.10,
        wear_eur_per_export_kwh=0.05,
    )

    assert policy.minimum_export_rate(0.131, 0.83) == pytest.approx(0.223614, abs=1e-6)


def test_mep_builds_native_plan_when_no_market_extension_applies() -> None:
    snapshot = _snapshot(maximum_soc=0.7)

    result = MarketDailyPlanner().plan(
        snapshot=snapshot,
        conversion_model=_conversion(),
    )

    assert result.planner_id == "mep"
    assert result.planner_name == "Markt Etmaal Planner"
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.native_observation.observer_only is True
    assert result.native_observation.selection_permitted is False
    assert result.market_routes == ()
    assert result.winning_source == "mep_native_plan"
    assert result.dispatch_authority is False
    assert result.reason == "no_admitted_market_route"


def test_mep_bounds_charge_candidates_before_projected_household_grid_dependency() -> None:
    """ADR-017/037: a later cheap interval cannot hide an earlier energy need."""

    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.30)
    assert snapshot.pv_energy_timeline is not None
    source = snapshot.price_points[0]
    later_cheap_start = snapshot.captured_at + timedelta(hours=12)
    dark = replace(
        snapshot,
        pv_energy_timeline=replace(
            snapshot.pv_energy_timeline,
            intervals=tuple(
                replace(
                    item,
                    pv_energy_wh=0.0,
                    forecast_lower_energy_wh=0.0,
                    forecast_central_energy_wh=0.0,
                    forecast_upper_energy_wh=0.0,
                )
                for item in snapshot.pv_energy_timeline.intervals
            ),
        ),
        price_points=(
            replace(
                source,
                point_id="current-cheap",
                ends_at=snapshot.captured_at + timedelta(hours=3),
                value_eur_per_kwh=0.13,
            ),
            replace(
                source,
                point_id="expensive-household-period",
                starts_at=snapshot.captured_at + timedelta(hours=3),
                ends_at=later_cheap_start,
                value_eur_per_kwh=0.40,
            ),
            replace(
                source,
                point_id="later-cheap",
                starts_at=later_cheap_start,
                value_eur_per_kwh=0.10,
            ),
        ),
    )

    portfolio, _ = MarketDailyPlanner().generate_with_diagnostics(
        snapshot=dark,
        conversion_model=_conversion(),
    )

    assert portfolio.required_by < later_cheap_start
    charge_intervals = tuple(
        interval
        for schedule in portfolio.native_observation.strategy_space.schedules
        for interval in schedule.intervals
        if interval.intent.value == "grid_requirement"
    )
    assert charge_intervals
    assert all(interval.ends_at <= portfolio.required_by for interval in charge_intervals)
    assert min(interval.starts_at for interval in charge_intervals) >= snapshot.captured_at
    assert max(interval.ends_at for interval in charge_intervals) <= portfolio.required_by


def test_mep_does_not_override_native_smart_discharge_during_forecast_solar() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.995)

    result = MarketDailyPlanner().plan(
        snapshot=snapshot,
        conversion_model=_conversion(),
    )

    assert result.winning_source == "mep_native_plan"
    assert result.current_intent is not None
    assert result.current_intent.value == "household_support_only"
    assert result.current_interval_ends_at == snapshot.captured_at + timedelta(minutes=15)


def test_mep_does_not_invent_nom_capture_without_forecast_solar() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.995)
    assert snapshot.pv_energy_timeline is not None
    dark = replace(
        snapshot,
        pv_energy_timeline=replace(
            snapshot.pv_energy_timeline,
            intervals=tuple(
                replace(
                    item,
                    pv_energy_wh=0.0,
                    forecast_lower_energy_wh=0.0,
                    forecast_central_energy_wh=0.0,
                    forecast_upper_energy_wh=0.0,
                )
                for item in snapshot.pv_energy_timeline.intervals
            ),
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=dark,
        conversion_model=_conversion(),
    )

    assert result.current_intent is not None
    assert result.current_intent.value == "household_support_only"
    assert result.current_interval_ends_at == snapshot.captured_at + timedelta(minutes=15)


def test_mep_reports_observational_phase_timings_and_work_counts() -> None:
    snapshot = _snapshot(maximum_soc=0.7)

    result, diagnostics = MarketDailyPlanner().plan_with_diagnostics(
        snapshot=snapshot,
        conversion_model=_conversion(),
    )

    assert result.snapshot_id == snapshot.snapshot_id
    assert diagnostics.planner_total_ms >= diagnostics.native_plan_ms
    assert diagnostics.native_plan_ms >= 0.0
    assert diagnostics.tariff_build_ms >= 0.0
    assert diagnostics.market_route_build_ms >= 0.0
    assert diagnostics.market_route_assessment_ms >= 0.0
    assert diagnostics.winner_selection_ms >= 0.0
    assert diagnostics.native_candidate_count == len(
        result.native_observation.observer_result.candidate_set.candidates
    )
    assert diagnostics.market_route_count == len(result.market_routes)
    assert diagnostics.route_assessment_count == len(result.route_assessments)


def test_mep_uses_published_market_prices_beyond_native_24_hours() -> None:
    snapshot = _snapshot(maximum_soc=0.7)
    assert snapshot.pv_energy_timeline is not None
    assert snapshot.household_load_forecast is not None
    pv_last = snapshot.pv_energy_timeline.intervals[-1]
    load_last = snapshot.household_load_forecast.intervals[-1]
    extended_pv = snapshot.pv_energy_timeline.intervals + tuple(
        replace(
            pv_last,
            interval_id=f"pv-extended-{index}",
            starts_at=pv_last.ends_at + index * timedelta(minutes=30),
            ends_at=pv_last.ends_at + (index + 1) * timedelta(minutes=30),
            forecast_evidence_ids=(f"solcast-extended-{index}",),
        )
        for index in range(12)
    )
    extended_load = snapshot.household_load_forecast.intervals + tuple(
        replace(
            load_last,
            interval_id=f"load-extended-{index}",
            starts_at=load_last.ends_at + index * timedelta(minutes=15),
            ends_at=load_last.ends_at + (index + 1) * timedelta(minutes=15),
        )
        for index in range(24)
    )
    horizon_end = snapshot.captured_at + timedelta(hours=30)
    priced = replace(
        snapshot,
        price_points=(replace(snapshot.price_points[0], ends_at=horizon_end),),
        pv_energy_timeline=replace(
            snapshot.pv_energy_timeline,
            intervals=extended_pv,
        ),
        household_load_forecast=replace(
            snapshot.household_load_forecast,
            intervals=extended_load,
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=priced,
        conversion_model=_conversion(),
    )

    assert result.native_observation.strategy_space.schedules[0].horizon_end == (
        horizon_end
    )


def test_mep_keeps_negative_tariffs_signed_in_its_native_plan() -> None:
    snapshot = _snapshot(maximum_soc=0.7)
    negative = tuple(replace(point, value_eur_per_kwh=-0.18) for point in snapshot.price_points)

    result = MarketDailyPlanner().plan(
        snapshot=replace(snapshot, price_points=negative),
        conversion_model=_conversion(),
    )

    settled = result.native_observation.observer_result.portfolio.strategy_results[0]
    assert all(
        interval.import_eur_per_kwh == -0.18
        for path in settled.run.financial.paths
        for interval in path.intervals
    )
    assert all(
        interval.export_eur_per_kwh == pytest.approx(-0.18, abs=2e-6)
        for path in settled.run.financial.paths
        for interval in path.intervals
    )


def test_mep_reserves_the_full_physically_chargeable_negative_window_volume() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    negative_start = snapshot.captured_at + timedelta(hours=2)
    priced = (
        replace(
            snapshot.price_points[0],
            point_id="before",
            ends_at=negative_start,
            value_eur_per_kwh=0.20,
        ),
        replace(
            snapshot.price_points[0],
            point_id="negative",
            starts_at=negative_start,
            ends_at=negative_start + timedelta(hours=2),
            value_eur_per_kwh=-0.05,
        ),
        replace(
            snapshot.price_points[0],
            point_id="after",
            starts_at=negative_start + timedelta(hours=2),
            value_eur_per_kwh=0.20,
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=replace(snapshot, price_points=priced),
        conversion_model=_conversion(),
    )

    negative_routes = tuple(
        item for item in result.market_routes if item.route_kind == "negative_capacity"
    )
    assert len(negative_routes) == 1
    route = negative_routes[0]
    assert route.window_starts_at == negative_start
    assert route.window_ends_at == negative_start + timedelta(hours=2)
    assert route.maximum_charge_input_wh == 4800.0
    assert route.reserved_storage_room_wh == 4800.0
    assert route.storage_energy_ceiling_before_window_wh == 3360.0
    assert route.required_pre_window_discharge_output_wh == 4392.0
    assert route.reason == "negative_all_in_import_window"
    assert len(result.route_assessments) >= 1
    assessment = next(item for item in result.route_assessments if item.admitted)
    assert assessment.physically_admissible is True
    assert assessment.incremental_wear_eur > 0.0
    assert assessment.worst_case_incremental_result_eur > 0.0
    assert assessment.minimum_incremental_result_eur_per_exported_kwh > 0.0
    assert assessment.admitted is True
    assert result.winning_source == "market_route"
    assert result.reason == "profitable_complete_market_route"
    assert result.dispatch_authority is False
    assert result.current_intent is not None
    assert result.current_intent.value == "storage_export"
    assert result.current_interval_ends_at is not None


def test_mep_builds_complete_2026_grid_trade_with_linked_saldering() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.2)
    split = snapshot.captured_at + timedelta(hours=12)
    end = snapshot.captured_at + timedelta(hours=24)
    source = snapshot.price_points[0]
    priced = replace(
        snapshot,
        price_points=(
            replace(source, point_id="cheap", ends_at=split, value_eur_per_kwh=0.05),
            replace(
                source,
                point_id="expensive",
                starts_at=split,
                ends_at=end,
                value_eur_per_kwh=0.55,
            ),
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=priced,
        conversion_model=_conversion(),
    )

    grid_routes = tuple(item for item in result.market_routes if item.route_kind == "grid_trade")
    assert grid_routes
    assert all(route.window_ends_at <= route.export_window_starts_at for route in grid_routes)
    grid_assessments = tuple(
        item
        for item in result.route_assessments
        if item.route_id in {route.route_id for route in grid_routes}
        and "baseline-household-support" in item.source_native_schedule_id
    )
    assert grid_assessments
    assert all(item.admitted for item in grid_assessments)
    assert all(
        item.worst_case_incremental_result_eur
        >= item.minimum_total_route_profit_eur
        for item in grid_assessments
    )


def test_mep_combines_grid_trade_with_hybrid_pv_residual_grid_parent() -> None:
    """ADR-017/024/037: trade extends the complete hybrid household path."""

    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.2)
    split = snapshot.captured_at + timedelta(hours=12)
    end = snapshot.captured_at + timedelta(hours=24)
    source = snapshot.price_points[0]
    priced = replace(
        snapshot,
        price_points=(
            replace(source, point_id="cheap", ends_at=split, value_eur_per_kwh=0.05),
            replace(
                source,
                point_id="expensive",
                starts_at=split,
                ends_at=end,
                value_eur_per_kwh=2.00,
            ),
        ),
    )

    portfolio, _ = MarketDailyPlanner().generate_with_diagnostics(
        snapshot=priced,
        conversion_model=_conversion(),
    )

    hybrid_trades = tuple(
        assessment
        for assessment in portfolio.route_assessments
        if "hybrid-pv-grid" in assessment.source_native_schedule_id
        and any(
            interval.intent.value == "storage_export"
            for interval in assessment.intent_schedule.intervals
        )
    )

    assert hybrid_trades
    assert any(assessment.admitted for assessment in hybrid_trades)
    assert all(
        any(
            interval.intent.value == "grid_requirement"
            for interval in assessment.intent_schedule.intervals
        )
        for assessment in hybrid_trades
    )
    assert all(
        evidence.reserve_respected
        and evidence.minimum_storage_energy_observed_wh
        >= evidence.minimum_storage_energy_wh
        for assessment in hybrid_trades
        for evidence in assessment.scenario_evidence
    )
    for hybrid_trade in hybrid_trades:
        final_export_end = max(
            interval.ends_at
            for interval in hybrid_trade.intent_schedule.intervals
            if interval.intent.value == "storage_export"
        )
        assert not any(
            interval.intent.value == "nom" and interval.starts_at >= final_export_end
            for interval in hybrid_trade.intent_schedule.intervals
        )


def test_mep_subdivides_broad_grid_trade_window_and_preserves_pv_room() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.2)
    cheap_window_end = snapshot.captured_at + timedelta(hours=12)
    horizon_end = snapshot.captured_at + timedelta(hours=24)
    source = snapshot.price_points[0]
    priced = replace(
        snapshot,
        price_points=(
            replace(
                source,
                point_id="broad-cheap-window",
                ends_at=cheap_window_end,
                value_eur_per_kwh=0.05,
            ),
            replace(
                source,
                point_id="later-export-window",
                starts_at=cheap_window_end,
                ends_at=horizon_end,
                value_eur_per_kwh=0.55,
            ),
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=priced,
        conversion_model=_conversion(),
    )

    grid_routes = tuple(
        route for route in result.market_routes if route.route_kind == "grid_trade"
    )
    assert len(grid_routes) > 1
    assert all(
        route.opportunity_window_starts_at == snapshot.captured_at
        and route.opportunity_window_ends_at == cheap_window_end
        for route in grid_routes
    )
    assert all(
        route.window_ends_at - route.window_starts_at
        <= timedelta(
            hours=route.maximum_charge_input_wh / 2400.0,
            minutes=15,
        )
        for route in grid_routes
    )
    assert all(
        route.window_ends_at <= cheap_window_end - timedelta(minutes=15)
        for route in grid_routes
    )

    route_ids = {route.route_id for route in grid_routes}
    grid_assessments = tuple(
        assessment
        for assessment in result.route_assessments
        if assessment.route_id in route_ids
    )
    assert grid_assessments
    assert all(
        any(
            interval.intent.value == "nom"
            for interval in assessment.intent_schedule.intervals
        )
        for assessment in grid_assessments
    )
    assert result.current_intent is not None
    assert result.current_intent.value == "nom"


def test_mep_uses_latest_safe_charge_window_inside_equal_route_cost() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.2)
    cheap_window_end = snapshot.captured_at + timedelta(hours=12)
    horizon_end = snapshot.captured_at + timedelta(hours=24)
    source = snapshot.price_points[0]
    result = MarketDailyPlanner().plan(
        snapshot=replace(
            snapshot,
            price_points=(
                replace(
                    source,
                    point_id="broad-cheap-window",
                    ends_at=cheap_window_end,
                    value_eur_per_kwh=0.05,
                ),
                replace(
                    source,
                    point_id="later-export-window",
                    starts_at=cheap_window_end,
                    ends_at=horizon_end,
                    value_eur_per_kwh=0.55,
                ),
            ),
        ),
        conversion_model=_conversion(),
    )
    admitted = tuple(item for item in result.route_assessments if item.admitted)
    pv_aligned = max(
        admitted,
        key=lambda item: next(
            evidence.explicit_charge_pv_to_storage_input_wh
            for evidence in item.scenario_evidence
            if evidence.scenario is PVScenario.LOWER
        ),
    )
    latest = max(
        admitted,
        key=MarketDailyEvaluationEngine._market_charge_starts_at,
    )
    assert pv_aligned is not latest

    # Hold complete-route grid energy equal so the last-safe tie-break is
    # isolated from both financial value and physical net-energy demand.
    common_grid_input_wh = 10000.0

    def with_route_values(assessment, *, result_eur, grid_input_wh=common_grid_input_wh):
        return replace(
            assessment,
            worst_case_incremental_result_eur=result_eur,
            scenario_evidence=tuple(
                replace(evidence, grid_to_storage_input_wh=grid_input_wh)
                for evidence in assessment.scenario_evidence
            ),
        )

    assessments = (
        with_route_values(pv_aligned, result_eur=0.495),
        with_route_values(latest, result_eur=0.500),
    )

    winner = MarketDailyEvaluationEngine.select_market_assessment(assessments)

    assert winner is not None
    assert winner.market_schedule_id == latest.market_schedule_id

    lower_grid_route = MarketDailyEvaluationEngine.select_market_assessment(
        (
            with_route_values(
                pv_aligned,
                result_eur=0.495,
                grid_input_wh=9000.0,
            ),
            with_route_values(latest, result_eur=0.500),
        )
    )

    assert lower_grid_route is not None
    assert lower_grid_route.market_schedule_id == pv_aligned.market_schedule_id

    financially_better = MarketDailyEvaluationEngine.select_market_assessment(
        (
            with_route_values(pv_aligned, result_eur=0.521),
            with_route_values(latest, result_eur=0.500),
        )
    )

    assert financially_better is not None
    assert financially_better.market_schedule_id == pv_aligned.market_schedule_id


def test_export_marginal_return_breaks_complete_route_subcent_tie() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.2)
    cheap_window_end = snapshot.captured_at + timedelta(hours=12)
    source = snapshot.price_points[0]
    result = MarketDailyPlanner().plan(
        snapshot=replace(
            snapshot,
            price_points=(
                replace(
                    source,
                    point_id="broad-cheap-window",
                    ends_at=cheap_window_end,
                    value_eur_per_kwh=0.05,
                ),
                replace(
                    source,
                    point_id="later-export-window",
                    starts_at=cheap_window_end,
                    ends_at=snapshot.captured_at + timedelta(hours=24),
                    value_eur_per_kwh=0.55,
                ),
            ),
        ),
        conversion_model=_conversion(),
    )
    admitted = tuple(item for item in result.route_assessments if item.admitted)
    assert len(admitted) >= 2
    lower_peak = replace(
        admitted[0],
        worst_case_incremental_result_eur=0.500,
        minimum_incremental_result_eur_per_exported_kwh=0.373,
    )
    actual_peak = replace(
        admitted[1],
        worst_case_incremental_result_eur=0.491,
        minimum_incremental_result_eur_per_exported_kwh=0.388,
    )

    winner = MarketDailyEvaluationEngine.select_market_assessment(
        (lower_peak, actual_peak)
    )

    assert winner is actual_peak


def test_stored_energy_export_windows_all_retain_absolute_price_peak() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=1.0)
    source = snapshot.price_points[0]
    peak_start = snapshot.captured_at + timedelta(hours=6)
    points = (
        replace(
            source,
            point_id="before-high",
            ends_at=peak_start - timedelta(minutes=15),
            value_eur_per_kwh=0.10,
        ),
        replace(
            source,
            point_id="high-left",
            starts_at=peak_start - timedelta(minutes=15),
            ends_at=peak_start,
            value_eur_per_kwh=0.37,
        ),
        replace(
            source,
            point_id="absolute-peak",
            starts_at=peak_start,
            ends_at=peak_start + timedelta(minutes=15),
            value_eur_per_kwh=0.388,
        ),
        replace(
            source,
            point_id="high-right",
            starts_at=peak_start + timedelta(minutes=15),
            ends_at=peak_start + timedelta(minutes=30),
            value_eur_per_kwh=0.375,
        ),
        replace(
            source,
            point_id="after-high",
            starts_at=peak_start + timedelta(minutes=30),
            ends_at=snapshot.captured_at + timedelta(hours=24),
            value_eur_per_kwh=0.10,
        ),
    )
    measured_wh = snapshot.current_storage_states[0].current_stored_energy_wh
    inventory = StorageEnergyInventory(
        execution_scope_id="battery",
        captured_at=snapshot.captured_at,
        measured_stored_energy_wh=measured_wh,
        lots=(
            StorageEnergyLot(
                source="pv",
                stored_energy_wh=measured_wh,
                acquisition_cost_eur=0.10,
                acquired_at=snapshot.captured_at - timedelta(hours=1),
                evidence_ids=("measured-pv-charge",),
            ),
        ),
    )

    result, diagnostics = MarketDailyPlanner().plan_with_diagnostics(
        snapshot=replace(snapshot, price_points=points),
        conversion_model=_conversion(),
        storage_inventory=inventory,
    )

    routes = tuple(
        route
        for route in result.market_routes
        if route.route_kind == "stored_energy_export"
    )
    assert routes
    assert all(
        route.export_window_starts_at <= peak_start
        < route.export_window_ends_at
        for route in routes
        if route.export_window_starts_at is not None
        and route.export_window_ends_at is not None
    )
    assessments = tuple(
        assessment
        for assessment in result.route_assessments
        if assessment.route_id in {route.route_id for route in routes}
    )
    assert any(item.admitted for item in assessments)
    assert diagnostics.route_assessment_count <= diagnostics.market_route_count * 7


def test_mep_combines_export_window_and_uses_cheapest_next_day_recharge() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    source = snapshot.price_points[0]
    export_start = snapshot.captured_at + timedelta(hours=8)
    export_end = export_start + timedelta(hours=1)
    midnight = export_start.replace(hour=0) + timedelta(days=1)
    priced = replace(
        snapshot,
        price_points=(
            replace(source, point_id="before", ends_at=export_start, value_eur_per_kwh=0.30),
            replace(
                source,
                point_id="export",
                starts_at=export_start,
                ends_at=export_end,
                value_eur_per_kwh=0.40,
            ),
            replace(
                source,
                point_id="overnight",
                starts_at=export_end,
                ends_at=midnight,
                value_eur_per_kwh=0.30,
            ),
            replace(
                source,
                point_id="recharge",
                starts_at=midnight,
                ends_at=snapshot.captured_at + timedelta(hours=24),
                value_eur_per_kwh=0.131,
            ),
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=priced,
        conversion_model=StorageConversionModel(
            model_id="zendure-rte",
            charge_efficiency=0.83**0.5,
            discharge_efficiency=0.83**0.5,
            evidence_ids=("zendure-rte",),
            method_version="test:v1",
        ),
        trading_policy=MarketTradingPolicy(
            margin_fraction=0.10,
            wear_eur_per_export_kwh=0.05,
        ),
    )

    pv_routes = tuple(
        item for item in result.market_routes if item.route_kind == "pv_trade"
    )
    grid_recovery_routes = tuple(
        item
        for item in result.market_routes
        if item.route_kind == "pv_trade_grid_recovery"
    )
    assert pv_routes
    assert grid_recovery_routes
    route = pv_routes[0]
    grid_recovery = grid_recovery_routes[0]
    assert route.export_window_starts_at == export_start
    assert route.export_window_ends_at <= export_end
    assert route.average_export_eur_per_kwh == pytest.approx(0.40, abs=2e-6)
    assert route.average_recharge_eur_per_kwh == pytest.approx(0.131)
    assert route.minimum_export_eur_per_kwh == pytest.approx(0.223614, abs=1e-6)
    assert route.window_starts_at.date() > export_end.date()
    assert route.maximum_charge_input_wh == 0.0
    assert grid_recovery.maximum_charge_input_wh == pytest.approx(
        grid_recovery.required_pre_window_discharge_output_wh / 0.83
    )
    assert grid_recovery.opportunity_window_starts_at == route.window_starts_at
    assert grid_recovery.opportunity_window_ends_at == route.window_ends_at
    assert (
        grid_recovery.opportunity_window_starts_at
        <= grid_recovery.window_starts_at
        < grid_recovery.window_ends_at
        <= grid_recovery.opportunity_window_ends_at
    )
    pv_assessment = next(
        item
        for item in result.route_assessments
        if item.route_id == route.route_id
    )
    grid_assessment = next(
        item
        for item in result.route_assessments
        if item.route_id == grid_recovery.route_id
    )
    assert all(
        scenario.grid_to_storage_input_wh > 0.0
        for scenario in grid_assessment.scenario_evidence
    )
    assert all(
        scenario.storage_energy_at_horizon_end_wh
        >= scenario.baseline_storage_energy_at_horizon_end_wh
        for scenario in pv_assessment.scenario_evidence
    )
    assert all(
        not scenario.target_held_at_horizon_end
        for scenario in pv_assessment.scenario_evidence
    )
    assert pv_assessment.physically_admissible is True
    assert all(
        scenario.storage_energy_at_horizon_end_wh
        >= scenario.baseline_storage_energy_at_horizon_end_wh
        for scenario in grid_assessment.scenario_evidence
    )
    assert any(
        interval.intent.value == "household_support_only"
        and interval.starts_at >= route.export_window_ends_at
        for interval in grid_assessment.intent_schedule.intervals
    )
    assert grid_assessment.physically_admissible is True


def test_mep_values_only_known_inventory_and_keeps_one_contiguous_export_window() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    source = snapshot.price_points[0]
    export_start = snapshot.captured_at + timedelta(hours=4)
    export_end = export_start + timedelta(hours=1)
    recovery_end = export_end + timedelta(hours=4)
    priced = replace(
        snapshot,
        price_points=(
            replace(source, point_id="before", ends_at=export_start, value_eur_per_kwh=0.30),
            replace(
                source,
                point_id="export",
                starts_at=export_start,
                ends_at=export_end,
                value_eur_per_kwh=0.40,
            ),
            replace(
                source,
                point_id="recovery",
                starts_at=export_end,
                ends_at=recovery_end,
                value_eur_per_kwh=0.131,
            ),
            replace(
                source,
                point_id="after",
                starts_at=recovery_end,
                ends_at=snapshot.captured_at + timedelta(hours=24),
                value_eur_per_kwh=0.30,
            ),
        ),
    )
    measured_wh = snapshot.current_storage_states[0].current_stored_energy_wh
    inventory = StorageEnergyInventory(
        execution_scope_id="battery",
        captured_at=snapshot.captured_at,
        measured_stored_energy_wh=measured_wh,
        lots=(
            StorageEnergyLot(
                source="pv",
                stored_energy_wh=2000.0,
                acquisition_cost_eur=0.04,
                acquired_at=snapshot.captured_at - timedelta(hours=2),
                evidence_ids=("measured-pv-charge",),
            ),
            StorageEnergyLot(
                source="unknown",
                stored_energy_wh=measured_wh - 2000.0,
                acquisition_cost_eur=None,
                acquired_at=snapshot.captured_at,
                evidence_ids=("opening-balance",),
            ),
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=priced,
        conversion_model=StorageConversionModel(
            model_id="zendure-rte",
            charge_efficiency=0.83**0.5,
            discharge_efficiency=0.83**0.5,
            evidence_ids=("zendure-rte",),
            method_version="test:v1",
        ),
        storage_inventory=inventory,
    )

    routes = tuple(
        route for route in result.market_routes if route.route_kind == "pv_trade"
    )
    assert routes
    assert all(route.inventory_sources == ("pv",) for route in routes)
    assert all(
        route.inventory_deliverable_energy_wh is not None
        and route.required_pre_window_discharge_output_wh
        <= route.inventory_deliverable_energy_wh
        for route in routes
    )
    assert all(
        route.export_window_starts_at < route.export_window_ends_at
        for route in routes
        if route.export_window_starts_at is not None
        and route.export_window_ends_at is not None
    )


def test_mep_accepts_cheaper_recovery_later_on_same_day() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    source = snapshot.price_points[0]
    export_start = snapshot.captured_at + timedelta(hours=4)
    export_end = export_start + timedelta(hours=1)
    recovery_end = export_end + timedelta(hours=4)
    priced = replace(
        snapshot,
        price_points=(
            replace(source, point_id="before", ends_at=export_start, value_eur_per_kwh=0.30),
            replace(
                source,
                point_id="export",
                starts_at=export_start,
                ends_at=export_end,
                value_eur_per_kwh=0.40,
            ),
            replace(
                source,
                point_id="recovery",
                starts_at=export_end,
                ends_at=recovery_end,
                value_eur_per_kwh=0.131,
            ),
            replace(
                source,
                point_id="after",
                starts_at=recovery_end,
                ends_at=snapshot.captured_at + timedelta(hours=24),
                value_eur_per_kwh=0.30,
            ),
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=priced,
        conversion_model=StorageConversionModel(
            model_id="zendure-rte",
            charge_efficiency=0.83**0.5,
            discharge_efficiency=0.83**0.5,
            evidence_ids=("zendure-rte",),
            method_version="test:v1",
        ),
    )

    same_day_routes = tuple(
        route
        for route in result.market_routes
        if route.route_kind == "pv_trade_grid_recovery"
        and route.export_window_ends_at is not None
        and route.window_starts_at.date() == route.export_window_ends_at.date()
    )
    assert same_day_routes
    assert all(
        route.window_starts_at >= route.export_window_ends_at
        for route in same_day_routes
        if route.export_window_ends_at is not None
    )


def test_mep_uses_actual_duration_for_split_same_day_recovery_intervals() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    source = snapshot.price_points[0]
    horizon_end = snapshot.captured_at + timedelta(hours=24)
    boundaries = [snapshot.captured_at, snapshot.captured_at + timedelta(minutes=7)]
    while boundaries[-1] + timedelta(minutes=15) < horizon_end:
        boundaries.append(boundaries[-1] + timedelta(minutes=15))
    boundaries.append(horizon_end)
    price_points = tuple(
        replace(
            source,
            point_id=f"split-price-{index}",
            starts_at=starts_at,
            ends_at=ends_at,
            value_eur_per_kwh=(
                0.346
                if snapshot.captured_at + timedelta(hours=4)
                <= starts_at
                < snapshot.captured_at + timedelta(hours=6)
                else 0.131
                if snapshot.captured_at + timedelta(hours=8)
                <= starts_at
                < snapshot.captured_at + timedelta(hours=12)
                else 0.30
            ),
        )
        for index, (starts_at, ends_at) in enumerate(zip(boundaries, boundaries[1:], strict=False))
    )

    result = MarketDailyPlanner().plan(
        snapshot=replace(snapshot, price_points=price_points),
        conversion_model=StorageConversionModel(
            model_id="zendure-rte",
            charge_efficiency=0.8012**0.5,
            discharge_efficiency=0.8012**0.5,
            evidence_ids=("zendure-rte",),
            method_version="test:v1",
        ),
    )

    morning_routes = tuple(
        route
        for route in result.market_routes
        if route.route_kind == "pv_trade_grid_recovery"
        and route.export_window_starts_at is not None
        and snapshot.captured_at + timedelta(hours=4)
        <= route.export_window_starts_at
        < snapshot.captured_at + timedelta(hours=6)
        and snapshot.captured_at + timedelta(hours=8)
        <= route.window_starts_at
        < snapshot.captured_at + timedelta(hours=12)
    )
    assert morning_routes
    assessed_route_ids = {assessment.route_id for assessment in result.route_assessments}
    assert all(route.route_id in assessed_route_ids for route in morning_routes)
    assert result.reason != "market_recovery_outside_available_horizon"


def test_mep_can_use_late_2026_export_after_earlier_linked_grid_charge() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    source = snapshot.price_points[0]
    export_start = snapshot.captured_at + timedelta(hours=23)
    priced = replace(
        snapshot,
        price_points=(
            replace(source, point_id="cheap", ends_at=export_start, value_eur_per_kwh=0.05),
            replace(
                source,
                point_id="late-export",
                starts_at=export_start,
                ends_at=snapshot.captured_at + timedelta(hours=24),
                value_eur_per_kwh=0.40,
            ),
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=priced,
        conversion_model=_conversion(),
    )

    grid_routes = tuple(
        route for route in result.market_routes if route.route_kind == "grid_trade"
    )
    assert grid_routes
    assert all(
        route.window_ends_at <= route.export_window_starts_at
        for route in grid_routes
        if route.export_window_starts_at is not None
    )


def test_mep_source_has_no_dependency_on_cp_or_ep_runtime_outputs() -> None:
    source = __import__("inspect").getsource(
        __import__(
            "picot.planner.market_daily_planner",
            fromlist=["MarketDailyPlanner"],
        )
    )

    forbidden = (
        "DailyObserverRuntimeOutcome",
        "IndependentDailyObserverRuntime",
        "CanonicalPipelineRun",
        "planner_comparison_ledger",
    )
    assert all(name not in source for name in forbidden)


def test_market_routes_consume_opportunity_evidence_without_top_n_selection() -> None:
    source = __import__("inspect").getsource(
        __import__(
            "picot.planner.market_daily_planner",
            fromlist=["MarketDailyPlanner"],
        )
    )

    assert "opportunities: OpportunitySet" in source
    assert ")[:6]" not in source
    assert ")[:8]" not in source


def test_every_market_route_retains_opportunity_lineage() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    negative = tuple(
        replace(point, value_eur_per_kwh=-0.10)
        for point in snapshot.price_points
    )

    result = MarketDailyPlanner().plan(
        snapshot=replace(snapshot, price_points=negative),
        conversion_model=_conversion(),
    )

    assert result.market_routes
    assert all(route.opportunity_ids for route in result.market_routes)


def test_mep_does_not_create_capacity_route_for_merely_low_positive_import() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    positive = tuple(replace(point, value_eur_per_kwh=0.001) for point in snapshot.price_points)

    result = MarketDailyPlanner().plan(
        snapshot=replace(snapshot, price_points=positive),
        conversion_model=_conversion(),
    )

    assert result.market_routes == ()
    assert result.route_assessments == ()


def test_mep_keeps_complete_but_unprofitable_negative_cycle_out_of_winner() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    negative_start = snapshot.captured_at + timedelta(hours=2)
    priced = (
        replace(
            snapshot.price_points[0],
            point_id="before",
            ends_at=negative_start,
            value_eur_per_kwh=0.0,
        ),
        replace(
            snapshot.price_points[0],
            point_id="negative",
            starts_at=negative_start,
            ends_at=negative_start + timedelta(hours=2),
            value_eur_per_kwh=-0.001,
        ),
        replace(
            snapshot.price_points[0],
            point_id="after",
            starts_at=negative_start + timedelta(hours=2),
            value_eur_per_kwh=0.0,
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=replace(snapshot, price_points=priced),
        conversion_model=_conversion(),
    )

    assert result.market_routes
    assert result.route_assessments
    assert not any(item.admitted for item in result.route_assessments)
    assert result.winning_source == "mep_native_plan"
    assert result.reason == "no_admitted_market_route"
