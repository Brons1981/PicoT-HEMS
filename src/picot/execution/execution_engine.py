"""Deterministic Execution Engine defined by ADR-015, ADR-016 and ADR-027."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilitySnapshotSet,
    LogicalCapabilitySnapshot,
)
from picot.domain.execution import (
    CommandValidationOutcome,
    ExecutionPrimitiveRequest,
    ExecutionRecord,
    ExecutionResult,
)
from picot.domain.execution_plan import (
    ExecutionPlan,
    ExecutionPlanLifecycle,
    ExecutionPlanSegment,
    ExecutionPlanSet,
)

IMPLEMENTATION_VERSION = "execution-v1"


class ExecutionEngine:
    """Validate due plan segments and emit vendor-independent requests."""

    def execute_due(
        self,
        plan_set: ExecutionPlanSet,
        capabilities: CapabilitySnapshotSet,
        *,
        now: datetime,
    ) -> ExecutionResult:
        self._validate_atomic_inputs(plan_set, capabilities, now)
        capabilities_by_id = {
            capability.capability_id: capability
            for capability in capabilities.capabilities
        }
        requests: list[ExecutionPrimitiveRequest] = []
        records: list[ExecutionRecord] = []

        for plan in plan_set.plans:
            for segment in plan.segments:
                if not segment.starts_at <= now < segment.ends_at:
                    continue
                outcome, reason = self._validate_segment(
                    plan,
                    segment,
                    capabilities_by_id.get(segment.capability_id),
                    now,
                )
                request_id: str | None = None
                if outcome is CommandValidationOutcome.APPROVED:
                    request_id = self._request_id(plan_set, plan, segment, now)
                    requests.append(
                        ExecutionPrimitiveRequest(
                            request_id=request_id,
                            plan_set_id=plan_set.plan_set_id,
                            plan_id=plan.plan_id,
                            plan_revision=plan.revision,
                            segment_id=segment.segment_id,
                            execution_scope_id=plan.execution_scope_id,
                            capability_id=segment.capability_id,
                            primitive=segment.primitive,
                            requested_at=now,
                            requested_power_w=segment.requested_power_w,
                            soc_constraint=segment.soc_constraint,
                            energy_profile_id=segment.energy_profile_id,
                        )
                    )
                records.append(
                    ExecutionRecord(
                        record_id=self._record_id(plan_set, plan, segment, now),
                        plan_set_id=plan_set.plan_set_id,
                        plan_id=plan.plan_id,
                        segment_id=segment.segment_id,
                        execution_scope_id=plan.execution_scope_id,
                        capability_id=segment.capability_id,
                        evaluated_at=now,
                        outcome=outcome,
                        reason=reason,
                        request_id=request_id,
                    )
                )

        return ExecutionResult(
            plan_set_id=plan_set.plan_set_id,
            evaluated_at=now,
            requests=tuple(requests),
            records=tuple(records),
            implementation_version=IMPLEMENTATION_VERSION,
        )

    @staticmethod
    def _validate_atomic_inputs(
        plan_set: ExecutionPlanSet,
        capabilities: CapabilitySnapshotSet,
        now: datetime,
    ) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Execution time must be timezone-aware.")
        if capabilities.snapshot_id != plan_set.snapshot_id:
            raise ValueError("Capability Snapshot Set must match Execution Plan Set snapshot.")
        if capabilities.captured_at > now:
            raise ValueError("Capability Snapshot Set may not be captured in the future.")
        mapping_versions = {plan.mapping_version for plan in plan_set.plans}
        if mapping_versions and mapping_versions != {capabilities.mapping_version}:
            raise ValueError("Capability mapping version must match every Execution Plan.")

    @staticmethod
    def _validate_segment(
        plan: ExecutionPlan,
        segment: ExecutionPlanSegment,
        capability: LogicalCapabilitySnapshot | None,
        now: datetime,
    ) -> tuple[CommandValidationOutcome, str]:
        if plan.lifecycle is not ExecutionPlanLifecycle.PROPOSED:
            return (
                CommandValidationOutcome.CANCELLED,
                "Execution Plan is not in the initial PROPOSED lifecycle state.",
            )
        if not plan.valid_from <= now < plan.valid_until:
            return (
                CommandValidationOutcome.CANCELLED,
                "Execution Plan is outside its validity interval.",
            )
        if capability is None:
            return (
                CommandValidationOutcome.REPLAN_REQUIRED,
                "Required logical capability is missing from the current snapshot.",
            )
        if capability.execution_scope_id != plan.execution_scope_id:
            return (
                CommandValidationOutcome.REJECTED,
                "Capability execution scope does not match the Execution Plan.",
            )
        if capability.availability is not CapabilityAvailability.AVAILABLE:
            return (
                CommandValidationOutcome.REPLAN_REQUIRED,
                "Required logical capability is not currently available.",
            )
        if capability.health is not CapabilityHealth.HEALTHY:
            return (
                CommandValidationOutcome.REPLAN_REQUIRED,
                "Required logical capability is not currently healthy.",
            )
        if segment.primitive not in capability.supported_primitives:
            return (
                CommandValidationOutcome.REJECTED,
                "Execution Primitive is not supported by the current capability.",
            )
        if capability.fresh_at > now:
            return (
                CommandValidationOutcome.REJECTED,
                "Capability freshness timestamp is later than execution time.",
            )
        return (
            CommandValidationOutcome.APPROVED,
            "Due segment passed deterministic command validation.",
        )

    @staticmethod
    def _request_id(
        plan_set: ExecutionPlanSet,
        plan: ExecutionPlan,
        segment: ExecutionPlanSegment,
        now: datetime,
    ) -> str:
        source = (
            f"{plan_set.plan_set_id}|{plan.plan_id}|{plan.revision}|"
            f"{segment.segment_id}|{now.isoformat()}|{IMPLEMENTATION_VERSION}"
        )
        return f"execution-request-{sha256(source.encode()).hexdigest()[:16]}"

    @staticmethod
    def _record_id(
        plan_set: ExecutionPlanSet,
        plan: ExecutionPlan,
        segment: ExecutionPlanSegment,
        now: datetime,
    ) -> str:
        source = (
            f"{plan_set.plan_set_id}|{plan.plan_id}|{segment.segment_id}|"
            f"{now.isoformat()}|record|{IMPLEMENTATION_VERSION}"
        )
        return f"execution-record-{sha256(source.encode()).hexdigest()[:16]}"
