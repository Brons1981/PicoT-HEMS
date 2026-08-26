"""Coalescing runtime boundary for the temporary third MEP planner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock, Thread
from time import perf_counter

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import HomeAssistantCommandMapping
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.market_daily_planner import MarketDailyPlan, MarketDailyPlanner
from picot.v2.canonical_execution_runtime import (
    CanonicalDispatchOutcome,
    DispatchCanonicalMode,
)
from picot.v2.contracts import PlanningInputSnapshot

METHOD_VERSION = "v2-market-daily-runtime:v1"
MAXIMUM_MODE_EVIDENCE_AGE = timedelta(minutes=2)
INTENT_MODE_MAPPING = {
    DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY: (
        "Alleen slim ontladen",
        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
    ),
    DailyStorageIntent.NOM: (
        "Nul op de meter",
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
    ),
    DailyStorageIntent.GRID_REQUIREMENT: (
        "Snel opladen",
        ExecutionPrimitive.CHARGE_AT_POWER,
    ),
    DailyStorageIntent.STORAGE_EXPORT: (
        "Snel ontladen",
        ExecutionPrimitive.DISCHARGE_AT_POWER,
    ),
    DailyStorageIntent.STANDBY: (
        "Standby",
        ExecutionPrimitive.STANDBY,
    ),
}


@dataclass(frozen=True, slots=True)
class MarketDailyExecutionOutcome:
    status: str
    requested_vendor_mode: str | None
    reason: str
    command_id: str | None = None


@dataclass(slots=True)
class MarketDailyExecutionRuntime:
    """Execute only an unambiguous current MEP intent, fail closed."""

    dispatch: DispatchCanonicalMode
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    _pending_vendor_mode: str | None = None

    def apply(
        self,
        *,
        plan: MarketDailyPlan,
        snapshot: PlanningInputSnapshot,
    ) -> MarketDailyExecutionOutcome:
        selected = (
            INTENT_MODE_MAPPING.get(plan.current_intent)
            if plan.current_intent is not None
            else None
        )
        requested_mode = selected[0] if selected is not None else None
        if not plan.dispatch_authority:
            return MarketDailyExecutionOutcome(
                status="observer_only",
                requested_vendor_mode=requested_mode,
                reason="mep_live_authority_disabled",
            )
        if selected is None or plan.current_interval_ends_at is None:
            return self._blocked("mep_current_intent_ambiguous")
        executed_at = self.now()
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:
            raise ValueError("MEP execution clock must be timezone-aware")
        if executed_at >= plan.current_interval_ends_at:
            return self._blocked("mep_current_interval_expired")
        evidence = snapshot.storage_mode_capability_evidence
        provenance = snapshot.storage_mode_control_provenance
        if evidence is None or evidence.status != "available":
            return self._blocked("storage_mode_capability_unavailable")
        if (
            evidence.captured_at != snapshot.captured_at
            or executed_at - evidence.captured_at > MAXIMUM_MODE_EVIDENCE_AGE
        ):
            return self._blocked("storage_mode_capability_stale")
        if provenance is None:
            return self._blocked("storage_mode_provenance_unavailable")
        if provenance.manual_override_active:
            return self._blocked("manual_override_active")
        if executed_at - provenance.observed_at > MAXIMUM_MODE_EVIDENCE_AGE:
            return self._blocked("storage_mode_provenance_stale")
        calibration = snapshot.bms_calibration_evidence
        if calibration is not None and calibration.active:
            return self._blocked("bms_soc_calibration_active")
        if requested_mode not in evidence.usable_vendor_modes:
            return self._blocked("requested_vendor_mode_unavailable")
        if evidence.current_vendor_mode != provenance.observed_vendor_mode:
            return self._blocked("storage_mode_evidence_conflict")
        if evidence.current_vendor_mode == requested_mode:
            self._pending_vendor_mode = None
            return MarketDailyExecutionOutcome(
                status="already_active",
                requested_vendor_mode=requested_mode,
                reason="requested_vendor_mode_already_active",
            )
        if self._pending_vendor_mode == requested_mode:
            return MarketDailyExecutionOutcome(
                status="awaiting_mode_feedback",
                requested_vendor_mode=requested_mode,
                reason="duplicate_request_blocked",
            )

        primitive = selected[1]
        request_id = (
            f"mep:{snapshot.snapshot_id}:{plan.current_interval_ends_at.isoformat()}"
        )
        request = ExecutionPrimitiveRequest(
            request_id=request_id,
            plan_set_id=f"mep-plan-set:{snapshot.snapshot_id}",
            plan_id=f"mep-plan:{snapshot.snapshot_id}",
            plan_revision=1,
            segment_id=request_id,
            execution_scope_id=evidence.execution_scope_id,
            capability_id=evidence.capability_id,
            primitive=primitive,
            requested_at=executed_at,
        )
        mapping = HomeAssistantCommandMapping(
            mapping_id=f"mep-zendure-mode-{primitive.value}-v1",
            mapping_version=1,
            capability_id=evidence.capability_id,
            execution_scope_id=evidence.execution_scope_id,
            primitive=primitive,
            domain="input_select",
            service="select_option",
            entity_id=evidence.source_entity_id,
            value_key="option",
            fixed_value=requested_mode,
        )
        result: CanonicalDispatchOutcome = self.dispatch(request, mapping)
        if result.status == "dispatched":
            self._pending_vendor_mode = requested_mode
        return MarketDailyExecutionOutcome(
            status=result.status,
            requested_vendor_mode=requested_mode,
            reason="mep_current_interval_dispatched",
            command_id=result.command_id,
        )

    @staticmethod
    def _blocked(reason: str) -> MarketDailyExecutionOutcome:
        return MarketDailyExecutionOutcome(
            status="blocked",
            requested_vendor_mode=None,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class MarketDailyRuntimeOutcome:
    snapshot_id: str
    run_id: str
    captured_at: datetime
    status: str
    reason: str | None
    duration_ms: float
    plan: MarketDailyPlan | None
    execution: MarketDailyExecutionOutcome | None
    method_version: str

    def __post_init__(self) -> None:
        if self.status not in {"completed", "blocked"}:
            raise ValueError("MEP runtime status must be completed or blocked.")
        if (self.plan is None) != (self.status == "blocked"):
            raise ValueError("MEP runtime status must match its plan.")
        if self.status == "blocked" and not self.reason:
            raise ValueError("Blocked MEP runtime requires a reason.")
        if self.plan is not None and self.plan.snapshot_id != self.snapshot_id:
            raise ValueError("MEP runtime snapshot lineage must match.")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("MEP runtime capture time must be timezone-aware.")


class MarketDailyPlannerRuntime:
    def __init__(
        self,
        conversion_model: StorageConversionModel,
        *,
        live_enabled: bool = False,
        execution_runtime: MarketDailyExecutionRuntime | None = None,
    ) -> None:
        if live_enabled and execution_runtime is None:
            raise ValueError("live MEP requires an execution runtime")
        self.conversion_model = conversion_model
        self.live_enabled = live_enabled
        self.execution_runtime = execution_runtime

    def plan(self, snapshot: PlanningInputSnapshot) -> MarketDailyRuntimeOutcome:
        started = perf_counter()
        plan: MarketDailyPlan | None = None
        reason: str | None = None
        status = "completed"
        try:
            plan = MarketDailyPlanner().plan(
                snapshot=snapshot,
                conversion_model=self.conversion_model,
                dispatch_authority=self.live_enabled,
            )
        except Exception as exc:
            status = "blocked"
            reason = str(exc) or exc.__class__.__name__
        execution = (
            self.execution_runtime.apply(plan=plan, snapshot=snapshot)
            if plan is not None and self.execution_runtime is not None
            else None
        )
        return MarketDailyRuntimeOutcome(
            snapshot_id=snapshot.snapshot_id,
            run_id=snapshot.run_id,
            captured_at=snapshot.captured_at,
            status=status,
            reason=reason,
            duration_ms=round((perf_counter() - started) * 1000.0, 3),
            plan=plan,
            execution=execution,
            method_version=METHOD_VERSION,
        )


class MarketDailyPlannerWorker:
    """Run MEP serially off-thread and coalesce superseded snapshots."""

    def __init__(
        self,
        runtime: MarketDailyPlannerRuntime,
        *,
        on_outcome: Callable[[MarketDailyRuntimeOutcome], None] | None = None,
        on_error: Callable[[PlanningInputSnapshot, Exception], None] | None = None,
    ) -> None:
        self.runtime = runtime
        self.on_outcome = on_outcome
        self.on_error = on_error
        self._lock = Lock()
        self._pending: PlanningInputSnapshot | None = None
        self._thread: Thread | None = None

    def submit(self, snapshot: PlanningInputSnapshot) -> None:
        with self._lock:
            self._pending = snapshot
            if self._thread is not None:
                return
            self._thread = Thread(
                target=self._drain,
                name="picot-v2-market-daily-planner",
                daemon=True,
            )
            self._thread.start()

    def _drain(self) -> None:
        while True:
            with self._lock:
                snapshot = self._pending
                self._pending = None
                if snapshot is None:
                    self._thread = None
                    return
            try:
                outcome = self.runtime.plan(snapshot)
                if self.on_outcome is not None:
                    self.on_outcome(outcome)
            except Exception as exc:
                if self.on_error is not None:
                    self.on_error(snapshot, exc)
