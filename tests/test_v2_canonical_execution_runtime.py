from dataclasses import replace
from datetime import timedelta
from importlib import import_module

from test_v2_storage_mode_provenance_integration import BASE, _run

from picot.v2.canonical_execution_runtime import (
    CanonicalDispatchOutcome,
    CanonicalExecutionRuntime,
)
from picot.v2.contracts import BMSCalibrationEvidence, CanonicalPipelineRun
from picot.v2.household_planning_regime import HouseholdPlanningRegime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot.v2.storage_capability_snapshot import (
    build_storage_capability_snapshot_set,
)


def _planner_owned_standby() -> object:
    module = import_module("picot.v2.storage_mode_provenance")
    provenance = module.initial_storage_mode_provenance(
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )
    provenance = module.record_planner_mode_application(
        provenance,
        vendor_mode="Standby",
        applied_at=BASE,
        application_id="canonical-live-test",
    )
    return module.observe_storage_mode(
        provenance,
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )


def _live_run() -> CanonicalPipelineRun:
    observer = _run(
        current_mode="Standby",
        provenance=_planner_owned_standby(),
    )
    evidence = observer.planning_input.storage_mode_capability_evidence
    assert evidence is not None
    planning_input = replace(
        observer.planning_input,
        capability_snapshot_set=build_storage_capability_snapshot_set(
            evidence,
            snapshot_id=observer.planning_input.snapshot_id,
        ),
    )
    return CanonicalPipeline().run(
        planning_input=planning_input,
        control_change_allowed=True,
    )


def test_explicit_live_authority_removes_only_authority_blocker() -> None:
    run = _live_run()

    assert run.execution_plan_set.plans[0].observer_only is False
    assert run.execution_record.status == "live_plan_ready"
    assert run.primitive_boundary.status == "request_ready"
    assert run.primitive_boundary.blockers == ()
    assert run.adapter_boundary.status == "translation_ready"
    assert run.vendor_result.status == "dispatch_ready"


def test_explicit_live_authority_bootstraps_unverified_provenance() -> None:
    module = import_module("picot.v2.storage_mode_provenance")
    observer = _run(
        current_mode="Standby",
        provenance=module.initial_storage_mode_provenance(
            observed_vendor_mode="Standby",
            observed_at=BASE,
        ),
    )

    run = CanonicalPipeline().run(
        planning_input=observer.planning_input,
        control_change_allowed=True,
    )

    assert run.primitive_boundary.status == "request_ready"
    assert run.primitive_boundary.blockers == ()


def test_explicit_live_authority_never_bypasses_manual_override() -> None:
    module = import_module("picot.v2.storage_mode_provenance")
    provenance = module.record_planner_mode_application(
        _planner_owned_standby(),
        vendor_mode="Alleen slim opladen",
        applied_at=BASE,
        application_id="canonical-live-previous-command",
    )
    overridden = module.observe_storage_mode(
        provenance,
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )
    observer = _run(current_mode="Standby", provenance=overridden)

    run = CanonicalPipeline().run(
        planning_input=observer.planning_input,
        control_change_allowed=True,
    )

    assert run.primitive_boundary.status == "dry_run_blocked"
    assert run.primitive_boundary.blockers == ("manual_override_active",)
    assert run.vendor_result.status == "not_dispatched"


def test_explicit_bms_calibration_temporarily_blocks_canonical_dispatch() -> None:
    live = _live_run()
    planning_input = replace(
        live.planning_input,
        bms_calibration_evidence=BMSCalibrationEvidence(
            status="active",
            active=True,
            observed_at=BASE,
            source_entity_id="sensor.zendure_2400_ac_kalibreren",
            evidence_id="evidence-bms-calibration",
            method_version="zendure-calibration-state:v1",
        ),
    )

    run = CanonicalPipeline().run(
        planning_input=planning_input,
        control_change_allowed=True,
    )

    assert run.primitive_boundary.status == "dry_run_blocked"
    assert run.primitive_boundary.blockers == ("bms_soc_calibration_active",)
    assert run.vendor_result.status == "not_dispatched"


