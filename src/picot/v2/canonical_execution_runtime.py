"""Controlled Home Assistant boundary for canonical live execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from picot.adapters.home_assistant import (
    HomeAssistantAdapter,
    HomeAssistantDispatcher,
)
from picot.adapters.home_assistant_http import HomeAssistantHttpTransport
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.home_assistant import (
    HomeAssistantCommandMapping,
    HomeAssistantDispatchMode,
)
from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.live_pv_canary_runtime import SUPERVISOR_BASE_URL
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

NOM_VENDOR_MODE = "Nul op de meter"
SMART_DISCHARGE_VENDOR_MODE = "Alleen slim ontladen"


@dataclass(frozen=True, slots=True)
class CanonicalDispatchOutcome:
    """Exact result returned by the external dispatch boundary."""

    status: str
    command_id: str


DispatchCanonicalMode = Callable[
    [ExecutionPrimitiveRequest, HomeAssistantCommandMapping],
    CanonicalDispatchOutcome,
]


@dataclass(slots=True)
class CanonicalExecutionRuntime:
    """Consume one approved canonical dispatch intent idempotently."""

    dispatch: DispatchCanonicalMode
    commitment_store: ActivePlanCommitmentStore | None = None
    _pending_vendor_mode: str | None = None

    def reset_pending_state(self) -> None:
        """Drop only process-local dispatch state after a manual plan reset."""

        self._pending_vendor_mode = None

    def apply(self, run: CanonicalPipelineRun) -> CanonicalPipelineRun:
        """Dispatch one due intent, or preserve the fail-closed result."""
        boundary = run.primitive_boundary
        if run.vendor_result.status != "dispatch_ready":
            return run
        if (
            boundary.request_id is None
            or boundary.planned_primitive is None
            or boundary.source_entity_id is None
            or boundary.planned_vendor_mode is None
        ):
            return run

        due = next(
            (
                (plan, segment)
                for plan in run.execution_plan_set.plans
                for segment in plan.segments
                if segment.starts_at <= run.planning_input.captured_at < segment.ends_at
            ),
            None,
        )
        if boundary.current_vendor_mode == boundary.planned_vendor_mode:
            self._pending_vendor_mode = None
            return replace(
                run,
                vendor_result=replace(
                    run.vendor_result,
                    status="already_active",
                ),
            )
        if self._pending_vendor_mode == boundary.planned_vendor_mode:
            return replace(
                run,
                vendor_result=replace(
                    run.vendor_result,
                    status="awaiting_mode_feedback",
                ),
            )

        if due is None:
            return run
        plan, segment = due
        request = ExecutionPrimitiveRequest(
            request_id=boundary.request_id,
            plan_set_id=run.execution_plan_set.plan_set_id,
            plan_id=plan.plan_id,
            plan_revision=1,
            segment_id=segment.segment_id,
            execution_scope_id=plan.execution_scope_id,
            capability_id=segment.capability_id,
            primitive=boundary.planned_primitive,
            requested_at=run.planning_input.captured_at,
            requested_power_w=segment.requested_power_w,
        )
        mapping = HomeAssistantCommandMapping(
            mapping_id=(f"canonical-zendure-mode-{boundary.planned_primitive.value}-v1"),
            mapping_version=1,
            capability_id=segment.capability_id,
            execution_scope_id=plan.execution_scope_id,
            primitive=boundary.planned_primitive,
            domain="input_select",
            service="select_option",
            entity_id=boundary.source_entity_id,
            value_key="option",
            fixed_value=boundary.planned_vendor_mode,
        )
        outcome = self.dispatch(request, mapping)
        if outcome.status == "dispatched":
            self._pending_vendor_mode = boundary.planned_vendor_mode
        return replace(
            run,
            adapter_boundary=replace(
                run.adapter_boundary,
                status="translated",
            ),
            vendor_result=replace(
                run.vendor_result,
                command_id=outcome.command_id,
                status=outcome.status,
            ),
        )

@dataclass(frozen=True, slots=True)
class HomeAssistantCanonicalModeAdapter:
    """Translate and send one canonical mode request through ADR-035."""

    token: str
    requested_at: Callable[[], datetime]

    def __call__(
        self,
        request: ExecutionPrimitiveRequest,
        mapping: HomeAssistantCommandMapping,
    ) -> CanonicalDispatchOutcome:
        now = self.requested_at()
        call = HomeAssistantAdapter().translate(
            request,
            mapping,
            created_at=now,
            dispatch_mode=HomeAssistantDispatchMode.LIVE,
        )
        transport = HomeAssistantHttpTransport(
            base_url=SUPERVISOR_BASE_URL,
            access_token=self.token,
            transport_mode=HomeAssistantDispatchMode.LIVE,
        )
        result = HomeAssistantDispatcher().dispatch(
            call,
            attempted_at=now,
            transport=transport,
        )
        return CanonicalDispatchOutcome(
            status=result.status.value,
            command_id=result.command_id,
        )
