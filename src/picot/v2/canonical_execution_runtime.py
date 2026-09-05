"""Controlled Home Assistant boundary for canonical live execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from picot.adapters.home_assistant import (
    HomeAssistantAdapter,
    HomeAssistantDispatcher,
)
from picot.adapters.home_assistant_http import HomeAssistantHttpTransport
from picot.architecture_ownership import architecture_ownership
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import (
    HomeAssistantCommandMapping,
    HomeAssistantDispatchMode,
)
from picot.v2.contracts import CanonicalPipelineRun, PlanningInputSnapshot
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

ARCHITECTURE_OWNERSHIP = architecture_ownership("execution_engine", __name__)
SUPERVISOR_BASE_URL = "http://supervisor/core"


@dataclass(frozen=True, slots=True)
class CanonicalDispatchOutcome:
    """Exact result returned by the external dispatch boundary."""

    status: str
    command_id: str


@dataclass(frozen=True, slots=True)
class CommittedBoundaryDispatchOutcome:
    """Result of executing one already-approved commitment segment."""

    status: str
    application_id: str | None = None
    command_id: str | None = None
    plan_id: str | None = None
    previous_vendor_mode: str | None = None
    planned_vendor_mode: str | None = None
    failure_reason: str | None = None


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

    @staticmethod
    def _mapping(
        *,
        evidence: Any,
        primitive: ExecutionPrimitive,
        capability_id: str,
        execution_scope_id: str,
    ) -> HomeAssistantCommandMapping | None:
        mappings = getattr(evidence, "mappings", ())
        matches = tuple(
            item
            for item in mappings
            if primitive in item.primitives
        )
        if primitive in {
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.DISCHARGE_AT_POWER,
        }:
            matches = tuple(
                item
                for item in matches
                if item.power_semantics == "integration_configured_maximum"
            )
        if len(matches) != 1:
            return None
        return HomeAssistantCommandMapping(
            mapping_id=f"canonical-zendure-mode-{primitive.value}-v1",
            mapping_version=1,
            capability_id=capability_id,
            execution_scope_id=execution_scope_id,
            primitive=primitive,
            domain="input_select",
            service="select_option",
            entity_id=evidence.source_entity_id,
            value_key="option",
            fixed_value=matches[0].vendor_mode,
        )

    def advance_committed_boundary(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        execution_enabled: bool,
    ) -> CommittedBoundaryDispatchOutcome:
        """Execute the due stored segment without invoking Candidate planning."""

        commitment = next(
            (
                item
                for item in snapshot.active_plan_commitments
                if item.starts_at <= snapshot.captured_at < item.ends_at
            ),
            None,
        )
        if commitment is None:
            return CommittedBoundaryDispatchOutcome(status="not_due")
        segment = next(
            (
                item
                for item in commitment.segments
                if item.starts_at <= snapshot.captured_at < item.ends_at
            ),
            None,
        )
        if segment is None:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=commitment.plan_id,
                failure_reason="committed_segment_not_due",
            )
        try:
            primitive = ExecutionPrimitive(segment.primitive)
        except ValueError:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=commitment.plan_id,
                failure_reason="committed_primitive_unsupported",
            )
        evidence = snapshot.storage_mode_capability_evidence
        provenance = snapshot.storage_mode_control_provenance
        if not execution_enabled:
            return CommittedBoundaryDispatchOutcome(
                status="observer_only",
                plan_id=commitment.plan_id,
            )
        if snapshot.bms_calibration_evidence is not None and (
            snapshot.bms_calibration_evidence.active
        ):
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=commitment.plan_id,
                failure_reason="bms_soc_calibration_active",
            )
        if provenance is None or provenance.manual_override_active:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=commitment.plan_id,
                failure_reason=(
                    "manual_override_provenance_unverified"
                    if provenance is None
                    else "manual_override_active"
                ),
            )
        if evidence is None or evidence.current_vendor_mode is None:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=commitment.plan_id,
                failure_reason="storage_mode_capability_evidence_unavailable",
            )
        mapping = self._mapping(
            evidence=evidence,
            primitive=primitive,
            capability_id=evidence.capability_id,
            execution_scope_id=commitment.execution_scope_id,
        )
        if mapping is None or mapping.fixed_value is None:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=commitment.plan_id,
                failure_reason="primitive_vendor_mapping_unavailable",
            )
        planned_vendor_mode = mapping.fixed_value
        application_id = (
            "canonical-commitment-boundary:"
            f"{commitment.plan_id}:{commitment.plan_revision}:"
            f"{segment.starts_at.isoformat()}:{primitive.value}"
        )
        common = {
            "application_id": application_id,
            "plan_id": commitment.plan_id,
            "previous_vendor_mode": evidence.current_vendor_mode,
            "planned_vendor_mode": planned_vendor_mode,
        }
        if evidence.current_vendor_mode == planned_vendor_mode:
            self._pending_vendor_mode = None
            return CommittedBoundaryDispatchOutcome(
                status="already_active",
                **common,
            )
        if self._pending_vendor_mode == planned_vendor_mode:
            return CommittedBoundaryDispatchOutcome(
                status="awaiting_mode_feedback",
                **common,
            )
        requested_power_w = None
        if primitive in {
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.DISCHARGE_AT_POWER,
        }:
            limits = next(
                (
                    item
                    for item in snapshot.storage_physical_limits
                    if item.execution_scope_id == commitment.execution_scope_id
                    and item.capability_id == evidence.capability_id
                ),
                None,
            )
            if limits is None:
                return CommittedBoundaryDispatchOutcome(
                    status="blocked",
                    failure_reason="storage_physical_limits_unavailable",
                    **common,
                )
            requested_power_w = (
                limits.maximum_charge_input_power_w
                if primitive is ExecutionPrimitive.CHARGE_AT_POWER
                else limits.maximum_discharge_output_power_w
            )
        request = ExecutionPrimitiveRequest(
            request_id=f"commitment-boundary-request:{application_id}",
            plan_set_id=f"committed-plan-set:{commitment.plan_id}",
            plan_id=commitment.plan_id,
            plan_revision=commitment.plan_revision,
            segment_id=(
                f"committed-segment:{segment.starts_at.isoformat()}:"
                f"{segment.ends_at.isoformat()}"
            ),
            execution_scope_id=commitment.execution_scope_id,
            capability_id=evidence.capability_id,
            primitive=primitive,
            requested_at=snapshot.captured_at,
            requested_power_w=requested_power_w,
        )
        try:
            outcome = self.dispatch(request, mapping)
        except Exception as error:  # noqa: BLE001 - fail closed at external boundary
            self._pending_vendor_mode = None
            return CommittedBoundaryDispatchOutcome(
                status="dispatch_failed",
                failure_reason=f"{type(error).__name__}: {error}",
                **common,
            )
        if outcome.status == "dispatched":
            self._pending_vendor_mode = planned_vendor_mode
        return CommittedBoundaryDispatchOutcome(
            status=outcome.status,
            command_id=outcome.command_id,
            **common,
        )

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
        mapping = (
            self._mapping(
                evidence=evidence,
                primitive=boundary.planned_primitive,
                capability_id=segment.capability_id,
                execution_scope_id=plan.execution_scope_id,
            )
            if evidence is not None
            else None
        )
        if mapping is None or evidence is None:
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
        assert mapping.fixed_value is not None
        planned_vendor_mode = mapping.fixed_value
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
        try:
            outcome = self.dispatch(request, mapping)
        except Exception as error:  # noqa: BLE001 - fail closed at external boundary
            self._pending_vendor_mode = None
            return replace(
                translated,
                primitive_boundary=replace(
                    translated.primitive_boundary,
                    blockers=tuple(
                        dict.fromkeys(
                            (
                                *translated.primitive_boundary.blockers,
                                "canonical_dispatch_failed",
                            )
                        )
                    ),
                ),
                adapter_boundary=replace(
                    translated.adapter_boundary,
                    status="translation_failed",
                ),
                vendor_result=replace(
                    translated.vendor_result,
                    command_id=None,
                    status="dispatch_failed",
                    failure_reason=f"{type(error).__name__}: {error}",
                ),
            )
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