def test_canonical_plan_restores_smart_discharge_before_future_pv_window() -> None:
    live = _live_run()
    planning_input = live.planning_input
    assert planning_input.pv_energy_timeline is not None
    assert planning_input.household_load_forecast is not None
    shift = timedelta(hours=1)
    shifted_pv = replace(
        planning_input.pv_energy_timeline,
        intervals=tuple(
            replace(
                interval,
                starts_at=interval.starts_at + shift,
                ends_at=interval.ends_at + shift,
            )
            for interval in planning_input.pv_energy_timeline.intervals
        ),
    )
    shifted_load = replace(
        planning_input.household_load_forecast,
        intervals=tuple(
            replace(
                interval,
                starts_at=interval.starts_at + shift,
                ends_at=interval.ends_at + shift,
            )
            for interval in planning_input.household_load_forecast.intervals
        ),
    )
    shifted_input = replace(
        planning_input,
        horizon_end=(planning_input.horizon_end + shift),
        pv_energy_timeline=shifted_pv,
        household_load_forecast=shifted_load,
    )

    run = CanonicalPipeline().run(
        planning_input=shifted_input,
        control_change_allowed=True,
    )

    assert run.primitive_boundary.status == "request_ready"
    assert run.primitive_boundary.planned_primitive is not None
    assert run.primitive_boundary.planned_primitive.value == (
        "balance_discharge_only"
    )
    assert run.primitive_boundary.planned_vendor_mode == "Alleen slim ontladen"


def test_future_pv_window_uses_smart_discharge_until_window_starts() -> None:
    live = _live_run()
    planning_input = live.planning_input
    assert planning_input.pv_energy_timeline is not None
    assert planning_input.household_load_forecast is not None
    shift = timedelta(hours=1)
    shifted_input = replace(
        planning_input,
        horizon_end=(planning_input.horizon_end + shift),
        pv_energy_timeline=replace(
            planning_input.pv_energy_timeline,
            intervals=tuple(
                replace(
                    interval,
                    starts_at=interval.starts_at + shift,
                    ends_at=interval.ends_at + shift,
                )
                for interval in planning_input.pv_energy_timeline.intervals
            ),
        ),
        household_load_forecast=replace(
            planning_input.household_load_forecast,
            intervals=tuple(
                replace(
                    interval,
                    starts_at=interval.starts_at + shift,
                    ends_at=interval.ends_at + shift,
                )
                for interval in planning_input.household_load_forecast.intervals
            ),
        ),
        household_planning_regime=HouseholdPlanningRegime(
            regime_id="household-regime-self-consumption-test",
            profile_id="profile-test",
            profile_version=1,
            regime="self_consumption_first",
            objective_order=(
                "self_consumption",
                "cost_optimization",
                "reserve_availability",
            ),
            reason="low_confidence_and_material_pv_underperformance",
            forecast_confidence=0.40,
            cumulative_forecast_energy_wh=2000.0,
            cumulative_actual_energy_wh=1000.0,
            deviation_energy_wh=-1000.0,
            deviation_percent=-50.0,
            underperformance_duration_seconds=1800,
            evidence_ids=("pv-evidence-test",),
        ),
    )

    run = CanonicalPipeline().run(
        planning_input=shifted_input,
        control_change_allowed=True,
    )

    assert run.primitive_boundary.status == "request_ready"
    assert run.primitive_boundary.planned_primitive is not None
    assert run.primitive_boundary.planned_primitive.value == (
        "balance_discharge_only"
    )
    assert run.primitive_boundary.planned_vendor_mode == "Alleen slim ontladen"


