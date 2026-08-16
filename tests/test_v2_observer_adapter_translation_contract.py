from dataclasses import replace
from importlib import import_module

from test_v2_observer_primitive_request_contract import (
    _planner_owned_provenance,
)
from test_v2_storage_mode_provenance_integration import BASE, _run

from picot.v2.projection import project


def test_ready_primitive_request_gets_stable_observer_translation() -> None:
    provenance = _planner_owned_provenance()
    first = _run(
        current_mode="Alleen slim opladen",
        provenance=provenance,
    )
    second = _run(
        current_mode="Alleen slim opladen",
        provenance=provenance,
    )

    translation = first.adapter_boundary
    assert first.primitive_boundary.request_id is not None
    assert translation.translation_id is not None
    assert translation.translation_id == second.adapter_boundary.translation_id
    assert translation.primitive_request_id == (
        first.primitive_boundary.request_id
    )
    assert translation.status == "observer_translation_ready"
    assert first.vendor_result.command_id is None
    assert first.vendor_result.status == "observer_dispatch_ready"


def test_manual_override_keeps_adapter_not_invoked() -> None:
    module = import_module("picot.v2.storage_mode_provenance")
    overridden = module.observe_storage_mode(
        _planner_owned_provenance(),
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )

    run = _run(current_mode="Standby", provenance=overridden)

    assert run.primitive_boundary.request_id is None
    assert run.adapter_boundary.translation_id is None
    assert run.adapter_boundary.primitive_request_id is None
    assert run.adapter_boundary.status == "not_invoked"
    assert run.vendor_result.status == "not_dispatched"


def test_projection_explains_adapter_translation_in_normal_dutch() -> None:
    run = _run(
        current_mode="Alleen slim opladen",
        provenance=_planner_owned_provenance(),
    )
    adapter_card = project(run).cards[7]

    assert adapter_card.state == "observer_translation_ready"
    assert adapter_card.attributes["translation_id"] == (
        run.adapter_boundary.translation_id
    )
    assert adapter_card.attributes["primitive_request_id"] == (
        run.primitive_boundary.request_id
    )
    assert adapter_card.attributes["planned_vendor_mode"] == (
        "Alleen slim opladen"
    )
    assert adapter_card.attributes["normal_result"] == (
        "De laadopdracht is vertaald voor Zendure; PicoT kijkt nog mee "
        "en verstuurt niets."
    )


def test_not_emitted_primitive_has_normal_dutch_result() -> None:
    run = _run(
        current_mode="Alleen slim opladen",
        provenance=_planner_owned_provenance(),
    )
    no_request = replace(
        run,
        primitive_boundary=replace(
            run.primitive_boundary,
            request_id=None,
            status="not_emitted",
            planned_primitive=None,
            planned_vendor_mode=None,
            mapping_status="not_assessed",
            blockers=(),
        ),
        adapter_boundary=replace(
            run.adapter_boundary,
            translation_id=None,
            primitive_request_id=None,
            status="not_invoked",
        ),
    )

    primitive_card = project(no_request).cards[6]
    assert primitive_card.attributes["normal_result"] == (
        "Er is nu geen uitvoerbare opdracht; PicoT stuurt niets naar Zendure."
    )
