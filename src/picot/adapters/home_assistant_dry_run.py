"""Controlled Home Assistant dry-run preview for the first PicoT capability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from picot.adapters.home_assistant import HomeAssistantAdapter, HomeAssistantDispatcher
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import (
    HomeAssistantCommandMapping,
    HomeAssistantDispatchMode,
    HomeAssistantDispatchResult,
    HomeAssistantServiceCall,
)


@dataclass(frozen=True, slots=True)
class HomeAssistantDryRunPreview:
    """Exact service-call preview without any network activity."""

    endpoint: str
    payload_json: str
    service_call: HomeAssistantServiceCall
    dispatch_result: HomeAssistantDispatchResult


def build_zendure_manual_power_dry_run(
    *,
    base_url: str,
    requested_power_w: float,
    created_at: datetime,
) -> HomeAssistantDryRunPreview:
    """Build the accepted first-capability dry-run for manual Zendure power."""
    request = ExecutionPrimitiveRequest(
        request_id="first-live-test-request",
        plan_set_id="first-live-test-plan-set",
        plan_id="first-live-test-plan",
        plan_revision=1,
        segment_id="first-live-test-segment",
        execution_scope_id="zendure-2400-ac",
        capability_id="zendure-2400-ac-manual-charge-power",
        primitive=ExecutionPrimitive.CHARGE_AT_POWER,
        requested_at=created_at,
        requested_power_w=requested_power_w,
    )
    mapping = HomeAssistantCommandMapping(
        mapping_id="ha-zendure-2400-ac-manual-power-v1",
        mapping_version=1,
        capability_id=request.capability_id,
        execution_scope_id=request.execution_scope_id,
        primitive=request.primitive,
        domain="input_number",
        service="set_value",
        entity_id="input_number.zendure_2400_ac_handmatig_vermogen",
        value_key="value",
        minimum_value=0.0,
        maximum_value=2400.0,
    )
    call = HomeAssistantAdapter().translate(
        request,
        mapping,
        created_at=created_at,
        dispatch_mode=HomeAssistantDispatchMode.DRY_RUN,
    )
    result = HomeAssistantDispatcher().dispatch(call, attempted_at=created_at)
    payload: dict[str, str | float] = dict(call.target)
    for key, value in call.service_data:
        payload[key] = value
    endpoint = (
        f"{base_url.rstrip('/')}/api/services/{call.domain}/{call.service}"
    )
    return HomeAssistantDryRunPreview(
        endpoint=endpoint,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        service_call=call,
        dispatch_result=result,
    )
