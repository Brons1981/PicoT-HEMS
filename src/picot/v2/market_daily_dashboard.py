"""Compact dashboard projection for MEP without granting dispatch authority."""

from __future__ import annotations

from picot.planner.market_daily_planner import MarketDailyPlan
from picot.v2.independent_daily_dashboard import (
    build_daily_observer_dashboard_view,
)
from picot.v2.independent_daily_observer_runtime import (
    DailyObserverRuntimeOutcome,
)
from picot.v2.market_daily_runtime import MarketDailyRuntimeOutcome


def build_market_daily_runtime_view(
    outcome: MarketDailyRuntimeOutcome,
) -> dict[str, object]:
    if outcome.plan is None:
        return {
            "planner_id": "mep",
            "planner_name": "Markt Etmaal Planner",
            "snapshot_id": outcome.snapshot_id,
            "captured_at": outcome.captured_at.isoformat(),
            "status": outcome.status,
            "reason": outcome.reason,
            "duration_ms": outcome.duration_ms,
            "planner_diagnostics": None,
            "dispatch_authority": False,
            "route_count": 0,
            "assessment_count": 0,
            "admitted_route_count": 0,
            "routes": [],
            "method_version": outcome.method_version,
        }
    view = build_market_daily_dashboard_view(outcome.plan)
    baseline_view = build_daily_observer_dashboard_view(
        DailyObserverRuntimeOutcome(
            snapshot_id=outcome.snapshot_id,
            run_id=outcome.run_id,
            captured_at=outcome.captured_at,
            status="completed",
            reason=None,
            duration_ms=outcome.duration_ms,
            observation=outcome.plan.native_observation,
            observer_only=True,
            selection_permitted=False,
            commitment_permitted=False,
            method_version=outcome.method_version,
        )
    )
    return {
        **view,
        "native_plan": baseline_view,
        "captured_at": outcome.captured_at.isoformat(),
        "status": outcome.status,
        "duration_ms": outcome.duration_ms,
        "planner_diagnostics": (
            {
                "native_plan_ms": outcome.planner_diagnostics.native_plan_ms,
                "tariff_build_ms": outcome.planner_diagnostics.tariff_build_ms,
                "market_route_build_ms": (
                    outcome.planner_diagnostics.market_route_build_ms
                ),
                "market_route_assessment_ms": (
                    outcome.planner_diagnostics.market_route_assessment_ms
                ),
                "winner_selection_ms": (
                    outcome.planner_diagnostics.winner_selection_ms
                ),
                "planner_total_ms": outcome.planner_diagnostics.planner_total_ms,
                "native_candidate_count": (
                    outcome.planner_diagnostics.native_candidate_count
                ),
                "market_route_count": outcome.planner_diagnostics.market_route_count,
                "route_assessment_count": (
                    outcome.planner_diagnostics.route_assessment_count
                ),
            }
            if outcome.planner_diagnostics is not None
            else None
        ),
        "execution": (
            {
                "status": outcome.execution.status,
                "requested_vendor_mode": (outcome.execution.requested_vendor_mode),
                "reason": outcome.execution.reason,
                "command_id": outcome.execution.command_id,
                "evaluated_at": (
                    outcome.execution.evaluated_at.isoformat()
                    if outcome.execution.evaluated_at is not None
                    else None
                ),
            }
            if outcome.execution is not None
            else None
        ),
        "runtime_method_version": outcome.method_version,
    }


