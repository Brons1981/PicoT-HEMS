from importlib import import_module

from test_v2_storage_mode_provenance_integration import BASE, _run

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.projection import project


def _planner_owned_provenance() -> object:
    module = import_module("picot.v2.storage_mode_provenance")
    provenance = module.initial_storage_mode_provenance(
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )
    provenance = module.record_planner_mode_application(
        provenance,
        vendor_mode="Alleen slim opladen",
        applied_at=BASE,
        application_id="application-primitive-request-test",
    )
    return module.observe_storage_mode(
        provenance,
        observed_vendor_mode="Alleen slim opladen",
        observed_at=BASE,
    )


def test_due_planner_owned_plan_creates_stable_observer_request() -> None:
    provenance = _planner_owned_provenance()
    first = _run(
        current_mode="Alleen slim opladen",
        provenance=provenance,
    )
    second = _run(
        current_mode="Alleen slim opladen",
        provenance=provenance,
    )

    request = first.primitive_boundary
    assert request.request_id is not None
    assert request.request_id == second.primitive_boundary.request_id
    assert request.status == "observer_request_ready"
    assert request.planned_primitive is ExecutionPrimitive.BALANCE_CHARGE_ONLY
    assert request.blockers == ("observer_only_authority",)
    assert first.adapter_boundary.status == "not_invoked"
    assert first.vendor_result.status == "not_dispatched"


def test_manual_override_prevents_primitive_request_creation() -> None:
    module = import_module("picot.v2.storage_mode_provenance")
    provenance = _planner_owned_provenance()
    overridden = module.observe_storage_mode(
        provenance,
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )

    run = _run(current_mode="Standby", provenance=overridden)

    assert run.primitive_boundary.request_id is None
    assert run.primitive_boundary.status == "dry_run_blocked"
    assert run.primitive_boundary.blockers == (
        "manual_override_active",
        "observer_only_authority",
    )
    assert run.adapter_boundary.status == "not_invoked"
    assert run.vendor_result.status == "not_dispatched"


def test_projection_explains_observer_request_in_normal_dutch() -> None:
    run = _run(
        current_mode="Alleen slim opladen",
        provenance=_planner_owned_provenance(),
    )
    primitive_card = project(run).cards[6]

    assert primitive_card.state == "observer_request_ready"
    assert primitive_card.attributes["request_id"] == (
        run.primitive_boundary.request_id
    )
    assert primitive_card.attributes["normal_result"] == (
        "De uitvoerbare laadopdracht is voorbereid; PicoT kijkt nog mee "
        "en stuurt niets naar Zendure."
    )
