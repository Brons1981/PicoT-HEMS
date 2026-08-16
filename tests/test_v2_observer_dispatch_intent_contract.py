from importlib import import_module

from test_v2_observer_primitive_request_contract import (
    _planner_owned_provenance,
)
from test_v2_storage_mode_provenance_integration import (
    BASE,
    MODE_ENTITY,
    _run,
)

from picot.v2.projection import project


def test_ready_adapter_translation_gets_stable_observer_dispatch_intent() -> None:
    provenance = _planner_owned_provenance()
    first = _run(
        current_mode="Alleen slim opladen",
        provenance=provenance,
    )
    second = _run(
        current_mode="Alleen slim opladen",
        provenance=provenance,
    )

    result = first.vendor_result
    assert first.adapter_boundary.translation_id is not None
    assert result.dispatch_intent_id is not None
    assert result.dispatch_intent_id == second.vendor_result.dispatch_intent_id
    assert result.adapter_translation_id == (
        first.adapter_boundary.translation_id
    )
    assert result.target_entity_id == MODE_ENTITY
    assert result.planned_vendor_mode == "Alleen slim opladen"
    assert result.status == "observer_dispatch_ready"
    assert result.command_id is None
    assert result.observed_result_id is None


def test_manual_override_prevents_dispatch_intent() -> None:
    module = import_module("picot.v2.storage_mode_provenance")
    overridden = module.observe_storage_mode(
        _planner_owned_provenance(),
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )

    run = _run(current_mode="Standby", provenance=overridden)

    assert run.adapter_boundary.translation_id is None
    assert run.vendor_result.dispatch_intent_id is None
    assert run.vendor_result.adapter_translation_id is None
    assert run.vendor_result.command_id is None
    assert run.vendor_result.status == "not_dispatched"


def test_projection_explains_observer_dispatch_in_normal_dutch() -> None:
    run = _run(
        current_mode="Alleen slim opladen",
        provenance=_planner_owned_provenance(),
    )
    vendor_card = project(run).cards[8]

    assert vendor_card.state == "observer_dispatch_ready"
    assert vendor_card.attributes["dispatch_intent_id"] == (
        run.vendor_result.dispatch_intent_id
    )
    assert vendor_card.attributes["adapter_translation_id"] == (
        run.adapter_boundary.translation_id
    )
    assert vendor_card.attributes["target_entity_id"] == MODE_ENTITY
    assert vendor_card.attributes["planned_vendor_mode"] == (
        "Alleen slim opladen"
    )
    assert vendor_card.attributes["command_id"] is None
    assert vendor_card.attributes["normal_result"] == (
        "De Zendure-opdracht is volledig voorbereid; PicoT kijkt nog mee "
        "en heeft niets verstuurd."
    )


def test_not_dispatched_has_normal_dutch_result() -> None:
    module = import_module("picot.v2.storage_mode_provenance")
    overridden = module.observe_storage_mode(
        _planner_owned_provenance(),
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )
    vendor_card = project(
        _run(current_mode="Standby", provenance=overridden)
    ).cards[8]

    assert vendor_card.state == "not_dispatched"
    assert vendor_card.attributes["normal_result"] == (
        "Er is geen opdracht naar Zendure verstuurd."
    )