def build_market_daily_dashboard_view(plan: MarketDailyPlan) -> dict[str, object]:
    """Expose market-route differences while preserving the frozen baseline."""

    assessments_by_route = {
        route.route_id: tuple(
            item for item in plan.route_assessments if item.route_id == route.route_id
        )
        for route in plan.market_routes
    }
    admitted_count = sum(item.admitted for item in plan.route_assessments)
    admitted = tuple(item for item in plan.route_assessments if item.admitted)
    if admitted:
        selected_schedule = max(
            admitted,
            key=lambda item: (
                item.worst_case_incremental_result_eur,
                item.minimum_incremental_result_eur_per_exported_kwh,
                item.market_schedule_id,
            ),
        ).intent_schedule
    else:
        candidates = {
            item.candidate_id: item
            for item in plan.native_observation.observer_result.candidate_set.candidates
        }
        results = {
            item.intent_schedule.schedule_id: item.intent_schedule
            for item in plan.native_observation.observer_result.portfolio.strategy_results
        }
        selected_schedule = results[
            candidates[
                sorted(plan.native_observation.observer_result.best_observation_ids)[0]
            ].intent_schedule_id
        ]
    return {
        "planner_id": plan.planner_id,
        "planner_name": plan.planner_name,
        "snapshot_id": plan.snapshot_id,
        "method_version": plan.method_version,
        "native_observation_id": plan.native_observation.observation_id,
        "winning_source": plan.winning_source,
        "reason": plan.reason,
        "dispatch_authority": plan.dispatch_authority,
        "round_trip_efficiency": plan.round_trip_efficiency,
        "trading_margin_percent": plan.trading_margin_fraction * 100.0,
        "wear_eur_per_export_kwh": plan.wear_eur_per_export_kwh,
        "current_intent": (plan.current_intent.value if plan.current_intent is not None else None),
        "current_interval_ends_at": (
            plan.current_interval_ends_at.isoformat()
            if plan.current_interval_ends_at is not None
            else None
        ),
        "route_count": len(plan.market_routes),
        "assessment_count": len(plan.route_assessments),
        "admitted_route_count": admitted_count,
        "selected_intent_intervals": [
            {
                "starts_at": item.starts_at.isoformat(),
                "ends_at": item.ends_at.isoformat(),
                "intent": item.intent.value,
                "storage_export_target_wh": item.storage_export_target_wh,
            }
            for item in selected_schedule.intervals
        ],
        "routes": [
            {
                "route_id": route.route_id,
                "window_starts_at": route.window_starts_at.isoformat(),
                "window_ends_at": route.window_ends_at.isoformat(),
                "maximum_charge_input_kwh": route.maximum_charge_input_wh / 1000.0,
                "reserved_storage_room_kwh": (route.reserved_storage_room_wh / 1000.0),
                "storage_energy_ceiling_before_window_kwh": (
                    route.storage_energy_ceiling_before_window_wh / 1000.0
                ),
                "required_pre_window_discharge_output_kwh": (
                    route.required_pre_window_discharge_output_wh / 1000.0
                ),
                "reason": route.reason,
                "route_kind": route.route_kind,
                "average_export_eur_per_kwh": route.average_export_eur_per_kwh,
                "average_recharge_eur_per_kwh": route.average_recharge_eur_per_kwh,
                "minimum_export_eur_per_kwh": route.minimum_export_eur_per_kwh,
                "export_window_starts_at": (
                    route.export_window_starts_at.isoformat()
                    if route.export_window_starts_at is not None
                    else None
                ),
                "export_window_ends_at": (
                    route.export_window_ends_at.isoformat()
                    if route.export_window_ends_at is not None
                    else None
                ),
                "assessment_count": len(assessments_by_route[route.route_id]),
                "admitted": any(item.admitted for item in assessments_by_route[route.route_id]),
                "assessments": [
                    {
                        "source_native_schedule_id": (item.source_native_schedule_id),
                        "market_schedule_id": item.market_schedule_id,
                        "physically_admissible": item.physically_admissible,
                        "incremental_wear_eur": item.incremental_wear_eur,
                        "worst_case_incremental_result_eur": (
                            item.worst_case_incremental_result_eur
                        ),
                        "minimum_incremental_result_eur_per_exported_kwh": (
                            item.minimum_incremental_result_eur_per_exported_kwh
                        ),
                        "admitted": item.admitted,
                        "admission_reason": item.admission_reason,
                    }
                    for item in assessments_by_route[route.route_id]
                ],
            }
            for route in plan.market_routes
        ],
    }
