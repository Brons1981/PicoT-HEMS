from dataclasses import replace
from datetime import timedelta

import pytest
from test_independent_daily_reference_adapter import _conversion, _snapshot

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.planner.market_daily_planner import MarketDailyPlanner
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome
from picot.v2.contracts import StorageRoundTripEfficiencyEvidence
from picot.v2.live_runtime import _validate_live_execution_authority
from picot.v2.market_daily_runtime import (
    MarketDailyExecutionRuntime,
    MarketDailyPlannerRuntime,
)
from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
)
from picot.v2.storage_mode_provenance import (
    initial_storage_mode_provenance,
    observe_storage_mode,
    record_planner_mode_application,
)
from picot.v2.zendure_mode_capabilities import (
    derive_zendure_mode_capability_evidence,
)

MODE_ENTITY = "input_select.zendure_2400_ac_modus_selecteren"


def _live_snapshot():
    snapshot = _snapshot(maximum_soc=0.7)
    current_mode = "Standby"
    evidence = derive_zendure_mode_capability_evidence(
        {
            "state": current_mode,
            "attributes": {
                "options": [
                    "Standby",
                    "Nul op de meter",
                    "Alleen slim ontladen",
                    "Snel opladen",
                    "Snel ontladen",
                ]
            },
        },
        captured_at=snapshot.captured_at,
        source_entity_id=MODE_ENTITY,
        capability_id=snapshot.current_storage_states[0].capability_id,
        execution_scope_id=(snapshot.current_storage_states[0].execution_scope_id),
    )
    provenance = initial_storage_mode_provenance(
        observed_vendor_mode=current_mode,
        observed_at=snapshot.captured_at,
    )
    return replace(
        snapshot,
        storage_mode_capability_evidence=evidence,
        storage_mode_control_provenance=provenance,
    )


def _fresh_mode_snapshot(snapshot, *, captured_at, current_mode):
    evidence = derive_zendure_mode_capability_evidence(
        {
            "state": current_mode,
            "attributes": {
                "options": [
                    "Standby",
                    "Nul op de meter",
                    "Alleen slim ontladen",
                    "Snel opladen",
                    "Snel ontladen",
                ]
            },
        },
        captured_at=captured_at,
        source_entity_id=MODE_ENTITY,
        capability_id=snapshot.current_storage_states[0].capability_id,
        execution_scope_id=(snapshot.current_storage_states[0].execution_scope_id),
    )
    provenance = initial_storage_mode_provenance(
        observed_vendor_mode=current_mode,
        observed_at=captured_at,
    )
    return replace(
        snapshot,
        captured_at=captured_at,
        storage_mode_capability_evidence=evidence,
        storage_mode_control_provenance=provenance,
        capability_snapshot_set=None,
        bms_calibration_evidence=None,
    )


def test_live_mep_dispatches_its_unambiguous_current_intent() -> None:
    snapshot = _live_snapshot()
    plan = MarketDailyPlanner().plan(
        snapshot=snapshot,
        conversion_model=_conversion(),
        dispatch_authority=True,
    )
    plan = replace(
        plan,
        current_intent=DailyStorageIntent.NOM,
        current_interval_ends_at=snapshot.captured_at + timedelta(minutes=15),
    )
    calls = []
    runtime = MarketDailyExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append((request, mapping))
            or CanonicalDispatchOutcome(
                status="dispatched",
                command_id="mep-command",
            )
        ),
        now=lambda: snapshot.captured_at,
    )

    result = runtime.apply(plan=plan, snapshot=snapshot)

    assert plan.dispatch_authority is True
    assert plan.native_observation.observer_only is True
    assert plan.native_observation.selection_permitted is False
    assert result.status == "dispatched"
    assert result.requested_vendor_mode is not None
    assert len(calls) == 1
    request, mapping = calls[0]
    assert mapping.fixed_value == result.requested_vendor_mode
    assert mapping.entity_id == MODE_ENTITY
    assert request.request_id.startswith(f"mep:{snapshot.snapshot_id}:")