def test_canonical_runtime_dispatches_the_exact_approved_mode() -> None:
    calls: list[tuple[object, object]] = []
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append((request, mapping))
            or CanonicalDispatchOutcome(
                status="dispatched",
                command_id="ha-command-test",
            )
        )
    )

    result = runtime.apply(_live_run())

    assert len(calls) == 1
    request, mapping = calls[0]
    assert request.primitive.value == "balance_bidirectional"
    assert mapping.fixed_value == "Nul op de meter"
    assert mapping.entity_id == ("input_select.zendure_2400_ac_modus_selecteren")
    assert result.adapter_boundary.status == "translated"
    assert result.vendor_result.status == "dispatched"
    assert result.vendor_result.command_id == "ha-command-test"


def test_plan_builder_converts_complete_mixed_storage_path_exactly_once() -> None:
    run = _live_run()
    winning_path = next(
        path
        for path in run.candidate_set.energy_paths
        if path.path_id == run.evaluation.winning_energy_path_id
    )
    plan = run.execution_plan_set.plans[0]

    assert {segment.primitive.value for segment in winning_path.segments} == {
        "balance_bidirectional",
        "balance_discharge_only",
    }
    assert tuple(
        segment.source_path_segment_id for segment in plan.segments
    ) == winning_path.segment_ids


def test_canonical_runtime_does_not_repeat_request_before_feedback() -> None:
    calls: list[str] = []
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append(mapping.fixed_value or "")
            or CanonicalDispatchOutcome(
                status="dispatched",
                command_id="ha-command-test",
            )
        )
    )
    run = _live_run()

    runtime.apply(run)
    duplicate = runtime.apply(run)

    assert calls == ["Nul op de meter"]
    assert duplicate.vendor_result.status == "awaiting_mode_feedback"


def test_active_pv_plan_is_not_interrupted_by_a_forecast_replan(tmp_path) -> None:
    calls: list[str] = []
    commitment_path = tmp_path / "commitment.json"
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append(mapping.fixed_value or "")
            or CanonicalDispatchOutcome("dispatched", "ha-command-test")
        ),
        commitment_store=ActivePlanCommitmentStore(commitment_path),
    )
    active = _live_run()
    runtime.apply(active)

    # A fresh runtime instance models an add-on restart. The execution
    # commitment must come from durable plan context, not process memory.
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append(mapping.fixed_value or "")
            or CanonicalDispatchOutcome("dispatched", "ha-command-after-restart")
        ),
        commitment_store=ActivePlanCommitmentStore(commitment_path),
    )

    commitment = ActivePlanCommitmentStore(commitment_path).load("home-battery")
    assert commitment is not None
    future = _future_pv_run(
        replace(
            active,
            planning_input=replace(
                active.planning_input,
                active_plan_commitments=(commitment,),
            ),
        )
    )
    future = replace(
        future,
        primitive_boundary=replace(
            future.primitive_boundary,
            current_vendor_mode="Nul op de meter",
        ),
    )
    held = runtime.apply(future)

    assert calls == ["Nul op de meter"]
    assert held.vendor_result.status == (
        "active_plan_preserved_after_blocked_replan"
    )
    assert held.vendor_result.planned_vendor_mode == "Nul op de meter"


def test_selected_future_pv_plan_is_persisted_before_window_start(tmp_path) -> None:
    commitment_path = tmp_path / "commitment.json"
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: CanonicalDispatchOutcome(
            "dispatched", "ha-command-test"
        ),
        commitment_store=ActivePlanCommitmentStore(commitment_path),
    )
    active = _live_run()
    shift = timedelta(hours=1)
    plan = active.execution_plan_set.plans[0]
    scheduled = replace(
        active,
        execution_plan_set=replace(
            active.execution_plan_set,
            plans=(
                replace(
                    plan,
                    valid_from=plan.valid_from + shift,
                    valid_until=plan.valid_until + shift,
                    segments=tuple(
                        replace(
                            segment,
                            starts_at=segment.starts_at + shift,
                            ends_at=segment.ends_at + shift,
                        )
                        for segment in plan.segments
                    ),
                ),
            ),
        ),
    )

    runtime.apply(scheduled)

    commitment = ActivePlanCommitmentStore(commitment_path).load("home-battery")
    assert commitment is not None
    assert commitment.starts_at > scheduled.planning_input.captured_at
    assert commitment.plan_id == scheduled.execution_plan_set.plans[0].plan_id


