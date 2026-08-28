from dataclasses import replace

from legacy_cp_pipeline import CanonicalPipeline
from test_v2_delegated_storage_pipeline_integration import (
    BASE,
    CAPABILITY_ID,
    _snapshot,
)

from picot.domain.execution_primitive import ExecutionPrimitive
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


def _run_with_mode(
    *,
    current_mode: str = "Standby",
    options: tuple[str, ...] = NORMAL_MODES,
) -> object:
    evidence = derive_zendure_mode_capability_evidence(
        {
            "state": current_mode,
            "attributes": {"options": list(options)},
        },
        captured_at=BASE,
        source_entity_id=MODE_ENTITY,
        capability_id=CAPABILITY_ID,
        execution_scope_id="home-battery",
    )
    snapshot = replace(
        _snapshot(),
        storage_mode_capability_evidence=evidence,
    )
    return CanonicalPipeline().run(planning_input=snapshot)


def test_due_plan_validates_unique_mapping_but_stays_blocked() -> None:
    run = _run_with_mode()

    assessment = run.primitive_boundary
    assert assessment.status == "dry_run_blocked"
    assert assessment.request_id is None
    assert assessment.planned_primitive is ExecutionPrimitive.BALANCE_CHARGE_ONLY
    assert assessment.mapping_status == "validated"
    assert assessment.source_entity_id == MODE_ENTITY
    assert assessment.current_vendor_mode == "Standby"
    assert assessment.planned_vendor_mode == "Alleen slim opladen"
    assert assessment.mapping_method_version == (
        "zendure-mode-capability-evidence:v1"
    )
    assert assessment.blockers == (
        "manual_override_provenance_unverified",
        "observer_only_authority",
    )
    assert run.adapter_boundary.translation_id is None
    assert run.adapter_boundary.status == "not_invoked"
    assert run.vendor_result.command_id is None
    assert run.vendor_result.status == "not_dispatched"


def test_missing_vendor_mapping_fails_closed_without_substitution() -> None:
    run = _run_with_mode(options=("Standby", "Nul op de meter"))

    assessment = run.primitive_boundary
    assert assessment.status == "dry_run_blocked"
    assert assessment.mapping_status == "unavailable"
    assert assessment.planned_vendor_mode is None
    assert assessment.blockers == (
        "primitive_vendor_mapping_unavailable",
        "manual_override_provenance_unverified",
        "observer_only_authority",
    )
    assert run.adapter_boundary.translation_id is None
    assert run.vendor_result.command_id is None


def test_dynamic_current_mode_is_never_silently_overwritten() -> None:
    run = _run_with_mode(
        current_mode="Dynamisch NOM",
        options=(*NORMAL_MODES, "Dynamisch NOM"),
    )

    assessment = run.primitive_boundary
    assert assessment.status == "dry_run_blocked"
    assert assessment.mapping_status == "validated"
    assert assessment.planned_vendor_mode == "Alleen slim opladen"
    assert assessment.blockers == (
        "current_vendor_mode_excluded",
        "manual_override_provenance_unverified",
        "observer_only_authority",
    )
    assert run.adapter_boundary.translation_id is None
    assert run.vendor_result.command_id is None


def test_projection_exposes_dry_run_mapping_and_blockers() -> None:
    projection = project(_run_with_mode())
    primitive_card = projection.cards[6]
    adapter_card = projection.cards[7]
    vendor_card = projection.cards[8]

    assert primitive_card.state == "dry_run_blocked"
    assert primitive_card.attributes["planned_primitive"] == (
        "balance_charge_only"
    )
    assert primitive_card.attributes["mapping_status"] == "validated"
    assert primitive_card.attributes["planned_vendor_mode"] == (
        "Alleen slim opladen"
    )
    assert primitive_card.attributes["blockers"] == [
        "manual_override_provenance_unverified",
        "observer_only_authority",
    ]
    assert adapter_card.state == "not_invoked"
    assert vendor_card.state == "not_dispatched"