def test_live_mep_preserves_active_nom_across_rolling_quarter_horizon(
    tmp_path,
) -> None:
    initial = _live_snapshot()
    plan = MarketDailyPlanner().plan(
        snapshot=initial,
        conversion_model=_conversion(),
        dispatch_authority=True,
    )
    captured_at = initial.captured_at + timedelta(minutes=2)
    snapshot = _fresh_mode_snapshot(
        initial,
        captured_at=captured_at,
        current_mode="Nul op de meter",
    )
    plan = replace(
        plan,
        current_intent=DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
        current_interval_ends_at=captured_at + timedelta(minutes=13),
    )
    selected_id = sorted(
        plan.native_observation.observer_result.best_observation_ids
    )[0]
    candidate = next(
        item
        for item in plan.native_observation.observer_result.candidate_set.candidates
        if item.candidate_id == selected_id
    )
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    store = ActivePlanCommitmentStore(tmp_path / "commitments.json")
    store.save(ActivePlanCommitment(
        execution_scope_id=scope_id,
        plan_id="mep-plan:before-quarter-boundary",
        plan_revision=1,
        primitive="balance_bidirectional",
        source_policy="pv_only",
        starts_at=captured_at - timedelta(minutes=2),
        ends_at=captured_at + timedelta(hours=1),
        target_energy_wh=snapshot.current_storage_states[0].usable_capacity_wh,
        selection_method_version="mep-active-plan-commitment:v1",
        planner_id="mep",
        schedule_id="mep-window-12:30-14:15",
        worst_case_financial_result_eur=(
            candidate.worst_case_financial_result_eur + 0.02
        ),
        minimum_confidence=candidate.minimum_confidence,
        reserve_respected_across_scenarios=(
            candidate.reserve_respected_across_scenarios
        ),
        target_held_across_scenarios=candidate.target_held_across_scenarios,
        minimum_storage_energy_at_horizon_end_wh=min(
            item.storage_energy_at_horizon_end_wh
            for item in candidate.scenario_outcomes
        ),
    ))
    calls = []
    runtime = MarketDailyExecutionRuntime(
        dispatch=lambda request, mapping: calls.append((request, mapping)),
        now=lambda: captured_at,
        commitment_store=store,
    )

    result = runtime.apply(plan=plan, snapshot=snapshot)

    assert result.status == "already_active"
    assert result.requested_vendor_mode == "Nul op de meter"
    assert result.commitment_status == "preserved"
    assert result.challenger_reason == "challenger_not_strictly_better"
    assert result.challenger_financial_delta_eur == pytest.approx(-0.02)
    assert calls == []


def test_live_mep_allows_strictly_better_challenger_to_replace_commitment(
    tmp_path,
) -> None:
    initial = _live_snapshot()
    plan = MarketDailyPlanner().plan(
        snapshot=initial,
        conversion_model=_conversion(),
        dispatch_authority=True,
    )
    captured_at = initial.captured_at + timedelta(minutes=2)
    snapshot = _fresh_mode_snapshot(
        initial,
        captured_at=captured_at,
        current_mode="Nul op de meter",
    )
    plan = replace(
        plan,
        current_intent=DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
        current_interval_ends_at=captured_at + timedelta(minutes=13),
    )
    selected_id = sorted(
        plan.native_observation.observer_result.best_observation_ids
    )[0]
    candidate = next(
        item
        for item in plan.native_observation.observer_result.candidate_set.candidates
        if item.candidate_id == selected_id
    )
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    store = ActivePlanCommitmentStore(tmp_path / "commitments.json")
    store.save(ActivePlanCommitment(
        execution_scope_id=scope_id,
        plan_id="mep-plan:inferior-active-plan",
        plan_revision=1,
        primitive="balance_bidirectional",
        source_policy="pv_only",
        starts_at=captured_at - timedelta(minutes=2),
        ends_at=captured_at + timedelta(hours=1),
        target_energy_wh=snapshot.current_storage_states[0].usable_capacity_wh,
        selection_method_version="mep-active-plan-commitment:v1",
        planner_id="mep",
        schedule_id="inferior-active-schedule",
        worst_case_financial_result_eur=(
            candidate.worst_case_financial_result_eur - 0.02
        ),
        minimum_confidence=candidate.minimum_confidence,
        reserve_respected_across_scenarios=(
            candidate.reserve_respected_across_scenarios
        ),
        target_held_across_scenarios=candidate.target_held_across_scenarios,
        minimum_storage_energy_at_horizon_end_wh=min(
            item.storage_energy_at_horizon_end_wh
            for item in candidate.scenario_outcomes
        ),
    ))
    calls = []
    runtime = MarketDailyExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append((request, mapping))
            or CanonicalDispatchOutcome(status="dispatched", command_id="replace")
        ),
        now=lambda: captured_at,
        commitment_store=store,
    )

    result = runtime.apply(plan=plan, snapshot=snapshot)

    assert result.status == "dispatched"
    assert result.requested_vendor_mode == "Alleen slim ontladen"
    assert result.commitment_status == "replaced"
    assert result.challenger_reason == "challenger_financially_proven_better"
    assert result.challenger_financial_delta_eur == pytest.approx(0.02)
    assert store.load(scope_id) is None
    assert len(calls) == 1


