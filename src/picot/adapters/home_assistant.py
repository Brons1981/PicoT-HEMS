"""Home Assistant adapter and dry-run dispatcher defined by ADR-035."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Protocol

from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import (
    HomeAssistantCommandMapping,
    HomeAssistantDispatchMode,
    HomeAssistantDispatchResult,
    HomeAssistantDispatchStatus,
    HomeAssistantServiceCall,
)

IMPLEMENTATION_VERSION = "home-assistant-adapter-v1"


class HomeAssistantTransport(Protocol):
    """Runtime-only transport for an already validated service call."""

    def send(self, call: HomeAssistantServiceCall) -> int:
        """Send one call and return a response status."""


class HomeAssistantAdapter:
    """Translate one execution request through one explicit HA mapping."""

    def translate(
        self,
        request: ExecutionPrimitiveRequest,
        mapping: HomeAssistantCommandMapping,
        *,
        created_at: datetime,
        dispatch_mode: HomeAssistantDispatchMode = HomeAssistantDispatchMode.DRY_RUN,
    ) -> HomeAssistantServiceCall:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Service call creation time must be timezone-aware.")
        if not mapping.enabled:
            raise ValueError("Home Assistant command mapping is disabled.")
        if request.capability_id != mapping.capability_id:
            raise ValueError("Capability ID does not match Home Assistant mapping.")
        if request.execution_scope_id != mapping.execution_scope_id:
            raise ValueError("Execution scope does not match Home Assistant mapping.")
        if request.primitive is not mapping.primitive:
            raise ValueError("Execution Primitive is not supported by this mapping.")
        if request.primitive is not ExecutionPrimitive.CHARGE_AT_POWER:
            raise ValueError("Adapter v1 supports only CHARGE_AT_POWER.")
        if mapping.domain != "number" or mapping.service != "set_value":
            raise ValueError("Adapter v1 requires number.set_value mapping.")
        if request.requested_power_w is None:
            raise ValueError("CHARGE_AT_POWER requires requested power.")

        value = request.requested_power_w * mapping.scale_factor
        if mapping.minimum_value is not None and value < mapping.minimum_value:
            raise ValueError("Translated value is below the mapping minimum.")
        if mapping.maximum_value is not None and value > mapping.maximum_value:
            raise ValueError("Translated value exceeds the mapping maximum.")

        command_id = self._command_id(request, mapping, value)
        return HomeAssistantServiceCall(
            command_id=command_id,
            source_request_id=request.request_id,
            plan_set_id=request.plan_set_id,
            plan_id=request.plan_id,
            segment_id=request.segment_id,
            execution_scope_id=request.execution_scope_id,
            capability_id=request.capability_id,
            mapping_id=mapping.mapping_id,
            mapping_version=mapping.mapping_version,
            domain=mapping.domain,
            service=mapping.service,
            target=(("entity_id", mapping.entity_id),),
            service_data=((mapping.value_key, value),),
            created_at=created_at,
            dispatch_mode=dispatch_mode,
            implementation_version=IMPLEMENTATION_VERSION,
        )

    @staticmethod
    def _command_id(
        request: ExecutionPrimitiveRequest,
        mapping: HomeAssistantCommandMapping,
        value: float,
    ) -> str:
        source = (
            f"{request.request_id}|{mapping.mapping_id}|{mapping.mapping_version}|"
            f"{mapping.domain}|{mapping.service}|{mapping.entity_id}|{value}|"
            f"{IMPLEMENTATION_VERSION}"
        )
        return f"ha-command-{sha256(source.encode()).hexdigest()[:16]}"


class HomeAssistantDispatcher:
    """Dispatch an immutable service call or record an exact dry-run."""

    def dispatch(
        self,
        call: HomeAssistantServiceCall,
        *,
        attempted_at: datetime,
        transport: HomeAssistantTransport | None = None,
    ) -> HomeAssistantDispatchResult:
        if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
            raise ValueError("Dispatch attempt time must be timezone-aware.")
        if call.dispatch_mode is HomeAssistantDispatchMode.DRY_RUN:
            return HomeAssistantDispatchResult(
                command_id=call.command_id,
                dispatch_mode=call.dispatch_mode,
                status=HomeAssistantDispatchStatus.DRY_RUN_ONLY,
                attempted_at=attempted_at,
            )
        if transport is None:
            return HomeAssistantDispatchResult(
                command_id=call.command_id,
                dispatch_mode=call.dispatch_mode,
                status=HomeAssistantDispatchStatus.REJECTED,
                attempted_at=attempted_at,
                error_reason="LIVE dispatch requires an explicit Home Assistant transport.",
            )
        try:
            response_status = transport.send(call)
        except Exception as exc:  # pragma: no cover - transport boundary
            return HomeAssistantDispatchResult(
                command_id=call.command_id,
                dispatch_mode=call.dispatch_mode,
                status=HomeAssistantDispatchStatus.FAILED,
                attempted_at=attempted_at,
                error_reason=str(exc) or exc.__class__.__name__,
            )
        status = (
            HomeAssistantDispatchStatus.DISPATCHED
            if 200 <= response_status < 300
            else HomeAssistantDispatchStatus.FAILED
        )
        return HomeAssistantDispatchResult(
            command_id=call.command_id,
            dispatch_mode=call.dispatch_mode,
            status=status,
            attempted_at=attempted_at,
            response_status=response_status,
            error_reason=(
                None if status is HomeAssistantDispatchStatus.DISPATCHED else "Home Assistant rejected the service call."
            ),
        )
