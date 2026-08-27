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
from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
)
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


def test_canonical_runtime_neither_creates_nor_changes_commitments(tmp_path) -> None:
    store = ActivePlanCommitmentStore(tmp_path / "commitment.json")
    active = _live_run()
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: CanonicalDispatchOutcome(
            "dispatched", "ha-command-test"
        ),
        commitment_store=store,
    )

    runtime.apply(active)

    assert store.load("home-battery") is None
    mep_commitment = ActivePlanCommitment(
        execution_scope_id="home-battery",
        plan_id="mep-plan",
        plan_revision=1,
        primitive="balance_bidirectional",
        source_policy="pv_only",
        starts_at=active.planning_input.captured_at,
        ends_at=active.planning_input.captured_at + timedelta(hours=1),
        target_energy_wh=8160.0,
        planner_id="mep",
        schedule_id="mep-schedule",
    )
    store.save(mep_commitment)
    completed = replace(
        _future_pv_run(active),
        evaluation=replace(
            active.evaluation,
            decisive_step="hard_constraint:storage_requirement_already_satisfied",
        ),
    )

    runtime.apply(completed)

    assert store.load("home-battery") == mep_commitment


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