def test_live_mep_never_bypasses_a_manual_override() -> None:
    snapshot = _live_snapshot()
    provenance = record_planner_mode_application(
        snapshot.storage_mode_control_provenance,
        vendor_mode="Nul op de meter",
        applied_at=snapshot.captured_at,
        application_id="previous-mep-command",
    )
    provenance = observe_storage_mode(
        provenance,
        observed_vendor_mode="Standby",
        observed_at=snapshot.captured_at,
    )
    snapshot = replace(
        snapshot,
        storage_mode_control_provenance=provenance,
    )
    plan = MarketDailyPlanner().plan(
        snapshot=snapshot,
        conversion_model=_conversion(),
        dispatch_authority=True,
    )
    plan = replace(
        plan,
        current_intent=DailyStorageIntent.NOM,
        current_interval_ends_at=snapshot.captured_at + timedelta(minutes=15),
    )
    calls = []
    runtime = MarketDailyExecutionRuntime(
        dispatch=lambda request, mapping: calls.append((request, mapping)),
        now=lambda: snapshot.captured_at,
    )

    result = runtime.apply(plan=plan, snapshot=snapshot)

    assert result.status == "blocked"
    assert result.reason == "manual_override_active"
    assert calls == []


def test_observer_mep_never_dispatches() -> None:
    snapshot = _live_snapshot()
    plan = MarketDailyPlanner().plan(
        snapshot=snapshot,
        conversion_model=_conversion(),
    )
    calls = []
    runtime = MarketDailyExecutionRuntime(
        dispatch=lambda request, mapping: calls.append((request, mapping)),
        now=lambda: snapshot.captured_at,
    )

    result = runtime.apply(plan=plan, snapshot=snapshot)

    assert result.status == "observer_only"
    assert calls == []


def test_mep_live_authority_cannot_coexist_with_another_live_planner() -> None:
    try:
        _validate_live_execution_authority(
            canonical_execution_enabled=True,
            live_pv_canary_enabled=False,
            market_daily_execution_enabled=True,
        )
    except ValueError as exc:
        assert "cannot share live authority" in str(exc)
    else:
        raise AssertionError("two live planner authorities must be rejected")


def test_live_mep_cannot_start_without_its_execution_boundary() -> None:
    try:
        MarketDailyPlannerRuntime(_conversion(), live_enabled=True)
    except ValueError as exc:
        assert str(exc) == "live MEP requires an execution runtime"
    else:
        raise AssertionError("live MEP without execution runtime must be rejected")


