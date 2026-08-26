from dataclasses import replace
from datetime import timedelta

from test_independent_daily_reference_adapter import _conversion, _snapshot

from picot.planner.market_daily_planner import MarketDailyPlanner


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
        interval.export_eur_per_kwh == -0.18
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
    assert assessment.worst_case_incremental_result_eur >= 0.25
    assert assessment.minimum_incremental_result_eur_per_exported_kwh >= 0.05
    assert assessment.admitted is True
    assert result.winning_source == "market_route"
    assert result.reason == "profitable_complete_market_route"
    assert result.dispatch_authority is False
    assert result.current_intent is not None
    assert result.current_intent.value == "storage_export"
    assert result.current_interval_ends_at is not None


def test_mep_does_not_assume_2026_saldering_for_grid_trade() -> None:
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
    assert grid_routes == ()
    assert any(item.route_kind == "pv_trade" for item in result.market_routes)
    assert result.route_assessments


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
