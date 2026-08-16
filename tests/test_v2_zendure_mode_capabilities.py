from datetime import UTC, datetime
from importlib import import_module

from picot.domain.execution_primitive import ExecutionPrimitive

CAPTURED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
NORMAL_MODES = (
    "Standby",
    "Handmatig",
    "Nul op de meter",
    "Alleen slim ontladen",
    "Alleen slim opladen",
    "Snel opladen",
    "Snel ontladen",
)
DYNAMIC_MODES = (
    "Dynamisch NOM",
    "Dynamisch NOM (Duur)",
    "Dynamisch Handelen",
    "Dynamisch Handelen + NOM",
)


def _derive(payload: dict[str, object]) -> object:
    module = import_module("picot.v2.zendure_mode_capabilities")
    return module.derive_zendure_mode_capability_evidence(
        payload,
        captured_at=CAPTURED_AT,
        source_entity_id="input_select.zendure_2400_ac_modus_selecteren",
        capability_id="storage-capability-home-battery",
        execution_scope_id="home-battery",
    )


def test_v2adr050_preserves_seven_normal_modes_and_excludes_four_dynamic_modes() -> None:
    evidence = _derive(
        {
            "state": "Nul op de meter",
            "attributes": {"options": [*NORMAL_MODES, *DYNAMIC_MODES]},
        }
    )

    assert evidence.status == "available"
    assert evidence.usable_vendor_modes == NORMAL_MODES
    assert evidence.excluded_dynamic_vendor_modes == DYNAMIC_MODES
    assert evidence.method_version == "zendure-mode-capability-evidence:v1"


def test_v2adr050_maps_normal_modes_without_delegating_price_decisions() -> None:
    evidence = _derive(
        {
            "state": "Standby",
            "attributes": {"options": [*NORMAL_MODES, *DYNAMIC_MODES]},
        }
    )
    mappings = {item.vendor_mode: item for item in evidence.mappings}

    assert mappings["Standby"].primitives == (ExecutionPrimitive.STANDBY,)
    assert mappings["Nul op de meter"].primitives == (ExecutionPrimitive.BALANCE_BIDIRECTIONAL,)
    assert mappings["Alleen slim ontladen"].primitives == (
        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
    )
    assert mappings["Alleen slim opladen"].primitives == (ExecutionPrimitive.BALANCE_CHARGE_ONLY,)
    assert mappings["Handmatig"].primitives == (
        ExecutionPrimitive.CHARGE_AT_POWER,
        ExecutionPrimitive.DISCHARGE_AT_POWER,
    )
    assert mappings["Handmatig"].power_semantics == "explicit_signed_power"
    assert mappings["Snel opladen"].power_semantics == "integration_configured_maximum"
    assert mappings["Snel ontladen"].power_semantics == "integration_configured_maximum"
    assert not any(mode in mappings for mode in DYNAMIC_MODES)


def test_v2adr050_missing_mode_options_fail_closed() -> None:
    evidence = _derive({"state": "Nul op de meter", "attributes": {}})

    assert evidence.status == "unavailable"
    assert evidence.unavailable_reason == "mode_options_missing"
    assert evidence.usable_vendor_modes == ()
    assert evidence.mappings == ()