def test_mep_uses_current_zendure_rte_for_its_private_conversion_model() -> None:
    snapshot = _snapshot(maximum_soc=0.7)
    evidence = StorageRoundTripEfficiencyEvidence(
        status="available",
        round_trip_efficiency=0.83,
        observed_at=snapshot.captured_at,
        source_entity_id="sensor.zendure_2400_ac_rte_totaal",
        evidence_id="ha-rte-83",
        method_version="test:v1",
    )
    runtime = MarketDailyPlannerRuntime(_conversion())

    conversion, policy = runtime._planning_configuration(
        replace(snapshot, storage_round_trip_efficiency=evidence)
    )

    assert conversion.charge_efficiency * conversion.discharge_efficiency == pytest.approx(0.83)
    assert conversion.evidence_ids == ("ha-rte-83",)
    assert policy.market_routes_enabled is True


def test_mep_disables_trading_but_keeps_physical_planning_without_valid_rte() -> None:
    snapshot = _snapshot(maximum_soc=0.7)
    runtime = MarketDailyPlannerRuntime(_conversion())

    outcome = runtime.plan(snapshot)

    assert outcome.status == "completed"
    assert outcome.plan is not None
    assert outcome.plan.market_routes == ()
    assert outcome.plan.winning_source == "mep_native_plan"


def test_mep_boundary_executes_retained_nom_instead_of_replanning_it_later() -> None:
    snapshot = _live_snapshot()
    calls = []
    clock = [snapshot.captured_at]
    execution = MarketDailyExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append((request, mapping))
            or CanonicalDispatchOutcome(
                status="dispatched",
                command_id="mep-command",
            )
        ),
        now=lambda: clock[0],
    )
    runtime = MarketDailyPlannerRuntime(
        _conversion(),
        live_enabled=True,
        execution_runtime=execution,
    )
    outcome = runtime.plan(snapshot)
    calls.clear()
    assert outcome.plan is not None
    candidates = {
        item.candidate_id: item
        for item in outcome.plan.native_observation.observer_result.candidate_set.candidates
    }
    selected_schedule_ids = {
        candidates[candidate_id].intent_schedule_id
        for candidate_id in outcome.plan.native_observation.observer_result.best_observation_ids
    }
    portfolio = outcome.plan.native_observation.observer_result.portfolio
    selected_result = next(
        item
        for item in portfolio.strategy_results
        if item.intent_schedule.schedule_id in selected_schedule_ids
    )
    retained = selected_result.intent_schedule
    nom_interval = replace(
        retained.intervals[1],
        intent=DailyStorageIntent.NOM,
    )
    retained = replace(
        retained,
        intervals=(retained.intervals[0], nom_interval, *retained.intervals[2:]),
    )
    portfolio = replace(
        portfolio,
        strategy_results=tuple(
            replace(
                item,
                intent_schedule=replace(
                    item.intent_schedule,
                    intervals=(
                        item.intent_schedule.intervals[0],
                        replace(
                            item.intent_schedule.intervals[1],
                            intent=DailyStorageIntent.NOM,
                        ),
                        *item.intent_schedule.intervals[2:],
                    ),
                ),
            )
            if item.intent_schedule.schedule_id in selected_schedule_ids
            else item
            for item in portfolio.strategy_results
        ),
    )
    baseline = replace(
        outcome.plan.native_observation,
        observer_result=replace(
            outcome.plan.native_observation.observer_result,
            portfolio=portfolio,
        ),
    )
    outcome = replace(
        outcome,
        plan=replace(outcome.plan, native_observation=baseline),
    )
    clock[0] = nom_interval.starts_at + timedelta(seconds=2)
    fresh = _fresh_mode_snapshot(
        snapshot,
        captured_at=clock[0],
        current_mode="Alleen slim ontladen",
    )

    advanced = runtime.advance(outcome, fresh)

    assert advanced.snapshot_id == outcome.snapshot_id
    assert advanced.plan is not None
    assert advanced.plan.current_intent is DailyStorageIntent.NOM
    assert advanced.plan.current_interval_ends_at == nom_interval.ends_at
    assert advanced.execution is not None
    assert advanced.execution.status == "dispatched"
    assert advanced.execution.requested_vendor_mode == "Nul op de meter"
    assert advanced.execution.evaluated_at == clock[0]
    assert len(calls) == 1
