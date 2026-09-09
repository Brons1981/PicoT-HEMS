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
from picot.domain.execution_plan import ExecutionPlanSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import (
    HomeAssistantCommandMapping,
    HomeAssistantDispatchMode,
)
from picot.v2.contracts import CanonicalPipelineRun, PlanningInputSnapshot
from picot.v2.market_execution_guard import guarded_market_primitive
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore, CommittedPlanSegment

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
    primitive: ExecutionPrimitive | None = None


DispatchCanonicalMode = Callable[
    [ExecutionPrimitiveRequest, HomeAssistantCommandMapping],
    CanonicalDispatchOutcome,
]


@dataclass(frozen=True, slots=True)
class _ChargeConfirmation:
    plan_id: str
    segment_id: str
    scope_id: str
    since: datetime
    last_seen_at: datetime
    vendor_mode: str
    source_entity_id: str


@dataclass(slots=True)
class CanonicalExecutionRuntime:
    """Consume one approved canonical dispatch intent idempotently."""

    dispatch: DispatchCanonicalMode
    commitment_store: ActivePlanCommitmentStore | None = None
    _pending_vendor_mode: str | None = None
    _confirmed_daily_segment: tuple[str, str, datetime] | None = None
    _daily_execution_suspended: bool = False
    _confirmed_daily_observation: _ChargeConfirmation | None = None
    _pending_daily_closure: _ChargeConfirmation | None = None
    completion_generation: int = 0

    def _market_primitive(
        self,
        snapshot: PlanningInputSnapshot,
        scope_id: str,
        requested: ExecutionPrimitive,
        *,
        ownership_lost: bool = False,
    ) -> ExecutionPrimitive:
        if self.commitment_store is None or snapshot.daily_charge_context is None:
            return requested
        mode = snapshot.storage_mode_capability_evidence
        mapping = (
            self._mapping(
                evidence=mode,
                primitive=ExecutionPrimitive.DISCHARGE_AT_POWER,
                capability_id=mode.capability_id,
                execution_scope_id=scope_id,
            )
            if mode
            else None
        )
        ids = tuple(
            b.assignment_id
            for b in self.commitment_store.load_market_plan_bindings()
            if b.execution_scope_id == scope_id
        )

        def phases() -> tuple[object, ...]:
            assert self.commitment_store is not None
            return tuple(
                (p.started_at, p.stop_requested_at, p.stopped_at) if p else None
                for key in ids
                for p in (self.commitment_store.load_market_progress(key),)
            )

        before = phases()
        result = guarded_market_primitive(
            snapshot=snapshot,
            store=self.commitment_store,
            scope_id=scope_id,
            requested=requested,
            ownership_lost=ownership_lost,
            export_mode_confirmed=bool(
                mode and mapping and mode.current_vendor_mode == mapping.fixed_value
            ),
        )
        if phases() != before:
            self.completion_generation += 1
        return result

    def _observe_market_interruption(self, snapshot: PlanningInputSnapshot) -> None:
        provenance = snapshot.storage_mode_control_provenance
        if provenance is not None and provenance.manual_override_active:
            for state in snapshot.current_storage_states:
                self._market_primitive(
                    snapshot,
                    state.execution_scope_id,
                    ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                    ownership_lost=True,
                )

    def reset_pending_state(self) -> None:
        """Drop only process-local dispatch state after a manual plan reset."""

        self._pending_vendor_mode = None
        self._confirmed_daily_segment = None
        self._confirmed_daily_observation = None
        self._pending_daily_closure = None

    def _observe_daily_completion(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        plan_id: str,
        segment_id: str,
        scope_id: str,
        prior: tuple[str, str, datetime] | None,
    ) -> None:
        if snapshot.daily_charge_context is None or self.commitment_store is None:
            return
        since = (
            prior[2]
            if prior is not None and prior[:2] == (plan_id, segment_id)
            else (snapshot.captured_at)
        )
        self._confirmed_daily_segment = (plan_id, segment_id, since)
        mode = snapshot.storage_mode_capability_evidence
        if mode is not None and mode.current_vendor_mode is not None:
            self._confirmed_daily_observation = _ChargeConfirmation(
                plan_id,
                segment_id,
                scope_id,
                since,
                snapshot.captured_at,
                mode.current_vendor_mode,
                mode.source_entity_id,
            )
        state = next(
            (s for s in snapshot.current_storage_states if s.execution_scope_id == scope_id), None
        )
        if state is None or not state.evidence_ids:
            return
        main = self.commitment_store.observe_daily_main_completion(
            execution_scope_id=scope_id,
            plan_id=plan_id,
            segment_id=segment_id,
            confirmed_since=since,
            observed_at=snapshot.captured_at,
            measured_at=state.measured_at,
            soc=state.current_soc,
            evidence_id="|".join(state.evidence_ids),
            state_read_at=state.state_read_at,
            state_valid_since=state.state_valid_since,
        )
        extra = self.commitment_store.observe_supplemental_completion(
            execution_scope_id=scope_id,
            plan_id=plan_id,
            segment_id=segment_id,
            confirmed_since=since,
            observed_at=snapshot.captured_at,
            measured_at=state.measured_at,
            soc=state.current_soc,
            evidence_id="|".join(state.evidence_ids),
            state_read_at=state.state_read_at,
            state_valid_since=state.state_valid_since,
        )
        self._note_completions(
            snapshot,
            tuple(
                a.assignment_id
                for a in (main, extra)
                if a is not None and a.completed_at is not None
            ),
        )

    def _note_completions(
        self, snapshot: PlanningInputSnapshot, completed_ids: tuple[str, ...]
    ) -> None:
        context = snapshot.daily_charge_context
        if context is None:
            return
        known = {a.assignment_id for a in context.assignments if a.completed_at is not None}
        known.update(
            a.assignment_id for a in context.supplemental_assignments if a.completed_at is not None
        )
        if set(completed_ids) - known:
            self.completion_generation += 1

    def _close_previous_charge(self, snapshot: PlanningInputSnapshot, *, enabled: bool) -> None:
        """Attribute a delayed measurement before processing the next execution.

        This consumes an actual prior mode confirmation. It never fabricates a
        fresh SOC timestamp or derives past execution from the next mode alone.
        """
        context = snapshot.daily_charge_context
        mode = snapshot.storage_mode_capability_evidence
        provenance = snapshot.storage_mode_control_provenance
        if (
            not enabled
            or self._daily_execution_suspended
            or self.commitment_store is None
            or context is None
            or context.status != "ready"
            or not snapshot.price_points
            or snapshot.pv_energy_timeline is None
            or snapshot.household_load_forecast is None
            or provenance is None
            or provenance.manual_override_active
            or mode is None
            or mode.status != "available"
            or mode.current_vendor_mode is None
            or (
                snapshot.bms_calibration_evidence is not None
                and snapshot.bms_calibration_evidence.active
            )
        ):
            self._pending_daily_closure = None
            return
        prior = self._confirmed_daily_observation
        if prior is not None:
            plan = self.commitment_store.load_active_daily_main_plan(prior.scope_id)
            old = (
                next((s for s in plan.segments if s.segment_id == prior.segment_id), None)
                if plan is not None and plan.plan_id == prior.plan_id
                else None
            )
            if (
                old is not None
                and old.ends_at <= snapshot.captured_at
                and (old.main_assignment_id is not None or old.purpose.startswith("supplemental:"))
            ):
                self._pending_daily_closure = prior
        proof = self._pending_daily_closure
        if proof is None:
            return
        plan = self.commitment_store.load_active_daily_main_plan(proof.scope_id)
        old = (
            next((s for s in plan.segments if s.segment_id == proof.segment_id), None)
            if plan is not None and plan.plan_id == proof.plan_id
            else None
        )
        state = next(
            (s for s in snapshot.current_storage_states if s.execution_scope_id == proof.scope_id),
            None,
        )
        if (
            old is None
            or state is None
            or mode.source_entity_id != proof.source_entity_id
            or mode.execution_scope_id != proof.scope_id
            or mode.capability_id != old.capability_id
        ):
            self._pending_daily_closure = None
            return
        if state.measured_at > old.ends_at:
            self._pending_daily_closure = None
            return
        if (
            self._daily_execution_blocker(
                snapshot,
                scope_id=proof.scope_id,
                capability_id=old.capability_id,
                primitive=old.primitive,
                requested_power_w=old.requested_power_w,
            )
            is not None
        ):
            self._pending_daily_closure = None
            return
        if not proof.since <= state.measured_at <= snapshot.captured_at or not state.evidence_ids:
            return
        changed = mode.state_changed_at
        if mode.current_vendor_mode == proof.vendor_mode:
            if changed is None or changed > proof.last_seen_at:
                return  # A changed-away-and-back mode is not uninterrupted evidence.
            until = snapshot.captured_at
        else:
            if (
                changed is None
                or changed.utcoffset() is None
                or not max(proof.last_seen_at, state.measured_at) <= changed <= snapshot.captured_at
                or provenance.status != "planner_owned"
                or provenance.last_planner_vendor_mode != mode.current_vendor_mode
                or provenance.last_planner_applied_at is None
                or not state.measured_at
                <= provenance.last_planner_applied_at
                <= snapshot.captured_at
            ):
                return
            until = changed
        evidence_id = (
            "segment-closure:"
            + "|".join(state.evidence_ids)
            + f":previous_mode={proof.vendor_mode}:mode_changed_at={changed}"
            + f":last_confirmed_at={proof.last_seen_at.isoformat()}"
        )
        arguments: dict[str, Any] = dict(
            execution_scope_id=proof.scope_id,
            plan_id=proof.plan_id,
            segment_id=proof.segment_id,
            confirmed_since=proof.since,
            observed_at=snapshot.captured_at,
            measured_at=state.measured_at,
            soc=state.current_soc,
            evidence_id=evidence_id,
            confirmed_until=until,
        )
        main = self.commitment_store.observe_daily_main_completion(**arguments)
        extra = self.commitment_store.observe_supplemental_completion(**arguments)
        self._note_completions(
            snapshot,
            tuple(
                a.assignment_id
                for a in (main, extra)
                if a is not None and a.completed_at is not None
            ),
        )
        if (main is not None and main.completed_at is not None) or (
            extra is not None and extra.completed_at is not None
        ):
            self._pending_daily_closure = None

    @staticmethod
    def _daily_execution_blocker(
        snapshot: PlanningInputSnapshot,
        *,
        scope_id: str,
        capability_id: str,
        primitive: ExecutionPrimitive,
        requested_power_w: float | None,
    ) -> str | None:
        capabilities = snapshot.capability_snapshot_set
        capability = next(
            (
                c
                for c in (capabilities.capabilities if capabilities else ())
                if c.capability_id == capability_id and c.execution_scope_id == scope_id
            ),
            None,
        )
        if (
            capability is None
            or capability.availability != "available"
            or (capability.health != "healthy" or primitive not in capability.supported_primitives)
        ):
            return "daily_main_capability_unavailable"
        if primitive in {ExecutionPrimitive.CHARGE_AT_POWER, ExecutionPrimitive.DISCHARGE_AT_POWER}:
            limits = next(
                (
                    limit
                    for limit in snapshot.storage_physical_limits
                    if limit.execution_scope_id == scope_id and limit.capability_id == capability_id
                ),
                None,
            )
            if limits is None:
                return "storage_physical_limits_unavailable"
            configured = (
                limits.maximum_charge_input_power_w
                if primitive is ExecutionPrimitive.CHARGE_AT_POWER
                else limits.maximum_discharge_output_power_w
            )
            if requested_power_w != configured:
                return "daily_main_configured_power_changed"
        return None

    @staticmethod
    def _mapping(
        *,
        evidence: Any,
        primitive: ExecutionPrimitive,
        capability_id: str,
        execution_scope_id: str,
    ) -> HomeAssistantCommandMapping | None:
        if (
            getattr(evidence, "capability_id", None) != capability_id
            or getattr(evidence, "execution_scope_id", None) != execution_scope_id
            or getattr(evidence, "status", None) != "available"
        ):
            return None
        mappings = getattr(evidence, "mappings", ())
        matches = tuple(item for item in mappings if primitive in item.primitives)
        if primitive in {
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.DISCHARGE_AT_POWER,
        }:
            matches = tuple(
                item for item in matches if item.power_semantics == "integration_configured_maximum"
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

        try:
            self._observe_market_interruption(snapshot)
            self._close_previous_charge(snapshot, enabled=execution_enabled)
        except (OSError, ValueError) as exc:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                failure_reason=f"charge_completion_evidence_failed:{exc}",
            )
        self._confirmed_daily_observation = None
        prior_confirmation = self._confirmed_daily_segment
        self._confirmed_daily_segment = None
        context = snapshot.daily_charge_context
        if context is not None and (
            self._daily_execution_suspended
            or not snapshot.price_points
            or snapshot.pv_energy_timeline is None
            or snapshot.household_load_forecast is None
            or not snapshot.current_storage_states
        ):
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                failure_reason="daily_main_execution_awaits_valid_planning",
            )
        daily_plan = next(
            (
                p
                for p in (context.main_plans if context is not None else ())
                if context is not None
                and p.plan_id in context.active_main_plan_ids
                and p.valid_from <= snapshot.captured_at < p.valid_until
            ),
            None,
        )
        commitment = next(
            (
                item
                for item in snapshot.active_plan_commitments
                if item.starts_at <= snapshot.captured_at < item.ends_at
            ),
            None,
        )
        if context is not None:
            commitment = None  # Daily input never executes an old implicit route.
            if context.status != "ready":
                return CommittedBoundaryDispatchOutcome(
                    status="blocked",
                    failure_reason=context.reason,
                )
        segments: tuple[ExecutionPlanSegment, ...] | tuple[CommittedPlanSegment, ...]
        if daily_plan is not None:
            plan_id = daily_plan.plan_id
            plan_revision = daily_plan.revision
            scope_id = daily_plan.execution_scope_id
            segments = daily_plan.segments
        else:
            if commitment is None:
                return CommittedBoundaryDispatchOutcome(status="not_due")
            plan_id = commitment.plan_id
            plan_revision = commitment.plan_revision
            scope_id = commitment.execution_scope_id
            segments = commitment.segments
        segment = next(
            (item for item in segments if item.starts_at <= snapshot.captured_at < item.ends_at),
            None,
        )
        if segment is None:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=plan_id,
                failure_reason="committed_segment_not_due",
            )
        try:
            primitive = ExecutionPrimitive(segment.primitive)
        except ValueError:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=plan_id,
                failure_reason="committed_primitive_unsupported",
            )
        evidence = snapshot.storage_mode_capability_evidence
        provenance = snapshot.storage_mode_control_provenance
        if not execution_enabled:
            return CommittedBoundaryDispatchOutcome(
                status="observer_only",
                plan_id=plan_id,
            )
        if snapshot.bms_calibration_evidence is not None and (
            snapshot.bms_calibration_evidence.active
        ):
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=plan_id,
                failure_reason="bms_soc_calibration_active",
            )
        if provenance is None or provenance.manual_override_active:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=plan_id,
                failure_reason=(
                    "manual_override_provenance_unverified"
                    if provenance is None
                    else "manual_override_active"
                ),
            )
        if evidence is None or evidence.current_vendor_mode is None:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=plan_id,
                failure_reason="storage_mode_capability_evidence_unavailable",
            )
        market_override = False
        if daily_plan is not None:
            try:
                guarded = self._market_primitive(snapshot, scope_id, primitive)
            except (ValueError, OSError):
                guarded = ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            market_override = guarded is not primitive
            primitive = guarded
        mapping = self._mapping(
            evidence=evidence,
            primitive=primitive,
            capability_id=evidence.capability_id,
            execution_scope_id=scope_id,
        )
        if mapping is None or mapping.fixed_value is None:
            return CommittedBoundaryDispatchOutcome(
                status="blocked",
                plan_id=plan_id,
                failure_reason="primitive_vendor_mapping_unavailable",
            )
        planned_vendor_mode = mapping.fixed_value
        application_id = (
            "canonical-commitment-boundary:"
            f"{plan_id}:{plan_revision}:"
            f"{segment.starts_at.isoformat()}:{primitive.value}"
        )
        common: dict[str, Any] = {
            "application_id": application_id,
            "plan_id": plan_id,
            "previous_vendor_mode": evidence.current_vendor_mode,
            "planned_vendor_mode": planned_vendor_mode,
            "primitive": primitive,
        }
        requested_power_w = None
        if primitive in {
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.DISCHARGE_AT_POWER,
        }:
            limits = next(
                (
                    item
                    for item in snapshot.storage_physical_limits
                    if item.execution_scope_id == scope_id
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
        if daily_plan is not None:
            original = next(s for s in daily_plan.segments if s.starts_at == segment.starts_at)
            assert self.commitment_store is not None
            completed_owner = next((a for a in self.commitment_store.load_daily_assignments()
                                    if a.assignment_id == original.main_assignment_id
                                    and a.historical_completion_segment is not None), None)
            if completed_owner is not None:
                return CommittedBoundaryDispatchOutcome(
                    status="blocked",
                    failure_reason="historical_main_completed_waiting_for_reconciliation",
                    **common,
                )
            if original.capability_id != evidence.capability_id:
                return CommittedBoundaryDispatchOutcome(
                    status="blocked",
                    failure_reason="daily_main_capability_changed",
                    **common,
                )
            if not market_override and original.requested_power_w != requested_power_w:
                return CommittedBoundaryDispatchOutcome(
                    status="blocked",
                    failure_reason="daily_main_configured_power_changed",
                    **common,
                )
        if daily_plan is not None:
            blocker = self._daily_execution_blocker(
                snapshot,
                scope_id=scope_id,
                capability_id=original.capability_id,
                primitive=primitive,
                requested_power_w=requested_power_w,
            )
            if blocker is not None:
                return CommittedBoundaryDispatchOutcome(
                    status="blocked",
                    failure_reason=blocker,
                    **common,
                )
        if evidence.current_vendor_mode == planned_vendor_mode:
            self._pending_vendor_mode = None
            if daily_plan is not None:
                self._observe_daily_completion(
                    snapshot,
                    plan_id=plan_id,
                    segment_id=original.segment_id,
                    scope_id=scope_id,
                    prior=prior_confirmation,
                )
            return CommittedBoundaryDispatchOutcome(
                status="already_active",
                **common,
            )
        if self._pending_vendor_mode == planned_vendor_mode:
            return CommittedBoundaryDispatchOutcome(
                status="awaiting_mode_feedback",
                **common,
            )
        request = ExecutionPrimitiveRequest(
            request_id=f"commitment-boundary-request:{application_id}",
            plan_set_id=f"committed-plan-set:{plan_id}",
            plan_id=plan_id,
            plan_revision=plan_revision,
            segment_id=(
                original.segment_id
                if daily_plan is not None
                else (
                    f"committed-segment:{segment.starts_at.isoformat()}:"
                    f"{segment.ends_at.isoformat()}"
                )
            ),
            execution_scope_id=scope_id,
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

    def apply_committed(
        self, run: CanonicalPipelineRun, observed: PlanningInputSnapshot
    ) -> CanonicalPipelineRun:
        """Execute the saved daily plan against a separate, fresh observation.

        The planning snapshot and plan lineage remain immutable. The existing
        committed boundary owns current-time selection, SOC guards and mapping.
        """
        if run.execution_record.status != "live_plan_ready":
            raise ValueError("fresh committed execution requires live plan authority")
        self._daily_execution_suspended = False
        outcome = self.advance_committed_boundary(observed, execution_enabled=True)
        request_id = (
            f"commitment-boundary-request:{outcome.application_id}"
            if outcome.application_id is not None
            else None
        )
        return replace(
            run,
            primitive_boundary=replace(
                run.primitive_boundary,
                request_id=request_id,
                planned_primitive=outcome.primitive,
                mapping_status="validated" if outcome.planned_vendor_mode else "unavailable",
                source_entity_id=(
                    observed.storage_mode_capability_evidence.source_entity_id
                    if observed.storage_mode_capability_evidence
                    else None
                ),
                mapping_method_version=(
                    observed.storage_mode_capability_evidence.method_version
                    if observed.storage_mode_capability_evidence
                    else None
                ),
                current_vendor_mode=outcome.previous_vendor_mode,
                planned_vendor_mode=outcome.planned_vendor_mode,
                status=outcome.status,
                blockers=(outcome.failure_reason,) if outcome.failure_reason else (),
            ),
            adapter_boundary=replace(
                run.adapter_boundary,
                primitive_request_id=request_id,
                translation_id=None,
                status=outcome.status,
            ),
            vendor_result=replace(
                run.vendor_result,
                command_id=outcome.command_id,
                adapter_translation_id=None,
                dispatch_intent_id=outcome.application_id,
                planned_vendor_mode=outcome.planned_vendor_mode,
                status=outcome.status,
                failure_reason=outcome.failure_reason,
                observed_result_id=f"execution-observation:{observed.snapshot_id}",
                target_entity_id=(
                    observed.storage_mode_capability_evidence.source_entity_id
                    if observed.storage_mode_capability_evidence
                    else None
                ),
            ),
        )

    def apply(self, run: CanonicalPipelineRun) -> CanonicalPipelineRun:
        """Translate at the adapter boundary and dispatch only with live authority."""
        try:
            self._observe_market_interruption(run.planning_input)
            self._close_previous_charge(
                run.planning_input,
                enabled=run.execution_record.status == "live_plan_ready",
            )
        except (OSError, ValueError) as exc:
            return replace(
                run,
                primitive_boundary=replace(
                    run.primitive_boundary,
                    request_id=None,
                    status="dry_run_blocked",
                    blockers=(
                        *run.primitive_boundary.blockers,
                        f"charge_completion_evidence_failed:{exc}",
                    ),
                ),
            )
        self._confirmed_daily_observation = None
        prior_confirmation = self._confirmed_daily_segment
        self._confirmed_daily_segment = None
        boundary = run.primitive_boundary
        if run.planning_input.daily_charge_context is not None:
            self._daily_execution_suspended = run.execution_record.status in {
                "live_fallback_ready",
                "observer_fallback_ready",
            }
        due = next(
            (
                (plan, segment)
                for plan in run.execution_plan_set.plans
                for segment in plan.segments
                if segment.starts_at <= run.planning_input.captured_at < segment.ends_at
            ),
            None,
        )
        fallback = run.execution_record.status in {"live_fallback_ready", "observer_fallback_ready"}
        if boundary.request_id is None or boundary.planned_primitive is None:
            return run
        evidence = run.planning_input.storage_mode_capability_evidence
        if fallback:
            scopes = {s.execution_scope_id for s in run.planning_input.current_storage_states}
            scopes.update(s.execution_scope_id for s in run.planning_input.storage_physical_limits)
            if evidence is None or len(scopes) != 1:
                return replace(
                    run,
                    primitive_boundary=replace(
                        boundary,
                        blockers=(*boundary.blockers, "fallback_scope_unavailable"),
                        mapping_status="unavailable",
                    ),
                )
            scope_id = next(iter(scopes))
            capability_id = evidence.capability_id
            plan_id = f"guarded-nom:{scope_id}"
            segment_id = boundary.request_id
            requested_power_w = None
        else:
            if due is None:
                return run
            plan, segment = due
            scope_id, capability_id = plan.execution_scope_id, segment.capability_id
            plan_id, segment_id = plan.plan_id, segment.segment_id
            requested_power_w = segment.requested_power_w
        if not fallback and run.execution_record.status == "live_plan_ready":
            try:
                guarded = self._market_primitive(
                    run.planning_input, scope_id, boundary.planned_primitive
                )
            except (ValueError, OSError):
                guarded = ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            if guarded is not boundary.planned_primitive:
                boundary = replace(
                    boundary,
                    planned_primitive=guarded,
                    request_id=f"{boundary.request_id}:market-stop",
                )
                requested_power_w = None
        if not fallback and run.planning_input.daily_charge_context is not None:
            assert boundary.planned_primitive is not None
            assert boundary.request_id is not None
            blocker = self._daily_execution_blocker(
                run.planning_input,
                scope_id=scope_id,
                capability_id=capability_id,
                primitive=boundary.planned_primitive,
                requested_power_w=requested_power_w,
            )
            if blocker is not None:
                return replace(
                    run,
                    primitive_boundary=replace(
                        boundary,
                        request_id=None,
                        status="dry_run_blocked",
                        blockers=(*boundary.blockers, blocker),
                    ),
                )
        assert boundary.planned_primitive is not None
        assert boundary.request_id is not None
        mapping = (
            self._mapping(
                evidence=evidence,
                primitive=boundary.planned_primitive,
                capability_id=capability_id,
                execution_scope_id=scope_id,
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
                        dict.fromkeys((*boundary.blockers, "primitive_vendor_mapping_unavailable"))
                    ),
                ),
                adapter_boundary=replace(
                    run.adapter_boundary,
                    status="translation_blocked",
                ),
            )
        assert mapping.fixed_value is not None
        planned_vendor_mode = mapping.fixed_value
        live_authority = run.execution_record.status in {"live_plan_ready", "live_fallback_ready"}
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
            if not fallback:
                self._observe_daily_completion(
                    run.planning_input,
                    plan_id=plan_id,
                    segment_id=segment_id,
                    scope_id=scope_id,
                    prior=prior_confirmation,
                )
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
            plan_id=plan_id,
            plan_revision=1,
            segment_id=segment_id,
            execution_scope_id=scope_id,
            capability_id=capability_id,
            primitive=boundary.planned_primitive,
            requested_at=run.planning_input.captured_at,
            requested_power_w=requested_power_w,
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
