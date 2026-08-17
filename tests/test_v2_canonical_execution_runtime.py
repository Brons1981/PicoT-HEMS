from dataclasses import replace
from datetime import timedelta
from importlib import import_module

from test_v2_storage_mode_provenance_integration import BASE, _run

from picot.v2.canonical_execution_runtime import (
    CanonicalDispatchOutcome,
    CanonicalExecutionRuntime,
)
from picot.v2.contracts import BMSCalibrationEvidence
from picot.v2.household_planning_regime import HouseholdPlanningRegime
from picot.v2.pipeline import CanonicalPipeline
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


def _live_run() -> object:
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


def test_self_consumption_regime_uses_nom_before_future_pv_window() -> None:
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
        "balance_bidirectional"
    )
    assert run.primitive_boundary.planned_vendor_mode == "Nul op de meter"


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
