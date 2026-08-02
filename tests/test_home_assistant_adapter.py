from __future__ import annotations

from datetime import UTC, datetime

import pytest

from picot.adapters.home_assistant import HomeAssistantAdapter, HomeAssistantDispatcher
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import (
    HomeAssistantCommandMapping,
    HomeAssistantDispatchMode,
    HomeAssistantDispatchStatus,
)

NOW = datetime(2026, 8, 2, 7, 30, tzinfo=UTC)


def _request(power: float = 1200.0) -> ExecutionPrimitiveRequest:
    return ExecutionPrimitiveRequest(
        request_id="request-1",
        plan_set_id="plan-set-1",
        plan_id="plan-1",
        plan_revision=1,
        segment_id="segment-1",
        execution_scope_id="battery-main",
        capability_id="battery-charge",
        primitive=ExecutionPrimitive.CHARGE_AT_POWER,
        requested_at=NOW,
        requested_power_w=power,
    )


def _mapping(
    *,
    domain: str = "number",
    entity_id: str = "number.battery_charge_power",
) -> HomeAssistantCommandMapping:
    return HomeAssistantCommandMapping(
        mapping_id="ha-mapping-1",
        mapping_version=1,
        capability_id="battery-charge",
        execution_scope_id="battery-main",
        primitive=ExecutionPrimitive.CHARGE_AT_POWER,
        domain=domain,
        service="set_value",
        entity_id=entity_id,
        value_key="value",
        minimum_value=0.0,
        maximum_value=2400.0,
    )


def _mode_request(primitive: ExecutionPrimitive) -> ExecutionPrimitiveRequest:
    return ExecutionPrimitiveRequest(
        request_id=f"request-{primitive.value}",
        plan_set_id="plan-set-1",
        plan_id="plan-1",
        plan_revision=1,
        segment_id=f"segment-{primitive.value}",
        execution_scope_id="zendure-2400-ac",
        capability_id="zendure-operating-mode",
        primitive=primitive,
        requested_at=NOW,
    )


def _mode_mapping(
    primitive: ExecutionPrimitive,
    option: str,
) -> HomeAssistantCommandMapping:
    return HomeAssistantCommandMapping(
        mapping_id=f"ha-zendure-mode-{primitive.value}-v1",
        mapping_version=1,
        capability_id="zendure-operating-mode",
        execution_scope_id="zendure-2400-ac",
        primitive=primitive,
        domain="input_select",
        service="select_option",
        entity_id="input_select.zendure_2400_ac_modus_selecteren",
        value_key="option",
        fixed_value=option,
    )


def test_adapter_translates_charge_power_deterministically() -> None:
    adapter = HomeAssistantAdapter()
    first = adapter.translate(_request(), _mapping(), created_at=NOW)
    second = adapter.translate(_request(), _mapping(), created_at=NOW)

    assert first == second
    assert first.target == (("entity_id", "number.battery_charge_power"),)
    assert first.service_data == (("value", 1200.0),)
    assert first.dispatch_mode is HomeAssistantDispatchMode.DRY_RUN


def test_adapter_translates_input_number_charge_power() -> None:
    mapping = _mapping(
        domain="input_number",
        entity_id="input_number.zendure_2400_ac_handmatig_vermogen",
    )

    call = HomeAssistantAdapter().translate(_request(), mapping, created_at=NOW)

    assert call.domain == "input_number"
    assert call.service == "set_value"
    assert call.target == (
        ("entity_id", "input_number.zendure_2400_ac_handmatig_vermogen"),
    )
    assert call.service_data == (("value", 1200.0),)


@pytest.mark.parametrize(
    ("primitive", "option"),
    [
        (ExecutionPrimitive.BALANCE_DISCHARGE_ONLY, "Alleen slim ontladen"),
        (ExecutionPrimitive.BALANCE_BIDIRECTIONAL, "Nul op de meter"),
    ],
)
def test_adapter_translates_initial_zendure_modes(
    primitive: ExecutionPrimitive,
    option: str,
) -> None:
    call = HomeAssistantAdapter().translate(
        _mode_request(primitive),
        _mode_mapping(primitive, option),
        created_at=NOW,
    )

    assert call.domain == "input_select"
    assert call.service == "select_option"
    assert call.target == (
        ("entity_id", "input_select.zendure_2400_ac_modus_selecteren"),
    )
    assert call.service_data == (("option", option),)


def test_adapter_rejects_mode_mapping_without_explicit_option() -> None:
    mapping = _mode_mapping(
        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
        "Alleen slim ontladen",
    )
    invalid = HomeAssistantCommandMapping(
        mapping_id=mapping.mapping_id,
        mapping_version=mapping.mapping_version,
        capability_id=mapping.capability_id,
        execution_scope_id=mapping.execution_scope_id,
        primitive=mapping.primitive,
        domain=mapping.domain,
        service=mapping.service,
        entity_id=mapping.entity_id,
        value_key=mapping.value_key,
    )

    with pytest.raises(ValueError, match="explicit fixed option"):
        HomeAssistantAdapter().translate(
            _mode_request(ExecutionPrimitive.BALANCE_DISCHARGE_ONLY),
            invalid,
            created_at=NOW,
        )


def test_dry_run_never_requires_transport() -> None:
    call = HomeAssistantAdapter().translate(_request(), _mapping(), created_at=NOW)
    result = HomeAssistantDispatcher().dispatch(call, attempted_at=NOW)

    assert result.status is HomeAssistantDispatchStatus.DRY_RUN_ONLY
    assert result.response_status is None


def test_live_dispatch_without_transport_is_rejected() -> None:
    call = HomeAssistantAdapter().translate(
        _request(),
        _mapping(),
        created_at=NOW,
        dispatch_mode=HomeAssistantDispatchMode.LIVE,
    )
    result = HomeAssistantDispatcher().dispatch(call, attempted_at=NOW)

    assert result.status is HomeAssistantDispatchStatus.REJECTED


def test_adapter_rejects_value_above_mapping_limit() -> None:
    with pytest.raises(ValueError, match="maximum"):
        HomeAssistantAdapter().translate(
            _request(2500.0),
            _mapping(),
            created_at=NOW,
        )


def test_adapter_rejects_scope_mismatch() -> None:
    mapping = HomeAssistantCommandMapping(
        mapping_id="ha-mapping-1",
        mapping_version=1,
        capability_id="battery-charge",
        execution_scope_id="other-battery",
        primitive=ExecutionPrimitive.CHARGE_AT_POWER,
        domain="number",
        service="set_value",
        entity_id="number.battery_charge_power",
        value_key="value",
    )
    with pytest.raises(ValueError, match="scope"):
        HomeAssistantAdapter().translate(_request(), mapping, created_at=NOW)
