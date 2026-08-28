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
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

SUPERVISOR_BASE_URL = "http://supervisor/core"


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
        """Translate at the adapter boundary and dispatch only with live authority."""
        boundary = run.primitive_boundary
        due = next(
            (
                (plan, segment)
                for plan in run.execution_plan_set.plans
                for segment in plan.segments
                if segment.starts_at <= run.planning_input.captured_at < segment.ends_at
            ),
            None,
        )
        if due is None or boundary.request_id is None or boundary.planned_primitive is None:
            return run
        plan, segment = due
        evidence = run.planning_input.storage_mode_capability_evidence
        matches = (
            tuple(
                item.vendor_mode
                for item in evidence.mappings
                if boundary.planned_primitive in item.primitives
            )
            if evidence is not None
            else ()
        )
        if len(matches) != 1 or evidence is None:
            return replace(
                run,
                primitive_boundary=replace(
                    boundary,
                    mapping_status="unavailable",
                    blockers=tuple(
                        dict.fromkeys(
                            (*boundary.blockers, "primitive_vendor_mapping_unavailable")
                        )
                    ),
                ),
                adapter_boundary=replace(
                    run.adapter_boundary,
                    status="translation_blocked",
                ),
            )
        planned_vendor_mode = matches[0]
        mapping = HomeAssistantCommandMapping(
            mapping_id=(f"canonical-zendure-mode-{boundary.planned_primitive.value}-v1"),
            mapping_version=1,
            capability_id=segment.capability_id,
            execution_scope_id=plan.execution_scope_id,
            primitive=boundary.planned_primitive,
            domain="input_select",
            service="select_option",
            entity_id=evidence.source_entity_id,
            value_key="option",
            fixed_value=planned_vendor_mode,
        )
        live_authority = run.execution_record.status == "live_plan_ready"
        translated = replace(
            run,
            primitive_boundary=replace(
                boundary,
                mapping_status="validated",
                source_entity_id=evidence.source_entity_id,
                planned_vendor_mode=planned_vendor_mode,
            ),
            adapter_boundary=replace(
                run.adapter_boundary,
                translation_id=mapping.mapping_id,
                primitive_request_id=boundary.request_id,
                status=("translation_ready" if live_authority else "observer_translation_ready"),
            ),
            vendor_result=replace(
                run.vendor_result,
                adapter_translation_id=mapping.mapping_id,
                status=("dispatch_ready" if live_authority else "observer_dispatch_ready"),
                dispatch_intent_id=f"dispatch:{boundary.request_id}",
                target_entity_id=evidence.source_entity_id,
                planned_vendor_mode=planned_vendor_mode,
            ),
        )
        if not live_authority:
            return translated
        if boundary.current_vendor_mode == planned_vendor_mode:
            self._pending_vendor_mode = None
            return replace(
                translated,
                vendor_result=replace(
                    translated.vendor_result,
                    status="already_active",
                ),
            )
        if self._pending_vendor_mode == planned_vendor_mode:
            return replace(
                translated,
                vendor_result=replace(
                    translated.vendor_result,
                    status="awaiting_mode_feedback",
                ),
            )
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
        outcome = self.dispatch(request, mapping)
        if outcome.status == "dispatched":
            self._pending_vendor_mode = planned_vendor_mode
        return replace(
            translated,
            adapter_boundary=replace(
                translated.adapter_boundary,
                status="translated",
            ),
            vendor_result=replace(
                translated.vendor_result,
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
