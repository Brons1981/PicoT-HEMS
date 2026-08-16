from dataclasses import replace
from importlib import import_module

from test_v2_delegated_storage_pipeline_integration import (
    BASE,
    CAPABILITY_ID,
    _snapshot,
)

from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project
from picot.v2.zendure_mode_capabilities import (
    derive_zendure_mode_capability_evidence,
)

MODE_ENTITY = "input_select.zendure_2400_ac_modus_selecteren"
NORMAL_MODES = (
    "Standby",
    "Handmatig",
    "Nul op de meter",
    "Alleen slim ontladen",
    "Alleen slim opladen",
    "Snel opladen",
    "Snel ontladen",
)


def _module() -> object:
    return import_module("picot.v2.storage_mode_provenance")


def _run(*, current_mode: str, provenance: object) -> object:
    evidence = derive_zendure_mode_capability_evidence(
        {
            "state": current_mode,
            "attributes": {"options": list(NORMAL_MODES)},
        },
        captured_at=BASE,
        source_entity_id=MODE_ENTITY,
        capability_id=CAPABILITY_ID,
        execution_scope_id="home-battery",
    )
    snapshot = replace(
        _snapshot(),
        storage_mode_capability_evidence=evidence,
        storage_mode_control_provenance=provenance,
    )
    return CanonicalPipeline().run(planning_input=snapshot)


def test_initial_observation_remains_unverified_and_blocked() -> None:
    module = _module()
    provenance = module.initial_storage_mode_provenance(
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )

    assert provenance.status == "unverified"
    assert provenance.manual_override_active is False
    assert provenance.transition_reason == "no_planner_application_recorded"
    run = _run(current_mode="Standby", provenance=provenance)
    assert run.primitive_boundary.blockers == (
        "manual_override_provenance_unverified",
        "observer_only_authority",
    )


def test_matching_planner_application_is_planner_owned() -> None:
    module = _module()
    initial = module.initial_storage_mode_provenance(
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )
    provenance = module.record_planner_mode_application(
        initial,
        vendor_mode="Alleen slim opladen",
        applied_at=BASE,
        application_id="application-test-1",
    )
    provenance = module.observe_storage_mode(
        provenance,
        observed_vendor_mode="Alleen slim opladen",
        observed_at=BASE,
    )

    assert provenance.status == "planner_owned"
    assert provenance.manual_override_active is False
    assert provenance.last_planner_vendor_mode == "Alleen slim opladen"
    run = _run(
        current_mode="Alleen slim opladen",
        provenance=provenance,
    )
    assert run.primitive_boundary.blockers == ("observer_only_authority",)


def test_user_change_after_planner_application_activates_override() -> None:
    module = _module()
    provenance = module.record_planner_mode_application(
        module.initial_storage_mode_provenance(
            observed_vendor_mode="Standby",
            observed_at=BASE,
        ),
        vendor_mode="Alleen slim opladen",
        applied_at=BASE,
        application_id="application-test-2",
    )
    provenance = module.observe_storage_mode(
        provenance,
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )

    assert provenance.status == "manual_override"
    assert provenance.manual_override_active is True
    assert provenance.transition_reason == "observed_mode_differs_from_planner_mode"
    run = _run(current_mode="Standby", provenance=provenance)
    assert run.primitive_boundary.blockers == (
        "manual_override_active",
        "observer_only_authority",
    )


def test_manual_override_only_clears_through_explicit_reset() -> None:
    module = _module()
    provenance = module.record_planner_mode_application(
        module.initial_storage_mode_provenance(
            observed_vendor_mode="Standby",
            observed_at=BASE,
        ),
        vendor_mode="Alleen slim opladen",
        applied_at=BASE,
        application_id="application-test-3",
    )
    overridden = module.observe_storage_mode(
        provenance,
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )
    still_overridden = module.observe_storage_mode(
        overridden,
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )
    released = module.reset_storage_mode_override(
        still_overridden,
        observed_vendor_mode="Standby",
        reset_at=BASE,
        reset_id="reset-test-1",
    )

    assert still_overridden.status == "manual_override"
    assert still_overridden.manual_override_active is True
    assert released.status == "released"
    assert released.manual_override_active is False
    assert released.transition_reason == "explicit_user_reset"
    run = _run(current_mode="Standby", provenance=released)
    assert run.primitive_boundary.blockers == ("observer_only_authority",)


def test_projection_exposes_mode_provenance_without_recalculation() -> None:
    module = _module()
    provenance = module.initial_storage_mode_provenance(
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )
    primitive_card = project(
        _run(current_mode="Standby", provenance=provenance)
    ).cards[6]

    assert primitive_card.attributes["mode_provenance_status"] == "unverified"
    assert primitive_card.attributes["manual_override_active"] is False
    assert primitive_card.attributes["mode_provenance_reason"] == (
        "no_planner_application_recorded"
    )
