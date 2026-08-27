"""Coalescing runtime boundary for the temporary third MEP planner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import sqrt
from threading import Lock, Thread
from time import perf_counter

from picot.domain.daily_reference_candidate import DailyReferenceCandidate
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import HomeAssistantCommandMapping
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.domain.storage_energy_inventory import StorageEnergyInventory
from picot.planner.market_daily_planner import (
    MarketDailyPlan,
    MarketDailyPlanner,
    MarketDailyPlannerDiagnostics,
    MarketTradingPolicy,
)
from picot.v2.canonical_execution_runtime import (
    CanonicalDispatchOutcome,
    DispatchCanonicalMode,
)
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
)

METHOD_VERSION = "v2-market-daily-runtime:v2"
MAXIMUM_MODE_EVIDENCE_AGE = timedelta(minutes=2)
MEP_COMMITMENT_METHOD_VERSION = "mep-active-plan-commitment:v1"
# An active MEP action may incur a real relay transition when it is replaced.
# Require a material five-cent plan improvement; sub-cent calculation noise is
# not sufficient authority to interrupt an executing plan.
MEP_CHALLENGER_FINANCIAL_SWITCH_MARGIN_EUR = 0.05
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
    evaluated_at: datetime | None = None
    commitment_status: str | None = None
    commitment_schedule_id: str | None = None
    challenger_reason: str | None = None
    challenger_financial_delta_eur: float | None = None


@dataclass(frozen=True, slots=True)
class _MepPlanProfile:
    candidate: DailyReferenceCandidate
    schedule: DailyReferenceIntentSchedule
    nom_starts_at: datetime | None
    nom_ends_at: datetime | None


def _native_plan_profile(
    plan: MarketDailyPlan,
    *,
    captured_at: datetime,
) -> _MepPlanProfile | None:
    if plan.winning_source != "mep_native_plan":
        return None
    result = plan.native_observation.observer_result
    if not result.best_observation_ids:
        return None
    candidates = {item.candidate_id: item for item in result.candidate_set.candidates}
    candidate = candidates.get(sorted(result.best_observation_ids)[0])
    if candidate is None:
        return None
    schedules = {
        item.intent_schedule.schedule_id: item.intent_schedule
        for item in result.portfolio.strategy_results
    }
    schedule = schedules.get(candidate.intent_schedule_id)
    if schedule is None:
        return None
    nom_indexes = tuple(
        index
        for index, interval in enumerate(schedule.intervals)
        if interval.intent is DailyStorageIntent.NOM
        and interval.ends_at > captured_at
    )
    if not nom_indexes:
        return _MepPlanProfile(candidate, schedule, None, None)
    first_index = next(
        (
            index
            for index in nom_indexes
            if schedule.intervals[index].starts_at <= captured_at
        ),
        nom_indexes[0],
    )
    phase_start = schedule.intervals[first_index].starts_at
    phase_end = schedule.intervals[first_index].ends_at
    for interval in schedule.intervals[first_index + 1:]:
        if interval.intent is not DailyStorageIntent.NOM or interval.starts_at != phase_end:
            break
        phase_end = interval.ends_at
    return _MepPlanProfile(candidate, schedule, phase_start, phase_end)


@dataclass(slots=True)
class MarketDailyExecutionRuntime:
    """Execute only an unambiguous current MEP intent, fail closed."""

    dispatch: DispatchCanonicalMode
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    commitment_store: ActivePlanCommitmentStore | None = None
    _pending_vendor_mode: str | None = None

    def apply(
        self,
        *,
        plan: MarketDailyPlan,
        snapshot: PlanningInputSnapshot,
    ) -> MarketDailyExecutionOutcome:
        if not plan.dispatch_authority:
            selected = (
                INTENT_MODE_MAPPING.get(plan.current_intent)
                if plan.current_intent is not None
                else None
            )
            return MarketDailyExecutionOutcome(
                status="observer_only",
                requested_vendor_mode=(selected[0] if selected is not None else None),
                reason="mep_live_authority_disabled",
            )
        executed_at = self.now()
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:
            raise ValueError("MEP execution clock must be timezone-aware")
        evidence = snapshot.storage_mode_capability_evidence
        provenance = snapshot.storage_mode_control_provenance
        if evidence is None or evidence.status != "available":
            return self._blocked(
                "storage_mode_capability_unavailable",
                executed_at,
            )
        if (
            evidence.captured_at != snapshot.captured_at
            or executed_at - evidence.captured_at > MAXIMUM_MODE_EVIDENCE_AGE
        ):
            return self._blocked("storage_mode_capability_stale", executed_at)
        if provenance is None:
            return self._blocked(
                "storage_mode_provenance_unavailable",
                executed_at,
            )
        if provenance.manual_override_active:
            return self._blocked("manual_override_active", executed_at)
        if executed_at - provenance.observed_at > MAXIMUM_MODE_EVIDENCE_AGE:
            return self._blocked("storage_mode_provenance_stale", executed_at)
        calibration = snapshot.bms_calibration_evidence
        if calibration is not None and calibration.active:
            return self._blocked("bms_soc_calibration_active", executed_at)
        (
            plan,
            commitment_status,
            commitment_schedule_id,
            challenger_reason,
            challenger_delta,
        ) = self._resolve_commitment(
            plan=plan,
            snapshot=snapshot,
            executed_at=executed_at,
            execution_scope_id=evidence.execution_scope_id,
        )
        selected = (
            INTENT_MODE_MAPPING.get(plan.current_intent)
            if plan.current_intent is not None
            else None
        )
        requested_mode = selected[0] if selected is not None else None
        if selected is None or plan.current_interval_ends_at is None:
            return self._blocked("mep_current_intent_ambiguous", executed_at)
        if executed_at >= plan.current_interval_ends_at:
            return self._blocked("mep_current_interval_expired", executed_at)
        if requested_mode not in evidence.usable_vendor_modes:
            return self._blocked("requested_vendor_mode_unavailable", executed_at)
        if evidence.current_vendor_mode != provenance.observed_vendor_mode:
            return self._blocked("storage_mode_evidence_conflict", executed_at)
        if evidence.current_vendor_mode == requested_mode:
            self._pending_vendor_mode = None
            saved = None
            if plan.current_intent in {
                DailyStorageIntent.NOM,
                DailyStorageIntent.STORAGE_EXPORT,
            }:
                saved = self._persist_action_commitment(
                    plan=plan,
                    snapshot=snapshot,
                    execution_scope_id=evidence.execution_scope_id,
                    captured_at=executed_at,
                )
                if saved is not None:
                    commitment_status = commitment_status or "created"
                    commitment_schedule_id = saved.schedule_id
            return MarketDailyExecutionOutcome(
                status="already_active",
                requested_vendor_mode=requested_mode,
                reason="requested_vendor_mode_already_active",
                evaluated_at=executed_at,
                commitment_status=commitment_status,
                commitment_schedule_id=commitment_schedule_id,
                challenger_reason=challenger_reason,
                challenger_financial_delta_eur=challenger_delta,
            )
        if self._pending_vendor_mode == requested_mode:
            return MarketDailyExecutionOutcome(
                status="awaiting_mode_feedback",
                requested_vendor_mode=requested_mode,
                reason="duplicate_request_blocked",
                evaluated_at=executed_at,
                commitment_status=commitment_status,
                commitment_schedule_id=commitment_schedule_id,
                challenger_reason=challenger_reason,
                challenger_financial_delta_eur=challenger_delta,
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
        if (
            plan.current_intent
            in {DailyStorageIntent.NOM, DailyStorageIntent.STORAGE_EXPORT}
            and result.status in {"dispatched", "already_active"}
        ):
            saved = self._persist_action_commitment(
                plan=plan,
                snapshot=snapshot,
                execution_scope_id=evidence.execution_scope_id,
                captured_at=executed_at,
            )
            if saved is not None:
                commitment_status = commitment_status or "created"
                commitment_schedule_id = saved.schedule_id
        return MarketDailyExecutionOutcome(
            status=result.status,
            requested_vendor_mode=requested_mode,
            reason="mep_current_interval_dispatched",
            command_id=result.command_id,
            evaluated_at=executed_at,
            commitment_status=commitment_status,
            commitment_schedule_id=commitment_schedule_id,
            challenger_reason=challenger_reason,
            challenger_financial_delta_eur=challenger_delta,
        )

    def _resolve_commitment(
        self,
        *,
        plan: MarketDailyPlan,
        snapshot: PlanningInputSnapshot,
        executed_at: datetime,
        execution_scope_id: str,
    ) -> tuple[
        MarketDailyPlan,
        str | None,
        str | None,
        str | None,
        float | None,
    ]:
        if self.commitment_store is None:
            return plan, None, None, None, None
        commitment = self.commitment_store.load(execution_scope_id)
        if commitment is None or commitment.planner_id != "mep":
            return plan, None, None, None, None
        if executed_at >= commitment.ends_at or self._target_reached(snapshot, commitment):
            self.commitment_store.clear(execution_scope_id)
            return plan, "completed", commitment.schedule_id, None, None
        if executed_at < commitment.starts_at:
            return plan, "future", commitment.schedule_id, None, None

        if commitment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value:
            preserved = replace(
                plan,
                current_intent=DailyStorageIntent.STORAGE_EXPORT,
                current_interval_ends_at=commitment.ends_at,
            )
            return (
                preserved,
                "preserved",
                commitment.schedule_id,
                "active_export_window_committed",
                0.0,
            )

        profile = _native_plan_profile(plan, captured_at=executed_at)
        better, reason, delta = self._challenger_is_better(profile, commitment)
        if better:
            self.commitment_store.clear(execution_scope_id)
            return plan, "replaced", commitment.schedule_id, reason, delta
        preserved = replace(
            plan,
            current_intent=DailyStorageIntent.NOM,
            current_interval_ends_at=commitment.ends_at,
        )
        return (
            preserved,
            "preserved",
            commitment.schedule_id,
            reason,
            delta,
        )

    @staticmethod
    def _target_reached(
        snapshot: PlanningInputSnapshot,
        commitment: ActivePlanCommitment,
    ) -> bool:
        state = next(
            (
                item
                for item in snapshot.current_storage_states
                if item.execution_scope_id == commitment.execution_scope_id
            ),
            None,
        )
        if state is None:
            return False
        if commitment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value:
            return state.current_stored_energy_wh <= commitment.target_energy_wh
        return state.current_stored_energy_wh >= commitment.target_energy_wh

    @staticmethod
    def _challenger_is_better(
        profile: _MepPlanProfile | None,
        commitment: ActivePlanCommitment,
    ) -> tuple[bool, str, float | None]:
        if profile is None:
            return False, "challenger_evidence_incomplete", None
        candidate = profile.candidate
        if not candidate.complete_across_scenarios:
            return False, "challenger_not_complete", None
        if (
            commitment.reserve_respected_across_scenarios is True
            and not candidate.reserve_respected_across_scenarios
        ):
            return False, "challenger_reserve_worse", None
        if (
            commitment.target_held_across_scenarios is True
            and not candidate.target_held_across_scenarios
        ):
            return False, "challenger_target_worse", None
        if (
            commitment.target_held_across_scenarios is False
            and candidate.target_held_across_scenarios
        ):
            return True, "challenger_target_proven_better", None
        challenger_energy = min(
            item.storage_energy_at_horizon_end_wh
            for item in candidate.scenario_outcomes
        )
        committed_energy = commitment.minimum_storage_energy_at_horizon_end_wh
        if committed_energy is not None:
            if challenger_energy < committed_energy - 1.0:
                return False, "challenger_storage_progress_worse", None
            if challenger_energy > committed_energy + 1.0:
                return True, "challenger_storage_progress_proven_better", None
        previous = commitment.worst_case_financial_result_eur
        if previous is None:
            return False, "commitment_financial_evidence_missing", None
        delta = candidate.worst_case_financial_result_eur - previous
        if delta > MEP_CHALLENGER_FINANCIAL_SWITCH_MARGIN_EUR:
            return True, "challenger_financially_proven_better", round(delta, 4)
        return False, "challenger_not_strictly_better", round(delta, 4)

    def _persist_action_commitment(
        self,
        *,
        plan: MarketDailyPlan,
        snapshot: PlanningInputSnapshot,
        execution_scope_id: str,
        captured_at: datetime,
    ) -> ActivePlanCommitment | None:
        if self.commitment_store is None:
            return None
        existing = self.commitment_store.load(execution_scope_id)
        if existing is not None and existing.planner_id == "mep":
            return existing
        if plan.current_intent is DailyStorageIntent.STORAGE_EXPORT:
            admitted = tuple(
                item for item in plan.route_assessments if item.admitted
            )
            if not admitted or plan.current_interval_ends_at is None:
                return None
            winner = max(
                admitted,
                key=lambda item: (
                    item.worst_case_incremental_result_eur,
                    item.minimum_incremental_result_eur_per_exported_kwh,
                    item.market_schedule_id,
                ),
            )
            route = next(
                (item for item in plan.market_routes if item.route_id == winner.route_id),
                None,
            )
            state = next(
                (
                    item
                    for item in snapshot.current_storage_states
                    if item.execution_scope_id == execution_scope_id
                ),
                None,
            )
            limit = next(
                (
                    item
                    for item in snapshot.storage_physical_limits
                    if item.execution_scope_id == execution_scope_id
                ),
                None,
            )
            if state is None or limit is None or route is None:
                return None
            directional_efficiency = sqrt(plan.round_trip_efficiency)
            target_energy_wh = max(
                state.usable_capacity_wh * limit.minimum_soc,
                state.current_stored_energy_wh
                - route.required_pre_window_discharge_output_wh
                / directional_efficiency,
            )
            commitment = ActivePlanCommitment(
                execution_scope_id=execution_scope_id,
                plan_id=f"mep-plan:{snapshot.snapshot_id}",
                plan_revision=1,
                primitive=ExecutionPrimitive.DISCHARGE_AT_POWER.value,
                source_policy="market_inventory_export",
                starts_at=captured_at,
                ends_at=plan.current_interval_ends_at,
                target_energy_wh=target_energy_wh,
                selection_method_version=MEP_COMMITMENT_METHOD_VERSION,
                planner_id="mep",
                schedule_id=winner.market_schedule_id,
                worst_case_financial_result_eur=(
                    winner.worst_case_incremental_result_eur
                ),
                reserve_respected_across_scenarios=all(
                    item.reserve_respected for item in winner.scenario_evidence
                ),
                target_held_across_scenarios=all(
                    item.target_held_at_horizon_end
                    for item in winner.scenario_evidence
                ),
                minimum_storage_energy_at_horizon_end_wh=min(
                    item.storage_energy_at_horizon_end_wh
                    for item in winner.scenario_evidence
                ),
            )
            self.commitment_store.save(commitment)
            return commitment

        profile = _native_plan_profile(plan, captured_at=captured_at)
        if (
            profile is None
            or profile.nom_starts_at is None
            or profile.nom_ends_at is None
        ):
            return None
        state = next(
            (
                item
                for item in snapshot.current_storage_states
                if item.execution_scope_id == execution_scope_id
            ),
            None,
        )
        if state is None:
            return None
        commitment = ActivePlanCommitment(
            execution_scope_id=execution_scope_id,
            plan_id=f"mep-plan:{snapshot.snapshot_id}",
            plan_revision=1,
            primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value,
            source_policy="pv_only",
            starts_at=min(profile.nom_starts_at, captured_at),
            ends_at=profile.nom_ends_at,
            target_energy_wh=state.usable_capacity_wh,
            selection_method_version=MEP_COMMITMENT_METHOD_VERSION,
            planner_id="mep",
            schedule_id=profile.schedule.schedule_id,
            worst_case_financial_result_eur=(
                profile.candidate.worst_case_financial_result_eur
            ),
            average_charge_window_price_eur_per_kwh=(
                profile.candidate.average_charge_window_price_eur_per_kwh
            ),
            minimum_confidence=profile.candidate.minimum_confidence,
            reserve_respected_across_scenarios=(
                profile.candidate.reserve_respected_across_scenarios
            ),
            target_held_across_scenarios=(
                profile.candidate.target_held_across_scenarios
            ),
            minimum_storage_energy_at_horizon_end_wh=min(
                item.storage_energy_at_horizon_end_wh
                for item in profile.candidate.scenario_outcomes
            ),
        )
        self.commitment_store.save(commitment)
        return commitment

    @staticmethod
    def _blocked(
        reason: str,
        evaluated_at: datetime | None = None,
    ) -> MarketDailyExecutionOutcome:
        return MarketDailyExecutionOutcome(
            status="blocked",
            requested_vendor_mode=None,
            reason=reason,
            evaluated_at=evaluated_at,
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
    planner_diagnostics: MarketDailyPlannerDiagnostics | None = None

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
        trading_policy: MarketTradingPolicy | None = None,
        micro_charge_suppression_fraction: float = 0.01,
        storage_inventory_provider: Callable[[], StorageEnergyInventory | None] | None = None,
    ) -> None:
        if live_enabled and execution_runtime is None:
            raise ValueError("live MEP requires an execution runtime")
        self.conversion_model = conversion_model
        self.live_enabled = live_enabled
        self.execution_runtime = execution_runtime
        self.trading_policy = trading_policy or MarketTradingPolicy()
        self.micro_charge_suppression_fraction = micro_charge_suppression_fraction
        self.storage_inventory_provider = storage_inventory_provider

    def _planning_configuration(
        self,
        snapshot: PlanningInputSnapshot,
    ) -> tuple[StorageConversionModel, MarketTradingPolicy]:
        evidence = snapshot.storage_round_trip_efficiency
        if (
            evidence is None
            or evidence.status != "available"
            or evidence.round_trip_efficiency is None
        ):
            return self.conversion_model, replace(
                self.trading_policy,
                market_routes_enabled=False,
            )
        directional_efficiency = sqrt(evidence.round_trip_efficiency)
        return (
            StorageConversionModel(
                model_id=f"mep-zendure-rte:{snapshot.snapshot_id}",
                charge_efficiency=directional_efficiency,
                discharge_efficiency=directional_efficiency,
                evidence_ids=(evidence.evidence_id,),
                method_version="measured-zendure-total-rte:v1",
            ),
            self.trading_policy,
        )

    def plan(self, snapshot: PlanningInputSnapshot) -> MarketDailyRuntimeOutcome:
        started = perf_counter()
        plan: MarketDailyPlan | None = None
        reason: str | None = None
        status = "completed"
        try:
            conversion_model, trading_policy = self._planning_configuration(snapshot)
            plan, planner_diagnostics = MarketDailyPlanner().plan_with_diagnostics(
                snapshot=snapshot,
                conversion_model=conversion_model,
                trading_policy=trading_policy,
                dispatch_authority=self.live_enabled,
                micro_charge_suppression_fraction=(
                    self.micro_charge_suppression_fraction
                ),
                storage_inventory=(
                    self.storage_inventory_provider()
                    if self.storage_inventory_provider is not None
                    else None
                ),
            )
        except Exception as exc:
            status = "blocked"
            reason = str(exc) or exc.__class__.__name__
            planner_diagnostics = None
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
            planner_diagnostics=planner_diagnostics,
            method_version=METHOD_VERSION,
        )

    def advance(
        self,
        outcome: MarketDailyRuntimeOutcome,
        snapshot: PlanningInputSnapshot,
    ) -> MarketDailyRuntimeOutcome:
        """Execute the next interval from the retained plan without replanning."""
        if outcome.plan is None:
            return outcome
        current_intent, current_interval_ends_at = (
            MarketDailyPlanner._current_decision(
                captured_at=snapshot.captured_at,
                native_observation=outcome.plan.native_observation,
                assessments=outcome.plan.route_assessments,
            )
        )
        advanced_plan = replace(
            outcome.plan,
            current_intent=current_intent,
            current_interval_ends_at=current_interval_ends_at,
        )
        execution = (
            self.execution_runtime.apply(plan=advanced_plan, snapshot=snapshot)
            if self.execution_runtime is not None
            else None
        )
        return replace(outcome, plan=advanced_plan, execution=execution)


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
        self._latest_outcome: MarketDailyRuntimeOutcome | None = None

    def advance(self, snapshot: PlanningInputSnapshot) -> bool:
        """Advance retained intent at a clock boundary using fresh evidence."""
        with self._lock:
            latest = self._latest_outcome
        if latest is None:
            return False
        try:
            outcome = self.runtime.advance(latest, snapshot)
        except Exception as exc:
            if self.on_error is not None:
                self.on_error(snapshot, exc)
            return False
        with self._lock:
            if self._latest_outcome is not latest:
                return False
            self._latest_outcome = outcome
        try:
            if self.on_outcome is not None:
                self.on_outcome(outcome)
        except Exception as exc:
            if self.on_error is not None:
                self.on_error(snapshot, exc)
            return False
        return True

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

    def process(self, snapshot: PlanningInputSnapshot) -> None:
        """Process one snapshot synchronously in an external ordered worker."""
        self._process(snapshot)

    def _process(self, snapshot: PlanningInputSnapshot) -> None:
        try:
            outcome = self.runtime.plan(snapshot)
            with self._lock:
                self._latest_outcome = outcome
            if self.on_outcome is not None:
                self.on_outcome(outcome)
        except Exception as exc:
            if self.on_error is not None:
                self.on_error(snapshot, exc)

    def _drain(self) -> None:
        while True:
            with self._lock:
                snapshot = self._pending
                self._pending = None
                if snapshot is None:
                    self._thread = None
                    return
            self._process(snapshot)
