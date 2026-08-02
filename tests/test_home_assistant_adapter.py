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


def _mapping() -> HomeAssistantCommandMapping:
    return HomeAssistantCommandMapping(
        mapping_id="ha-mapping-1",
        mapping_version=1,
        capability_id="battery-charge",
        execution_scope_id="battery-main",
        primitive=ExecutionPrimitive.CHARGE_AT_POWER,
        domain="number",
        service="set_value",
        entity_id="number.battery_charge_power",
        value_key="value",
        minimum_value=0.0,
        maximum_value=2400.0,
    )


def test_adapter_translates_charge_power_deterministically() -> None:
    adapter = HomeAssistantAdapter()
    first = adapter.translate(_request(), _mapping(), created_at=NOW)
    second = adapter.translate(_request(), _mapping(), created_at=NOW)

    assert first == second
    assert first.target == (("entity_id", "number.battery_charge_power"),)
    assert first.service_data == (("value", 1200.0),)
    assert first.dispatch_mode is HomeAssistantDispatchMode.DRY_RUN


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
