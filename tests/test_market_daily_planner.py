from dataclasses import replace
from datetime import timedelta

from test_independent_daily_reference_adapter import _conversion, _snapshot

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.planner.market_daily_planner import MarketDailyPlanner


def test_mep_preserves_frozen_daily_baseline_when_no_market_extension_applies() -> None:
    snapshot = _snapshot(maximum_soc=0.7)

    result = MarketDailyPlanner().plan(
        snapshot=snapshot,
        conversion_model=_conversion(),
    )

    assert result.planner_id == "mep"
    assert result.planner_name == "Markt Etmaal Planner"
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.baseline.observer_only is True
    assert result.baseline.selection_permitted is False
    assert result.market_routes == ()
    assert result.winning_source == "frozen_daily_baseline"
    assert result.dispatch_authority is False
    assert result.reason == "no_admitted_market_route"
    assert result.selected_intent_schedule.snapshot_id == snapshot.snapshot_id


def test_mep_protects_today_recovery_when_ep_prefers_cheaper_tomorrow() -> None:
    snapshot = _snapshot()
    source = snapshot.price_points[0]
    split_at = snapshot.captured_at + timedelta(hours=12)
    priced = replace(
        snapshot,
        price_points=(
            replace(
                source,
                point_id="today-expensive",
                ends_at=split_at,
                value_eur_per_kwh=0.40,
            ),
            replace(
                source,
                point_id="tomorrow-cheap",
                starts_at=split_at,
                value_eur_per_kwh=0.10,
            ),
        ),
    )

    result = MarketDailyPlanner().plan(
        snapshot=priced,
        conversion_model=_conversion(),
    )

    candidates = {
        item.candidate_id: item
        for item in result.baseline.observer_result.candidate_set.candidates
    }
    ep_winner = candidates[result.baseline.observer_result.best_observation_ids[0]]
    assert all(
        item.target_reached_at is not None
        and item.target_reached_at.date() > priced.captured_at.date()
        for item in ep_winner.scenario_outcomes
    )
    selected_candidate = next(
        item
        for item in candidates.values()
        if item.intent_schedule_id == result.selected_intent_schedule.schedule_id
    )
    assert all(
        item.target_reached_at is not None
        and item.target_reached_at.date() == priced.captured_at.date()
        for item in selected_candidate.scenario_outcomes
    )
    assert result.selection_reason == "today_pv_recovery_protected"
    assert result.baseline.observer_result.best_observation_ids[0] == ep_winner.candidate_id


def test_mep_uses_remaining_current_interval_when_not_more_expensive() -> None:
    snapshot = _snapshot()
    captured_at = snapshot.captured_at + timedelta(minutes=5)
    quarter_end = snapshot.captured_at + timedelta(minutes=15)
    schedule = DailyReferenceIntentSchedule(
        schedule_id="ep-schedule",
        snapshot_id=snapshot.snapshot_id,
        horizon_start=snapshot.captured_at,
        horizon_end=snapshot.captured_at + timedelta(minutes=30),
        intervals=(
            DailyReferenceIntentInterval(
                starts_at=snapshot.captured_at,
                ends_at=quarter_end,
                intent=DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
            ),
            DailyReferenceIntentInterval(
                starts_at=quarter_end,
                ends_at=snapshot.captured_at + timedelta(minutes=30),
                intent=DailyStorageIntent.NOM,
            ),
        ),
        method_version="ep:test",
    )
    tariffs = DailyReferenceTariffSchedule(
        schedule_id="tariffs",
        snapshot_id=snapshot.snapshot_id,
        horizon_start=snapshot.captured_at,
        horizon_end=snapshot.captured_at + timedelta(minutes=30),
        intervals=(
            DailyReferenceTariffInterval(
                starts_at=snapshot.captured_at,
                ends_at=quarter_end,
                import_eur_per_kwh=0.18,
                export_eur_per_kwh=0.18,
                confidence=1.0,
                evidence_ids=("current-price",),
            ),
            DailyReferenceTariffInterval(
                starts_at=quarter_end,
                ends_at=snapshot.captured_at + timedelta(minutes=30),
                import_eur_per_kwh=0.20,
                export_eur_per_kwh=0.20,
                confidence=1.0,
                evidence_ids=("following-price",),
            ),
        ),
        method_version="tariff:test",
    )

    adjusted = MarketDailyPlanner._use_remaining_cheap_interval(
        captured_at=captured_at,
        schedule=schedule,
        tariffs=tariffs,
    )

    assert adjusted.schedule_id == "mep-current:ep-schedule"
    assert adjusted.intervals[0].intent is DailyStorageIntent.NOM
    assert adjusted.intervals[0].ends_at == quarter_end


def test_mep_keeps_negative_tariffs_signed_in_its_frozen_baseline() -> None:
    snapshot = _snapshot(maximum_soc=0.7)
    negative = tuple(
        replace(point, value_eur_per_kwh=-0.18)
        for point in snapshot.price_points
    )

    result = MarketDailyPlanner().plan(
        snapshot=replace(snapshot, price_points=negative),
        conversion_model=_conversion(),
    )

    settled = result.baseline.observer_result.portfolio.strategy_results[0]
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

    assert len(result.market_routes) == 1
    route = result.market_routes[0]
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


def test_mep_does_not_create_capacity_route_for_merely_low_positive_import() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    positive = tuple(
        replace(point, value_eur_per_kwh=0.001)
        for point in snapshot.price_points
    )

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
    assert result.winning_source == "frozen_daily_baseline"
    assert result.reason == "no_admitted_market_route"