def test_future_commitment_does_not_preserve_nom_before_window_start(
    tmp_path,
) -> None:
    calls: list[str] = []
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append(mapping.fixed_value or "")
            or CanonicalDispatchOutcome("dispatched", "ha-command-test")
        ),
        commitment_store=ActivePlanCommitmentStore(tmp_path / "commitment.json"),
    )
    active = _live_run()
    plan = active.execution_plan_set.plans[0]
    pv_segment = next(
        item for item in plan.segments if item.charge_source_policy == "pv_only"
    )
    baseline_segment = next(
        item for item in plan.segments if item.charge_source_policy is None
    )
    future = _future_pv_run(active)
    future = replace(
        future,
        execution_plan_set=replace(
            active.execution_plan_set,
            plans=(
                replace(
                    plan,
                    segments=(
                        replace(
                            baseline_segment,
                            starts_at=active.planning_input.captured_at,
                            ends_at=pv_segment.ends_at,
                        ),
                        replace(
                            pv_segment,
                            starts_at=pv_segment.ends_at,
                            ends_at=baseline_segment.ends_at,
                        ),
                    ),
                ),
            ),
        ),
        primitive_boundary=replace(
            future.primitive_boundary,
            current_vendor_mode="Nul op de meter",
        ),
    )
    assert future.primitive_boundary.planned_vendor_mode == "Alleen slim ontladen"

    result = runtime.apply(future)

    commitment = runtime.commitment_store.load("home-battery")
    assert commitment is not None
    assert future.planning_input.captured_at < commitment.starts_at
    assert calls == ["Alleen slim ontladen"]
    assert result.vendor_result.status == "dispatched"


def test_completed_storage_target_may_end_committed_pv_plan(tmp_path) -> None:
    calls: list[str] = []
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append(mapping.fixed_value or "")
            or CanonicalDispatchOutcome("dispatched", "ha-command-test")
        ),
        commitment_store=ActivePlanCommitmentStore(tmp_path / "commitment.json"),
    )
    active = _live_run()
    runtime.apply(active)
    future = _future_pv_run(active)
    completed = replace(
        future,
        evaluation=replace(
            future.evaluation,
            decisive_step="hard_constraint:storage_requirement_already_satisfied",
        ),
        primitive_boundary=replace(
            future.primitive_boundary,
            current_vendor_mode="Nul op de meter",
        ),
    )

    result = runtime.apply(completed)

    assert calls == ["Nul op de meter", "Alleen slim ontladen"]
    assert result.vendor_result.status == "dispatched"


def _future_pv_run(active: CanonicalPipelineRun) -> CanonicalPipelineRun:
    planning_input = active.planning_input
    assert planning_input.pv_energy_timeline is not None
    assert planning_input.household_load_forecast is not None
    shift = timedelta(hours=1)
    return CanonicalPipeline().run(
        planning_input=replace(
            planning_input,
            horizon_end=planning_input.horizon_end + shift,
            pv_energy_timeline=replace(
                planning_input.pv_energy_timeline,
                intervals=tuple(
                    replace(
                        interval,
                        starts_at=interval.starts_at + shift,
                        ends_at=interval.ends_at + shift,
                    )
                    for interval in planning_input.pv_energy_timeline.intervals
                ),
            ),
            household_load_forecast=replace(
                planning_input.household_load_forecast,
                intervals=tuple(
                    replace(
                        interval,
                        starts_at=interval.starts_at + shift,
                        ends_at=interval.ends_at + shift,
                    )
                    for interval in planning_input.household_load_forecast.intervals
                ),
            ),
        ),
        control_change_allowed=True,
    )
