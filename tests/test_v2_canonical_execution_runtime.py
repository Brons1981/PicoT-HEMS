from importlib import import_module

from test_v2_storage_mode_provenance_integration import BASE, _run

from picot.v2.canonical_execution_runtime import (
    CanonicalDispatchOutcome,
    CanonicalExecutionRuntime,
)
from picot.v2.pipeline import CanonicalPipeline


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
    return CanonicalPipeline().run(
        planning_input=observer.planning_input,
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
    assert request.primitive.value == "balance_charge_only"
    assert mapping.fixed_value == "Alleen slim opladen"
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

    assert calls == ["Alleen slim opladen"]
    assert duplicate.vendor_result.status == "awaiting_mode_feedback"
