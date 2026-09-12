"""Canonical stage composition for the sole Markt Etmaal Planner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from hashlib import sha256
from time import perf_counter

from picot.architecture_ownership import architecture_ownership
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.daily_reference_candidate import DailyReferenceCandidate
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_portfolio import DailyReferenceStrategyResult
from picot.domain.energy_path import PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.domain.market_plan_binding import MarketPlanBinding
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.planner.market_daily_planner import (
    MarketDailyCandidatePortfolio,
    MarketDailyPlan,
    MarketRouteAssessment,
)
from picot.planner.mep_candidate_outcomes import (
    produce_main_charge_portfolio,
    produce_mep_comparable_portfolio,
)
from picot.v2.contracts import (
    Candidate,
    CandidateOutcomeSet,
    CandidateSet,
    CanonicalPipelineRun,
    DeviceAdapterBoundary,
    EnergyPath,
    EvaluationRecord,
    ExecutionPlanSet,
    ExecutionPrimitiveBoundary,
    ExecutionRecord,
    OpportunitySet,
    PlanningInputSnapshot,
    PVChargeProgressEvidence,
    VendorBoundaryResult,
)
from picot.v2.daily_bridge import DailyBridgeTrigger, energy_deficits
from picot.v2.daily_charge_assignment import DailyMainShortfallTrigger
from picot.v2.daily_pv_comparison import (
    DailyMainPVSurplusTrigger,
    DailyPVComparisonBasis,
    compare_daily_pv,
)
from picot.v2.execution_plan_projection import _project_plan, project_execution_plan_set
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.market_daily_runtime import (
    MarketDailyPlannerRuntime,
    MarketDailyRuntimeOutcome,
)
from picot.v2.market_rule_planning import market_rule_portfolio
from picot.v2.plan_commitment_store import (
    COMMITMENT_METHOD_VERSION,
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
    CommittedHouseholdLoadInterval,
    CommittedPlanSegment,
    CommittedStorageEnergyCheckpoint,
    active_pv_preservation_dates,
)

ARCHITECTURE_OWNERSHIP = architecture_ownership("pipeline_composition", __name__)
PV_CHARGE_PROGRESS_METHOD_VERSION = "pv-charge-progress:v1"


@dataclass(frozen=True, slots=True)
class MepCanonicalStageTimings:
    candidate_engine_ms: float
    evaluation_engine_ms: float
    execution_plan_builder_ms: float
    execution_engine_ms: float
    execution_primitive_ms: float
    device_adapter_ms: float
    vendor_result_ms: float


def _id(prefix: str, seed: str) -> str:
    return f"{prefix}-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _intent_primitive(
    intent: DailyStorageIntent,
) -> tuple[ExecutionPrimitive, ChargeSourcePolicy | None]:
    if intent is DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY:
        return ExecutionPrimitive.BALANCE_DISCHARGE_ONLY, None
    if intent is DailyStorageIntent.NOM:
        return ExecutionPrimitive.BALANCE_BIDIRECTIONAL, ChargeSourcePolicy.PV_ONLY
    if intent is DailyStorageIntent.GRID_REQUIREMENT:
        return (
            ExecutionPrimitive.CHARGE_AT_POWER,
            ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED,
        )
    if intent is DailyStorageIntent.STORAGE_EXPORT:
        return ExecutionPrimitive.DISCHARGE_AT_POWER, None
    return ExecutionPrimitive.STANDBY, None


def _coalesce(
    intervals: tuple[DailyReferenceIntentInterval, ...],
) -> tuple[tuple[datetime, datetime, DailyStorageIntent], ...]:
    phases: list[tuple[datetime, datetime, DailyStorageIntent]] = []
    for interval in intervals:
        if phases and phases[-1][1] == interval.starts_at and phases[-1][2] is interval.intent:
            phases[-1] = (phases[-1][0], interval.ends_at, interval.intent)
        else:
            phases.append((interval.starts_at, interval.ends_at, interval.intent))
    return tuple(phases)


def _coalesce_committed_segments(
    segments: tuple[CommittedPlanSegment, ...],
) -> tuple[CommittedPlanSegment, ...]:
    coalesced: list[CommittedPlanSegment] = []
    for segment in segments:
        if (
            coalesced
            and coalesced[-1].ends_at == segment.starts_at
            and coalesced[-1].primitive == segment.primitive
            and coalesced[-1].source_policy == segment.source_policy
            and coalesced[-1].storage_export_target_wh is None
            and segment.storage_export_target_wh is None
        ):
            coalesced[-1] = replace(coalesced[-1], ends_at=segment.ends_at)
        else:
            coalesced.append(segment)
    return tuple(coalesced)


def _committed_execution_segments(
    segments: tuple[PathSegment, ...],
) -> tuple[CommittedPlanSegment, ...]:
    """Persist the executable boundaries, including partial export intervals."""

    return _coalesce_committed_segments(
        tuple(
            CommittedPlanSegment(
                starts_at=segment.starts_at,
                ends_at=segment.ends_at,
                primitive=segment.primitive.value,
                source_policy=(
                    segment.charge_source_policy.value
                    if segment.charge_source_policy is not None
                    else None
                ),
                storage_export_target_wh=(
                    (segment.requested_power_w or 0.0)
                    * (segment.ends_at - segment.starts_at).total_seconds()
                    / 3600.0
                    if segment.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER
                    else None
                ),
            )
            for segment in segments
        )
    )


def _commitment_target_reached(
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
    has_future_export = any(
        segment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value
        and segment.ends_at > snapshot.captured_at
        for segment in commitment.segments
    )
    if has_future_export:
        return False
    if commitment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value:
        return state.current_stored_energy_wh <= commitment.target_energy_wh
    return state.current_stored_energy_wh >= commitment.target_energy_wh


def _has_future_export(
    commitment: ActivePlanCommitment,
    captured_at: datetime,
) -> bool:
    return any(
        segment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value
        and segment.ends_at > captured_at
        for segment in commitment.segments
    )


def _complete_acquisition_revision(
    *,
    snapshot: PlanningInputSnapshot,
    commitment: ActivePlanCommitment,
) -> ActivePlanCommitment | None:
    """Remove completed charge phases without discarding later export."""

    state = next(
        (
            item
            for item in snapshot.current_storage_states
            if item.execution_scope_id == commitment.execution_scope_id
        ),
        None,
    )
    future_exports = tuple(
        segment
        for segment in commitment.segments
        if segment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value
        and segment.ends_at > snapshot.captured_at
    )
    future_charges = tuple(
        segment
        for segment in commitment.segments
        if segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value
        and segment.ends_at > snapshot.captured_at
    )
    has_acquisition_before_export = any(
        charge.ends_at <= export.starts_at for charge in future_charges for export in future_exports
    )

    def is_pre_export_acquisition(segment: CommittedPlanSegment) -> bool:
        return segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value and any(
            segment.ends_at <= export.starts_at for export in future_exports
        )

    if (
        state is None
        or state.current_stored_energy_wh + 1e-6 < commitment.target_energy_wh
        or not future_exports
        or not future_charges
        or not has_acquisition_before_export
    ):
        return None
    revised_segments = _coalesce_committed_segments(
        tuple(
            replace(
                segment,
                starts_at=max(segment.starts_at, snapshot.captured_at),
                primitive=(
                    ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value
                    if is_pre_export_acquisition(segment)
                    else segment.primitive
                ),
                source_policy=(
                    ChargeSourcePolicy.PV_ONLY.value
                    if is_pre_export_acquisition(segment)
                    else segment.source_policy
                ),
            )
            for segment in commitment.segments
            if segment.ends_at > snapshot.captured_at
        )
    )
    return replace(
        commitment,
        plan_id=_id(
            "mep-plan-revision",
            f"{commitment.plan_id}|acquisition-complete|{snapshot.captured_at.isoformat()}",
        ),
        plan_revision=commitment.plan_revision + 1,
        primitive=revised_segments[0].primitive,
        source_policy=(revised_segments[0].source_policy or "not_applicable"),
        starts_at=revised_segments[0].starts_at,
        ends_at=revised_segments[-1].ends_at,
        segments=revised_segments,
        selection_reason="execution_feedback:acquisition_target_reached",
        replaced_plan_id=commitment.plan_id,
    )


def _defer_charge_revision(
    *,
    snapshot: PlanningInputSnapshot,
    commitment: ActivePlanCommitment,
) -> ActivePlanCommitment | None:
    """Move a PV-covered due charge phase to the last safe fallback slot."""

    segments = list(commitment.segments)
    due_index = next(
        (
            index
            for index, segment in enumerate(segments)
            if segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value
            and segment.starts_at <= snapshot.captured_at < segment.ends_at
        ),
        None,
    )
    if due_index is None or due_index + 1 >= len(segments):
        return None
    due = segments[due_index]
    following = segments[due_index + 1]
    if following.primitive != ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value:
        return None
    storage = next(
        (
            item
            for item in snapshot.current_storage_states
            if item.execution_scope_id == commitment.execution_scope_id
        ),
        None,
    )
    limits = next(
        (
            item
            for item in snapshot.storage_physical_limits
            if storage is not None
            and item.execution_scope_id == commitment.execution_scope_id
            and item.capability_id == storage.capability_id
        ),
        None,
    )
    if storage is None or limits is None:
        return None
    remaining_target_wh = max(
        0.0,
        commitment.target_energy_wh - storage.current_stored_energy_wh,
    )
    rte = snapshot.storage_round_trip_efficiency
    conservative_charge_efficiency = (
        rte.round_trip_efficiency
        if rte is not None and rte.status == "available" and rte.round_trip_efficiency is not None
        else 0.8
    )
    required_grid_input_wh = remaining_target_wh / conservative_charge_efficiency
    duration = timedelta(hours=required_grid_input_wh / limits.maximum_charge_input_power_w)
    if duration <= timedelta(0):
        return None
    canonical_interval = timedelta(minutes=15)
    shifted_end = following.ends_at - canonical_interval
    shifted_start = shifted_end - duration
    if shifted_start <= snapshot.captured_at:
        return None
    revised: list[CommittedPlanSegment] = []
    revised.extend(
        segment for segment in segments[:due_index] if segment.ends_at > snapshot.captured_at
    )
    revised.append(
        CommittedPlanSegment(
            starts_at=snapshot.captured_at,
            ends_at=shifted_start,
            primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value,
            source_policy=ChargeSourcePolicy.PV_ONLY.value,
        )
    )
    revised.append(replace(due, starts_at=shifted_start, ends_at=shifted_end))
    revised.append(replace(following, starts_at=shifted_end))
    revised.extend(segments[due_index + 2 :])
    revised_segments = _coalesce_committed_segments(tuple(revised))
    return replace(
        commitment,
        plan_id=_id(
            "mep-plan-revision",
            f"{commitment.plan_id}|pv-deferred|{snapshot.captured_at.isoformat()}",
        ),
        plan_revision=commitment.plan_revision + 1,
        primitive=revised_segments[0].primitive,
        source_policy=(revised_segments[0].source_policy or "not_applicable"),
        starts_at=revised_segments[0].starts_at,
        ends_at=revised_segments[-1].ends_at,
        segments=revised_segments,
        selection_reason=("execution_feedback:measured_pv_progress_covers_grid_charge"),
        replaced_plan_id=commitment.plan_id,
    )


def _overlap_fraction(
    starts_at: datetime,
    ends_at: datetime,
    window_starts_at: datetime,
    window_ends_at: datetime,
) -> float:
    overlap_starts_at = max(starts_at, window_starts_at)
    overlap_ends_at = min(ends_at, window_ends_at)
    if overlap_ends_at <= overlap_starts_at:
        return 0.0
    return (overlap_ends_at - overlap_starts_at).total_seconds() / (
        ends_at - starts_at
    ).total_seconds()


def _measured_pv_basis_covers_remaining_acquisition(
    *,
    snapshot: PlanningInputSnapshot,
    path: EnergyPath,
    due_segment: PathSegment,
) -> bool:
    """Keep NOM while actual SoC plus conservative future PV can reach target."""

    return (
        _pv_charge_progress_evidence(
            snapshot=snapshot,
            path=path,
            due_segment=due_segment,
        ).decision
        == "defer_grid_charge"
    )


def _pv_charge_progress_evidence(
    *,
    snapshot: PlanningInputSnapshot,
    path: EnergyPath,
    due_segment: PathSegment,
) -> PVChargeProgressEvidence:
    def unavailable(reason: str) -> PVChargeProgressEvidence:
        return PVChargeProgressEvidence(
            method_version=PV_CHARGE_PROGRESS_METHOD_VERSION,
            decision="keep_grid_charge",
            reason=reason,
        )

    if due_segment.primitive is not ExecutionPrimitive.CHARGE_AT_POWER:
        return unavailable("not_a_grid_charge_segment")
    mode = snapshot.storage_mode_capability_evidence
    if mode is None or mode.current_vendor_mode != "Nul op de meter":
        return unavailable("current_mode_is_not_nom")
    if snapshot.pv_energy_timeline is None or snapshot.household_load_forecast is None:
        return unavailable("future_pv_or_household_forecast_unavailable")
    storage = next(
        (
            item
            for item in snapshot.current_storage_states
            if item.execution_scope_id == due_segment.execution_scope_id
        ),
        None,
    )
    limits = next(
        (
            item
            for item in snapshot.storage_physical_limits
            if item.execution_scope_id == due_segment.execution_scope_id
            and storage is not None
            and item.capability_id == storage.capability_id
        ),
        None,
    )
    if storage is None or limits is None:
        return unavailable("storage_state_or_limits_unavailable")
    ordered = tuple(sorted(path.segments, key=lambda item: item.order))
    due_index = next(
        (index for index, item in enumerate(ordered) if item.segment_id == due_segment.segment_id),
        None,
    )
    if due_index is None:
        return unavailable("due_segment_not_in_winning_path")
    acquisition_end = due_segment.ends_at
    for segment in ordered[due_index + 1 :]:
        if segment.starts_at != acquisition_end or segment.primitive not in {
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        }:
            break
        acquisition_end = segment.ends_at
    window_start = snapshot.captured_at
    future_pv = tuple(
        item
        for item in snapshot.pv_energy_timeline.intervals
        if item.ends_at > window_start and item.starts_at < acquisition_end
    )
    if not future_pv or any(item.forecast_lower_energy_wh is None for item in future_pv):
        return unavailable("conservative_future_pv_range_incomplete")
    pv_surplus_wh = sum(
        (item.forecast_lower_energy_wh or 0.0)
        * _overlap_fraction(
            item.starts_at,
            item.ends_at,
            window_start,
            acquisition_end,
        )
        for item in future_pv
    ) - sum(
        item.expected_energy_wh
        * _overlap_fraction(
            item.starts_at,
            item.ends_at,
            window_start,
            acquisition_end,
        )
        for item in snapshot.household_load_forecast.intervals
    )
    rte = snapshot.storage_round_trip_efficiency
    conservative_charge_efficiency = (
        rte.round_trip_efficiency
        if rte is not None and rte.status == "available" and rte.round_trip_efficiency is not None
        else 0.8
    )
    conservative_pv_to_storage_wh = max(0.0, pv_surplus_wh) * conservative_charge_efficiency
    target_energy_wh = limits.maximum_soc * storage.usable_capacity_wh
    remaining_target_wh = max(0.0, target_energy_wh - storage.current_stored_energy_wh)
    required_grid_input_wh = remaining_target_wh / conservative_charge_efficiency
    latest_safe_start = (
        acquisition_end
        - timedelta(minutes=15)
        - timedelta(hours=required_grid_input_wh / limits.maximum_charge_input_power_w)
    )
    pv_covers_target = conservative_pv_to_storage_wh + 1e-6 >= remaining_target_wh
    before_latest_safe_start = snapshot.captured_at < latest_safe_start
    return PVChargeProgressEvidence(
        method_version=PV_CHARGE_PROGRESS_METHOD_VERSION,
        decision=(
            "defer_grid_charge"
            if pv_covers_target and before_latest_safe_start
            else "keep_grid_charge"
        ),
        reason=(
            "conservative_pv_can_cover_remaining_target"
            if pv_covers_target and before_latest_safe_start
            else "latest_safe_grid_start_reached"
            if pv_covers_target
            else "conservative_pv_cannot_cover_remaining_target"
        ),
        remaining_target_energy_wh=remaining_target_wh,
        conservative_pv_to_storage_wh=conservative_pv_to_storage_wh,
        required_grid_input_energy_wh=required_grid_input_wh,
        acquisition_deadline=acquisition_end,
        latest_safe_grid_charge_starts_at=latest_safe_start,
    )


def _first_action_phase(
    schedule: DailyReferenceIntentSchedule,
    captured_at: datetime,
) -> tuple[datetime, datetime, DailyStorageIntent] | None:
    actionable = {
        DailyStorageIntent.NOM,
        DailyStorageIntent.GRID_REQUIREMENT,
        DailyStorageIntent.STORAGE_EXPORT,
    }
    return next(
        (
            phase
            for phase in _coalesce(schedule.intervals)
            if phase[1] > captured_at and phase[2] in actionable
        ),
        None,
    )


def _committed_storage_energy_checkpoints(
    *,
    plan: MarketDailyPlan | MarketDailyCandidatePortfolio,
    schedule: DailyReferenceIntentSchedule,
    market: MarketRouteAssessment | None,
    projected_result: DailyReferenceStrategyResult | None = None,
) -> tuple[CommittedStorageEnergyCheckpoint, ...]:
    by_scenario: dict[str, dict[datetime, float]] = {}
    if projected_result is not None:
        by_scenario = {
            trajectory.scenario.value: {
                interval.ends_at: interval.storage_energy_at_end_wh
                for interval in trajectory.intervals
            }
            for trajectory in projected_result.run.simulation.trajectories
        }
    elif market is not None:
        by_scenario = {
            evidence.scenario.value: {
                checkpoint.at: checkpoint.energy_wh
                for checkpoint in evidence.storage_energy_checkpoints
            }
            for evidence in market.scenario_evidence
        }
    else:
        strategy_result = next(
            (
                item
                for item in (plan.native_observation.observer_result.portfolio.strategy_results)
                if item.intent_schedule.schedule_id == schedule.schedule_id
            ),
            None,
        )
        if strategy_result is not None:
            by_scenario = {
                trajectory.scenario.value: {
                    interval.ends_at: interval.storage_energy_at_end_wh
                    for interval in trajectory.intervals
                }
                for trajectory in strategy_result.run.simulation.trajectories
            }

    required = {"lower", "central", "upper"}
    if set(by_scenario) != required:
        return ()
    checkpoint_times = set(by_scenario["lower"])
    checkpoint_times.intersection_update(by_scenario["central"])
    checkpoint_times.intersection_update(by_scenario["upper"])
    return tuple(
        CommittedStorageEnergyCheckpoint(
            at=at,
            lower_energy_wh=by_scenario["lower"][at],
            central_energy_wh=by_scenario["central"][at],
            upper_energy_wh=by_scenario["upper"][at],
        )
        for at in sorted(checkpoint_times)
    )


def _persist_plan(
    *,
    store: ActivePlanCommitmentStore | None,
    snapshot: PlanningInputSnapshot,
    plan: MarketDailyPlan | MarketDailyCandidatePortfolio,
    schedule: DailyReferenceIntentSchedule,
    execution_segments: tuple[PathSegment, ...],
    plan_id: str,
    native: DailyReferenceCandidate | None,
    market: MarketRouteAssessment | None,
    projected_result: DailyReferenceStrategyResult | None = None,
    candidate_family: str | None = None,
    prior_commitment: ActivePlanCommitment | None = None,
    preserve_pv_during_grid_charge: bool,
    selection_reason: str,
) -> None:
    if store is None or not snapshot.current_storage_states:
        return
    storage = snapshot.current_storage_states[0]
    action_phase = _first_action_phase(schedule, snapshot.captured_at)
    if action_phase is None:
        return
    coalesced_segments = _coalesce(schedule.intervals)
    starts_at, _first_ends_at, first_intent = coalesced_segments[0]
    primitive, source_policy = _intent_primitive(first_intent)
    action_primitive, _action_source_policy = _intent_primitive(action_phase[2])
    limits = next(
        item
        for item in snapshot.storage_physical_limits
        if item.execution_scope_id == storage.execution_scope_id
        and item.capability_id == storage.capability_id
    )
    target_energy_wh = limits.maximum_soc * storage.usable_capacity_wh
    if action_primitive is ExecutionPrimitive.DISCHARGE_AT_POWER:
        route = next(
            (
                item
                for item in (market.scenario_evidence if market is not None else ())
                if item.scenario.value == "lower"
            ),
            None,
        )
        target_energy_wh = (
            max(
                limits.minimum_soc * storage.usable_capacity_wh,
                route.storage_energy_at_horizon_end_wh,
            )
            if route is not None
            else limits.minimum_soc * storage.usable_capacity_wh
        )
    storage_energy_checkpoints = _committed_storage_energy_checkpoints(
        plan=plan,
        schedule=schedule,
        market=market,
        projected_result=projected_result,
    )
    household_load_intervals = tuple(
        CommittedHouseholdLoadInterval(
            interval_id=interval.interval_id,
            starts_at=interval.starts_at,
            ends_at=interval.ends_at,
            expected_energy_wh=interval.expected_energy_wh,
            confidence=interval.confidence,
            source_reference=interval.source_reference,
            method_version=interval.method_version,
        )
        for interval in (
            snapshot.household_load_forecast.intervals
            if snapshot.household_load_forecast is not None
            else ()
        )
        if interval.starts_at >= snapshot.captured_at
        and interval.ends_at <= coalesced_segments[-1][1]
    )
    if not household_load_intervals or not storage_energy_checkpoints:
        raise ValueError(
            "an admitted plan requires committed household-load and storage-energy "
            "materiality baselines"
        )
    pv_preservation_dates: tuple[date, ...] = ()
    if preserve_pv_during_grid_charge:
        preservation_dates = {
            interval.starts_at.date()
            for interval in schedule.intervals
            if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
        }
        if prior_commitment is not None:
            preservation_dates.update(
                active_pv_preservation_dates(
                    prior_commitment,
                    captured_at=snapshot.captured_at,
                )
            )
        pv_preservation_dates = tuple(sorted(preservation_dates))
    store.save(
        ActivePlanCommitment(
            execution_scope_id=storage.execution_scope_id,
            plan_id=plan_id,
            plan_revision=(
                prior_commitment.plan_revision + 1 if prior_commitment is not None else 1
            ),
            primitive=primitive.value,
            source_policy=(source_policy.value if source_policy is not None else "not_applicable"),
            starts_at=starts_at,
            # A market commitment owns its complete lifecycle.  Expiring it at
            # the end of the first charge phase silently discards a later
            # export phase.
            ends_at=coalesced_segments[-1][1],
            target_energy_wh=target_energy_wh,
            selection_method_version=COMMITMENT_METHOD_VERSION,
            planner_id="mep",
            schedule_id=schedule.schedule_id,
            worst_case_financial_result_eur=(
                market.worst_case_incremental_result_eur
                if market is not None
                else (native.worst_case_financial_result_eur if native is not None else None)
            ),
            average_charge_window_price_eur_per_kwh=(
                native.average_charge_window_price_eur_per_kwh if native is not None else None
            ),
            minimum_confidence=(native.minimum_confidence if native is not None else None),
            reserve_respected_across_scenarios=(
                native.reserve_respected_across_scenarios
                if native is not None
                else all(item.reserve_respected for item in market.scenario_evidence)
                if market is not None
                else None
            ),
            target_held_across_scenarios=(
                native.target_held_across_scenarios
                if native is not None
                else all(item.target_held_at_horizon_end for item in market.scenario_evidence)
                if market is not None
                else None
            ),
            minimum_storage_energy_at_horizon_end_wh=(
                min(item.storage_energy_at_horizon_end_wh for item in native.scenario_outcomes)
                if native is not None
                else min(item.storage_energy_at_horizon_end_wh for item in market.scenario_evidence)
                if market is not None
                else None
            ),
            segments=_committed_execution_segments(execution_segments),
            selection_reason=selection_reason,
            replaced_plan_id=(prior_commitment.plan_id if prior_commitment is not None else None),
            selected_at=snapshot.captured_at,
            household_load_intervals=household_load_intervals,
            storage_energy_checkpoints=storage_energy_checkpoints,
            candidate_family=(
                candidate_family
                if candidate_family is not None
                else "market_route"
                if market is not None
                else native.family.value
                if native is not None
                else "unknown"
            ),
            pv_preservation_dates=pv_preservation_dates,
        )
    )


def build_mep_canonical_run(
    *,
    snapshot: PlanningInputSnapshot,
    opportunities: OpportunitySet,
    planner_runtime: MarketDailyPlannerRuntime,
    commitment_store: ActivePlanCommitmentStore | None,
    control_change_allowed: bool,
    switching_margin_eur: float,
    planning_checkpoint: Callable[[], None] | None = None,
) -> tuple[CanonicalPipelineRun, MepCanonicalStageTimings, MarketDailyRuntimeOutcome | None]:
    if snapshot.daily_charge_context is not None:
        return _build_daily_main_run(
            snapshot=snapshot,
            opportunities=opportunities,
            planner_runtime=planner_runtime,
            commitment_store=commitment_store,
            control_change_allowed=control_change_allowed,
            planning_checkpoint=planning_checkpoint,
        )
    retained_commitment = next(iter(snapshot.active_plan_commitments), None)
    if retained_commitment is not None:
        completed_revision = _complete_acquisition_revision(
            snapshot=snapshot,
            commitment=retained_commitment,
        )
        if completed_revision is not None:
            retained_commitment = completed_revision
            if commitment_store is not None:
                commitment_store.save(completed_revision)
    if retained_commitment is not None and _commitment_target_reached(
        snapshot,
        retained_commitment,
    ):
        if commitment_store is not None:
            commitment_store.clear(retained_commitment.execution_scope_id)
        retained_commitment = None
    snapshot = replace(
        snapshot,
        active_plan_commitments=((retained_commitment,) if retained_commitment is not None else ()),
    )

    stage_started = perf_counter()
    planner_outcome = planner_runtime.generate(
        snapshot,
        opportunities=opportunities,
        comparison_horizon_end=None,
    )
    comparable = None
    if planner_outcome.portfolio is not None:
        try:
            conversion_model, _ = planner_runtime.planning_configuration(snapshot)
            comparable = produce_mep_comparable_portfolio(
                snapshot=snapshot,
                portfolio=planner_outcome.portfolio,
                conversion_model=conversion_model,
                incumbent=retained_commitment,
                financial_equivalence_margin_eur=switching_margin_eur,
            )
        except Exception as exc:
            planner_outcome = replace(
                planner_outcome,
                status="blocked",
                reason=str(exc) or exc.__class__.__name__,
                portfolio=None,
            )
    if comparable is None:
        candidates: list[Candidate] = []
        paths: list[EnergyPath] = []
        winner_id: str | None = None
        selected_schedule = None
        native_winner = None
        market_winner = None
        selected_projected_result = None
        selected_prefix_composed = False
    else:
        candidates = [
            Candidate(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                candidate_id=item.candidate_id,
                energy_path_id=item.energy_path_id,
                family=item.family.value,
                pv_forecast_basis="confidence-weighted-lower-central",
            )
            for item in comparable.candidate_set.candidates
        ]
        paths = [
            EnergyPath(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                path_id=item.path_id,
                family=item.family.value,
                segment_ids=tuple(segment.segment_id for segment in item.segments),
                segments=item.segments,
                projected_states=item.projected_states,
                capability_confidence=item.confidence,
            )
            for item in comparable.candidate_set.energy_paths
        ]
        selected_schedule = None
        native_winner = None
        market_winner = None
        selected_projected_result = None
        selected_prefix_composed = False
    candidate_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    canonical_evaluation = (
        EvaluationEngine().evaluate(
            comparable.candidate_set,
            comparable.strategy,
            comparable.outcome_set,
            created_at=snapshot.captured_at,
            incumbent_candidate_id=comparable.incumbent_candidate_id,
            financial_equivalence_margin=switching_margin_eur,
        )
        if comparable is not None
        else None
    )
    winner_id = (
        canonical_evaluation.record.winning_candidate_id
        if canonical_evaluation is not None
        else None
    )
    incumbent_retained = (
        comparable is not None
        and comparable.incumbent_candidate_id is not None
        and winner_id == comparable.incumbent_candidate_id
    )
    replacement_reason = (
        canonical_evaluation.record.decisive_step
        if canonical_evaluation is not None
        and comparable is not None
        and comparable.incumbent_candidate_id is not None
        and not incumbent_retained
        else None
    )
    if comparable is not None and winner_id is not None:
        source = next(item for item in comparable.sources if item.candidate_id == winner_id)
        selected_schedule = source.schedule
        native_winner = source.native_candidate
        market_winner = source.market_assessment
        selected_projected_result = source.projected_result
        selected_prefix_composed = source.committed_prefix_composed
    winner = next((item for item in candidates if item.candidate_id == winner_id), None)
    winning_path = next(
        (item for item in paths if winner is not None and item.path_id == winner.energy_path_id),
        None,
    )
    candidate_set = CandidateSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=_id("mep-candidate-set", opportunities.opportunity_set_id),
        candidates=tuple(candidates),
        energy_paths=tuple(paths),
        projected_balances=((comparable.projected_balance,) if comparable is not None else ()),
        storage_requirements=((comparable.storage_requirement,) if comparable is not None else ()),
        derivation_status=("ready" if winner is not None else "blocked"),
        derivation_reason=(None if winner is not None else planner_outcome.reason),
    )
    outcomes = CandidateOutcomeSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=candidate_set.candidate_set_id,
        outcome_set_id=_id("mep-outcome-set", candidate_set.candidate_set_id),
        candidate_ids=tuple(item.candidate_id for item in candidates),
        outcomes=(comparable.diagnostic_outcomes if comparable is not None else ()),
    )
    decisive_step = (
        canonical_evaluation.record.decisive_step
        if canonical_evaluation is not None
        else "fallback:mep_planning_blocked"
    )
    evaluation = EvaluationRecord(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        evaluation_id=(
            canonical_evaluation.record.evaluation_id
            if canonical_evaluation is not None
            else _id("mep-evaluation", outcomes.outcome_set_id)
        ),
        candidate_set_id=candidate_set.candidate_set_id,
        winning_candidate_id=(winner.candidate_id if winner is not None else None),
        winning_energy_path_id=(winning_path.path_id if winning_path is not None else None),
        reason=(
            "active canonical MEP plan commitment retained"
            if incumbent_retained
            else decisive_step or "evaluation:winner_selected"
            if winner is not None
            else planner_outcome.reason or "mep_planning_blocked"
        ),
        status=("winner_selected" if winner is not None else "fallback_active"),
        evaluated_candidate_ids=(
            canonical_evaluation.record.evaluated_candidate_ids
            if canonical_evaluation is not None
            else ()
        ),
        decisive_step=decisive_step,
        incumbent_candidate_id=(
            comparable.incumbent_candidate_id if comparable is not None else None
        ),
        financial_equivalence_margin_eur=switching_margin_eur,
        commitment_decision=(
            "retained"
            if incumbent_retained
            else "replaced"
            if comparable is not None and comparable.incumbent_candidate_id is not None
            else "not_applicable"
        ),
    )
    evaluation_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    canonical_plan_set = (
        ExecutionPlanBuilder().build(
            canonical_evaluation,
            created_at=snapshot.captured_at,
            fallback_policy_id="mep-safe-fallback:v1",
        )
        if canonical_evaluation is not None and canonical_evaluation.winning_energy_path is not None
        else None
    )
    admitted_plan_ids_by_scope = (
        {retained_commitment.execution_scope_id: retained_commitment.plan_id}
        if incumbent_retained and retained_commitment is not None
        else {}
    )
    if canonical_plan_set is not None:
        execution_plan_set = project_execution_plan_set(
            canonical_plan_set,
            run_id=snapshot.run_id,
            captured_at=snapshot.captured_at,
            observer_only=not control_change_allowed,
            admitted_plan_ids_by_scope=admitted_plan_ids_by_scope,
        )
    else:
        execution_plan_set = ExecutionPlanSet(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            plan_set_id=_id("mep-plan-set", evaluation.evaluation_id),
            evaluation_id=evaluation.evaluation_id,
            winning_energy_path_id=evaluation.winning_energy_path_id,
        )
    plans = list(execution_plan_set.plans)
    if plans:
        if winning_path is None:
            raise ValueError("an executable plan requires its winning Energy Path")
        plan_id = plans[0].plan_id
        if (
            not incumbent_retained
            and selected_schedule is not None
            and planner_outcome.portfolio is not None
        ):
            _persist_plan(
                store=commitment_store,
                snapshot=snapshot,
                plan=planner_outcome.portfolio,
                schedule=selected_schedule,
                execution_segments=winning_path.segments,
                plan_id=plan_id,
                native=(None if selected_prefix_composed else native_winner),
                market=(None if selected_prefix_composed else market_winner),
                projected_result=(selected_projected_result if selected_prefix_composed else None),
                candidate_family=(
                    "market_route"
                    if market_winner is not None
                    else native_winner.family.value
                    if native_winner is not None
                    else None
                ),
                prior_commitment=(retained_commitment if replacement_reason is not None else None),
                preserve_pv_during_grid_charge=(
                    planner_outcome.portfolio.preserve_pv_during_grid_charge
                ),
                selection_reason=(
                    evaluation.decisive_step or "objective:mep_physical_and_market_evaluation"
                ),
            )
    execution_plan_builder_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    run, timings = _finish_mep_run(
        snapshot=snapshot,
        opportunities=opportunities,
        candidate_set=candidate_set,
        outcomes=outcomes,
        evaluation=evaluation,
        execution_plan_set=execution_plan_set,
        winning_path=winning_path,
        commitment_store=commitment_store,
        control_change_allowed=control_change_allowed,
        legacy_revisions=True,
        candidate_engine_ms=candidate_engine_ms,
        evaluation_engine_ms=evaluation_engine_ms,
        execution_plan_builder_ms=execution_plan_builder_ms,
    )
    return run, timings, planner_outcome


def _finish_mep_run(
    *,
    snapshot: PlanningInputSnapshot,
    opportunities: OpportunitySet,
    candidate_set: CandidateSet,
    outcomes: CandidateOutcomeSet,
    evaluation: EvaluationRecord,
    execution_plan_set: ExecutionPlanSet,
    winning_path: EnergyPath | None,
    commitment_store: ActivePlanCommitmentStore | None,
    control_change_allowed: bool,
    legacy_revisions: bool,
    nom_fallback: bool = False,
    candidate_engine_ms: float,
    evaluation_engine_ms: float,
    execution_plan_builder_ms: float,
) -> tuple[CanonicalPipelineRun, MepCanonicalStageTimings]:
    """Shared execution boundary; daily ownership never uses legacy PV revisions."""
    plans = list(execution_plan_set.plans)
    stage_started = perf_counter()
    execution_record = ExecutionRecord(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        execution_record_id=_id("mep-execution", execution_plan_set.plan_set_id),
        plan_set_id=execution_plan_set.plan_set_id,
        status=(
            "live_fallback_ready"
            if nom_fallback and control_change_allowed
            else "observer_fallback_ready"
            if nom_fallback
            else "live_plan_ready"
            if plans and control_change_allowed
            else "observer_only_plan_ready"
            if plans
            else "fallback_active"
        ),
        reason=(evaluation.reason if plans else "no executable MEP plan"),
    )
    execution_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    due_segment = next(
        (
            segment
            for plan in plans
            for segment in plan.segments
            if segment.starts_at <= snapshot.captured_at < segment.ends_at
        ),
        None,
    )
    if nom_fallback:
        due_segment = None
    due_path_segment = next(
        (
            item
            for item in (winning_path.segments if winning_path is not None else ())
            if due_segment is not None and item.segment_id == due_segment.source_path_segment_id
        ),
        None,
    )
    mode_evidence = snapshot.storage_mode_capability_evidence
    provenance = snapshot.storage_mode_control_provenance
    blockers: list[str] = []
    pv_charge_progress = None
    if due_segment is not None or nom_fallback:
        if mode_evidence is None or mode_evidence.current_vendor_mode is None:
            blockers.append("storage_mode_capability_evidence_unavailable")
        if (
            snapshot.bms_calibration_evidence is not None
            and snapshot.bms_calibration_evidence.active
        ):
            blockers.append("bms_soc_calibration_active")
        if provenance is None:
            blockers.append("manual_override_provenance_unverified")
        elif provenance.manual_override_active:
            blockers.append("manual_override_active")
        if legacy_revisions and winning_path is not None and due_path_segment is not None:
            pv_charge_progress = _pv_charge_progress_evidence(
                snapshot=snapshot,
                path=winning_path,
                due_segment=due_path_segment,
            )
        if pv_charge_progress is not None and pv_charge_progress.decision == "defer_grid_charge":
            blockers.append("measured_pv_progress_covers_grid_charge")
        if not control_change_allowed:
            blockers.append("observer_only_authority")
    request_ready = (due_segment is not None or nom_fallback) and blockers in (
        [],
        ["observer_only_authority"],
    )
    measured_progress_deferred = blockers == ["measured_pv_progress_covers_grid_charge"]
    request_id = (
        _id(
            "mep-primitive-request",
            f"{execution_record.execution_record_id}|"
            f"{due_segment.segment_id if due_segment is not None else 'guarded-nom'}",
        )
        if request_ready
        else None
    )
    primitive_boundary = ExecutionPrimitiveBoundary(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        request_id=request_id,
        execution_record_id=execution_record.execution_record_id,
        status=(
            "request_ready"
            if request_ready and control_change_allowed
            else "observer_request_ready"
            if request_ready
            else "execution_deferred"
            if measured_progress_deferred
            else "dry_run_blocked"
            if due_segment is not None or nom_fallback
            else "not_emitted"
        ),
        planned_primitive=(
            ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            if nom_fallback
            else due_segment.primitive
            if due_segment is not None
            else None
        ),
        mapping_status=("pending_adapter" if request_id is not None else "not_requested"),
        source_entity_id=(mode_evidence.source_entity_id if mode_evidence is not None else None),
        current_vendor_mode=(
            mode_evidence.current_vendor_mode if mode_evidence is not None else None
        ),
        planned_vendor_mode=None,
        mapping_method_version=(
            mode_evidence.method_version if mode_evidence is not None else None
        ),
        blockers=tuple(blockers),
        pv_charge_progress=pv_charge_progress,
    )
    if measured_progress_deferred and commitment_store is not None and due_path_segment is not None:
        active_commitment = commitment_store.load(due_path_segment.execution_scope_id)
        if active_commitment is not None:
            deferred_revision = _defer_charge_revision(
                snapshot=snapshot,
                commitment=active_commitment,
            )
            if deferred_revision is not None:
                commitment_store.save(deferred_revision)
    execution_primitive_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    adapter_boundary = DeviceAdapterBoundary(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        translation_id=None,
        primitive_request_id=None,
        status="not_invoked",
    )
    device_adapter_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    vendor_result = VendorBoundaryResult(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        command_id=None,
        adapter_translation_id=None,
        status="not_dispatched",
        dispatch_intent_id=None,
        target_entity_id=None,
        planned_vendor_mode=None,
    )
    vendor_result_ms = round((perf_counter() - stage_started) * 1000.0, 3)
    return (
        CanonicalPipelineRun(
            planning_input=snapshot,
            opportunities=opportunities,
            candidate_set=candidate_set,
            outcomes=outcomes,
            evaluation=evaluation,
            execution_plan_set=execution_plan_set,
            execution_record=execution_record,
            primitive_boundary=primitive_boundary,
            adapter_boundary=adapter_boundary,
            vendor_result=vendor_result,
        ),
        MepCanonicalStageTimings(
            candidate_engine_ms=candidate_engine_ms,
            evaluation_engine_ms=evaluation_engine_ms,
            execution_plan_builder_ms=execution_plan_builder_ms,
            execution_engine_ms=execution_engine_ms,
            execution_primitive_ms=execution_primitive_ms,
            device_adapter_ms=device_adapter_ms,
            vendor_result_ms=vendor_result_ms,
        ),
    )


def _build_daily_main_run(
    *,
    snapshot: PlanningInputSnapshot,
    opportunities: OpportunitySet,
    planner_runtime: MarketDailyPlannerRuntime,
    commitment_store: ActivePlanCommitmentStore | None,
    control_change_allowed: bool,
    planning_checkpoint: Callable[[], None] | None = None,
) -> tuple[CanonicalPipelineRun, MepCanonicalStageTimings, None]:
    """Select only an unbound daily goal; retain a bound route without repricing.

    The live input always supplies daily context. Legacy snapshots without this
    context remain readable by the historical replay entry point above.
    """
    context = snapshot.daily_charge_context
    assert context is not None
    started = perf_counter()
    comparable = None
    result = None
    reason = "daily_main_route_retained_without_optimisation_trigger"
    selected_window = None
    optimisation_trigger: (
        DailyMainShortfallTrigger | DailyMainPVSurplusTrigger | DailyBridgeTrigger | None
    ) = None
    pv_comparison = None
    bridge_assessment = None
    input_shortfalls: tuple[DailyMainShortfallTrigger, ...] = ()
    canonical_set = None
    planning_blocked = False
    optional_pv_review = False
    retained = tuple(
        p
        for p in context.main_plans
        if p.plan_id in context.active_main_plan_ids
        and p.valid_from <= snapshot.captured_at < p.valid_until
    )
    try:
        if context.status != "ready":
            raise ValueError(context.reason or "daily_charge_recovery_blocked")
        if commitment_store is None:
            raise ValueError("daily_charge_store_unavailable")
        if (
            not snapshot.price_points
            or snapshot.pv_energy_timeline is None
            or (snapshot.household_load_forecast is None or not snapshot.current_storage_states)
        ):
            raise ValueError("daily_main_planning_data_unavailable")
        pending = sorted(
            (
                a
                for a in context.assignments
                if a.route_plan_id is None
                and a.completed_at is None
                and a.ends_at > snapshot.captured_at
            ),
            key=lambda a: (a.delivery_date, a.execution_scope_id),
        )
        conversion, market_policy = planner_runtime.planning_configuration(snapshot)
        adapter = IndependentDailyReferenceAdapter()
        triggers = adapter.main_route_shortfalls(
            snapshot=snapshot, conversion_model=conversion,
        ) if context.active_main_plan_ids else ()
        input_shortfalls = triggers
        triggers = tuple(t for t in triggers if adapter.main_repair_required(
            snapshot=snapshot, trigger=t, conversion_model=conversion,
        ))
        if triggers:
            owners = {a.assignment_id: a for a in context.assignments}
            optimisation_trigger = min(triggers, key=lambda t: (
                owners[t.assignment_id].delivery_date, owners[t.assignment_id].execution_scope_id,
                t.assignment_id,
            ))
            pending = [next(a for a in context.assignments
                            if a.assignment_id == optimisation_trigger.assignment_id)]
        if not triggers:
            optional_pv_review = bool(retained) and not pending
            for state in context.pv_comparison_states:
                owner = next(
                    a for a in context.assignments if a.assignment_id == state.assignment_id
                )
                if state.basis is None or owner.completed_at is not None or (
                    owner.ends_at <= snapshot.captured_at
                ):
                    continue
                pv_comparison = compare_daily_pv(
                    state.basis, snapshot.pv_energy_timeline, at=snapshot.captured_at,
                )
                # A changed stored energy can make charging removable even with
                # unchanged closed PV observations. Poll time is not new evidence.
                storage_basis = tuple(
                    (s.execution_scope_id, s.current_soc, s.usable_capacity_wh)
                    for s in snapshot.current_storage_states
                    if s.execution_scope_id == owner.execution_scope_id
                )
                pv_comparison = replace(
                    pv_comparison, evidence_id="grid-review:" + sha256(
                        repr((pv_comparison.evidence_id, storage_basis,
                              (snapshot.household_load_guard.active,
                               snapshot.household_load_guard.quality,
                               snapshot.household_load_guard.extra_power_w)
                              if snapshot.household_load_guard is not None else None)).encode()
                    ).hexdigest(),
                )
                if pv_comparison.status != "complete" or (
                    pv_comparison.evidence_id in state.assessed_evidence_ids
                ):
                    continue
                surplus = adapter.pv_surplus_trigger(
                    snapshot=snapshot, assignment=owner, comparison=pv_comparison,
                    conversion_model=conversion,
                )
                if surplus is not None:
                    optimisation_trigger = surplus
                    pending = [owner]
                    break
                commitment_store.record_daily_pv_assessment(
                    assignment_id=owner.assignment_id, basis_id=state.basis.basis_id,
                    evidence_id=pv_comparison.evidence_id, outcome="no_route_change",
                )
        if not pending and optimisation_trigger is None and retained:
            bridge_assessment = adapter.bridge_assessment(
                snapshot=snapshot, conversion_model=conversion,
            )
            if bridge_assessment.trigger is not None:
                optimisation_trigger = bridge_assessment.trigger
                pending = [next(a for a in context.assignments
                                if a.assignment_id == optimisation_trigger.assignment_id)]
        if pending:
            optional_pv_review = isinstance(optimisation_trigger, DailyMainPVSurplusTrigger)
            if isinstance(optimisation_trigger, DailyBridgeTrigger):
                windows = adapter.bridge_windows(
                    snapshot=snapshot, trigger=optimisation_trigger, conversion_model=conversion,
                )
            else:
                windows = adapter.main_charge_windows(
                    snapshot=snapshot, assignment=pending[0], conversion_model=conversion,
                    optimisation_trigger=optimisation_trigger,
                )
            if not windows.windows:
                if isinstance(optimisation_trigger, DailyMainPVSurplusTrigger):
                    commitment_store.record_daily_pv_assessment(
                        assignment_id=optimisation_trigger.assignment_id,
                        basis_id=optimisation_trigger.basis_id,
                        evidence_id=optimisation_trigger.comparison_evidence_id,
                        outcome="no_admissible_grid_reduction",
                    )
                    reason = windows.reason or "pv_comparison_retains_main_route"
                elif (
                    windows.reason == "ongoing_load_requires_committed_grid_continuity" and retained
                ):
                    # No replacement was admitted. Keep the already admitted
                    # charging action until its own end, with the shortfall
                    # still visible; NOM fallback would defeat this protection.
                    reason = windows.reason
                else:
                    raise ValueError(windows.reason or "daily_main_no_feasible_window")
            else:
                tariffs = IndependentDailyTariffAdapter().build(
                    snapshot, horizon_end=windows.windows[0].schedule.horizon_end,
                )
                comparable = produce_main_charge_portfolio(
                    snapshot=snapshot, windows=windows, tariffs=tariffs,
                    opportunity_ids=opportunities.opportunity_ids,
                )
        elif not retained:
            raise ValueError("daily_main_active_plan_unavailable")
    except (ValueError, OSError) as exc:
        planning_blocked = not optional_pv_review
        reason = str(exc) or exc.__class__.__name__
    candidate_ms = round((perf_counter() - started) * 1000, 3)
    started = perf_counter()
    if comparable is not None:
        # EUR/kWh-stored: deliberately no legacy EUR switching margin/incumbent.
        result = EvaluationEngine().evaluate(
            comparable.candidate_set,
            comparable.strategy,
            comparable.outcome_set,
            created_at=snapshot.captured_at,
        )
        if result.winning_energy_path is not None:
            selected_window = next(
                s.window
                for s in comparable.sources
                if s.candidate_id == result.record.winning_candidate_id
            )
            reason = result.record.decisive_step or "daily_main_winner_selected"
        else:
            planning_blocked = not isinstance(optimisation_trigger, DailyMainPVSurplusTrigger)
            reason = "daily_main_evaluation_has_no_winner"
            if isinstance(optimisation_trigger, DailyMainPVSurplusTrigger):
                assert commitment_store is not None
                try:
                    commitment_store.record_daily_pv_assessment(
                        assignment_id=optimisation_trigger.assignment_id,
                        basis_id=optimisation_trigger.basis_id,
                        evidence_id=optimisation_trigger.comparison_evidence_id,
                        outcome="no_valid_grid_reduction_candidate",
                    )
                except (ValueError, OSError) as exc:
                    reason = str(exc) or exc.__class__.__name__
    evaluation_ms = round((perf_counter() - started) * 1000, 3)
    started = perf_counter()
    if selected_window is not None and result is not None:
        assert commitment_store is not None
        try:
            if planning_checkpoint is not None:
                planning_checkpoint()
            proposed = ExecutionPlanBuilder().build(
                result,
                created_at=snapshot.captured_at,
                fallback_policy_id="guarded-nom",
            )
            if len(proposed.plans) != 1:
                raise ValueError("daily_main_requires_single_storage_scope")
            selected_owner = next(a for a in context.assignments
                                  if a.assignment_id == selected_window.assignment_id)
            pv_basis = DailyPVComparisonBasis.capture(snapshot, selected_owner) if (
                selected_owner.revision == 0
            ) else None
            commitment_store.bind_daily_main_plan(
                plan=proposed.plans[0],
                window=selected_window,
                activate=True,
                optimisation_trigger=optimisation_trigger,
                pv_comparison_basis=pv_basis,
                bridge_deficits=energy_deficits(
                    selected_window.projection, selected_window.schedule,
                    until=optimisation_trigger.next_starts_at,
                    maximum_discharge_output_power_w=next(
                        limit.maximum_discharge_output_power_w
                        for limit in snapshot.storage_physical_limits
                        if limit.execution_scope_id == selected_owner.execution_scope_id
                    ),
                ) if isinstance(optimisation_trigger, DailyBridgeTrigger) else (),
            )
            canonical_set = proposed
        except (ValueError, OSError) as exc:
            planning_blocked = not isinstance(optimisation_trigger, DailyMainPVSurplusTrigger)
            reason = str(exc) or exc.__class__.__name__
    if (
        not planning_blocked
        and canonical_set is None
        and len(retained) == 1
        and snapshot.market_user_rule is not None
        and commitment_store is not None
    ):
        try:
            incumbent = retained[0]
            assigned = {b.assignment_id for b in commitment_store.load_market_plan_bindings()}
            for day in sorted(context.assignments, key=lambda a: a.delivery_date):
                if (
                    day.execution_scope_id != incumbent.execution_scope_id
                    or day.ends_at <= snapshot.captured_at
                ):
                    continue
                market_day = commitment_store.ensure_market_daily_assignment(
                    MarketDailyAssignment(
                        snapshot.market_user_rule,
                        day.execution_scope_id,
                        day.delivery_date,
                        day.timezone,
                        snapshot.captured_at,
                        snapshot.current_storage_states[0].usable_capacity_wh,
                    )
                )
                if market_day.status != "pending" or market_day.assignment_id in assigned:
                    continue
                try:
                    market = market_rule_portfolio(
                        planning_checkpoint=planning_checkpoint,
                        snapshot=snapshot,
                        plan=incumbent,
                        assignment=market_day,
                        conversion=conversion,
                        opportunity_ids=opportunities.opportunity_ids,
                        wear_eur_per_export_kwh=market_policy.wear_eur_per_export_kwh,
                        saldering_energy_tax_credit_enabled=market_policy.saldering_energy_tax_credit_enabled,
                    )
                    if not market.comparable.candidate_set.candidates:
                        reason = "market_not_admitted:" + ",".join(market.reasons)
                        continue
                    market_result = EvaluationEngine().evaluate(
                        market.comparable.candidate_set,
                        market.comparable.strategy,
                        market.comparable.outcome_set,
                        created_at=snapshot.captured_at,
                    )
                    if market_result.winning_energy_path is None:
                        reason = "market_evaluation_has_no_winner"
                        continue
                    market_plans = ExecutionPlanBuilder().build(
                        market_result,
                        created_at=snapshot.captured_at,
                        fallback_policy_id="guarded-nom",
                    )
                    source = next(
                        e
                        for e in market.evidence
                        if e.candidate_id == market_result.record.winning_candidate_id
                    )
                    market_plan = market_plans.plans[0]
                    energy = dict(source.segment_energy)
                    bound_parts = tuple(
                        s for s in market_plan.segments if s.source_path_segment_id in energy
                    )
                    binding = MarketPlanBinding(
                        market_day.assignment_id,
                        market_day.execution_scope_id,
                        market_plan.plan_id,
                        market_plan.snapshot_id,
                        tuple(s.segment_id for s in bound_parts),
                        source.admission.expected_export_wh,
                        tuple(energy[s.source_path_segment_id] for s in bound_parts),
                        source.expected_battery_draw_wh,
                    )
                    if planning_checkpoint is not None:
                        planning_checkpoint()
                    if source.charge_window is not None:
                        optimisation_trigger = source.charge_trigger
                        commitment_store.bind_daily_main_plan(
                            plan=market_plan,
                            window=source.charge_window,
                            activate=True,
                            optimisation_trigger=source.charge_trigger,
                            market_binding=binding,
                            market_admission=source.admission,
                        )
                    else:
                        commitment_store.bind_market_plan(
                            plan=market_plan,
                            previous_plan_id=incumbent.plan_id,
                            binding=binding,
                            admission=source.admission,
                        )
                    comparable, result, canonical_set = (
                        market.comparable,
                        market_result,
                        market_plans,
                    )
                    reason = "user_market_rule_selected"
                    break
                except (ValueError, OSError) as exc:
                    # A rejected optional user action cannot erase the charge plan.
                    reason = "market_not_admitted:" + str(exc)
        except (ValueError, OSError) as exc:
            reason = "market_not_admitted:" + str(exc)
    candidate_set_id = _id("daily-main-candidates", snapshot.snapshot_id)
    candidates = tuple(
        Candidate(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            candidate_id=c.candidate_id,
            energy_path_id=c.energy_path_id,
            family=c.family.value,
            pv_forecast_basis="mean-lower-central",
        )
        for c in (comparable.candidate_set.candidates if comparable is not None else ())
    )
    paths = tuple(
        EnergyPath(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            path_id=p.path_id,
            family=p.family.value,
            segment_ids=tuple(s.segment_id for s in p.segments),
            segments=p.segments,
            projected_states=p.projected_states,
            capability_confidence=p.confidence,
        )
        for p in (comparable.candidate_set.energy_paths if comparable is not None else ())
    )
    evaluation_id = (
        result.record.evaluation_id
        if result is not None
        else _id("daily-main-observation", snapshot.snapshot_id)
    )
    if canonical_set is not None:
        plan_set = project_execution_plan_set(
            canonical_set,
            run_id=snapshot.run_id,
            captured_at=snapshot.captured_at,
            observer_only=not control_change_allowed,
        )
    else:
        # The observation has fresh lineage; the saved plan keeps its original
        # Evaluation and execution identities. No fictitious re-evaluation.
        plans = tuple(
            _project_plan(
                p,
                captured_at=snapshot.captured_at,
                observer_only=not control_change_allowed,
                admitted_plan_id=p.plan_id,
            )
            for p in retained
        )
        plan_set = ExecutionPlanSet(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            plan_set_id=_id("daily-main-observed-plans", snapshot.snapshot_id),
            evaluation_id=evaluation_id,
            winning_energy_path_id=None,
            plan_ids=tuple(p.plan_id for p in plans),
            plans=plans,
        )
    winner_id = result.record.winning_candidate_id if result is not None else None
    winning_path = next(
        (
            p
            for p in paths
            if result is not None
            and result.winning_energy_path is not None
            and p.path_id == result.winning_energy_path.path_id
        ),
        None,
    )
    candidate_set = CandidateSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=candidate_set_id,
        candidates=candidates,
        energy_paths=paths,
        derivation_status="ready"
        if canonical_set is not None
        else "retained"
        if retained
        else "blocked",
        derivation_reason=reason,
    )
    outcomes = CandidateOutcomeSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=candidate_set_id,
        outcome_set_id=_id("daily-main-outcomes", candidate_set_id),
        candidate_ids=tuple(c.candidate_id for c in candidates),
        canonical_outcomes=comparable.outcome_set.outcomes if comparable is not None else (),
    )
    evaluation = EvaluationRecord(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        evaluation_id=evaluation_id,
        candidate_set_id=candidate_set_id,
        winning_candidate_id=winner_id,
        winning_energy_path_id=winning_path.path_id if winning_path is not None else None,
        reason=reason,
        daily_main_shortfall=(optimisation_trigger if isinstance(
            optimisation_trigger, DailyMainShortfallTrigger,
        ) else None),
        daily_bridge=bridge_assessment,
        daily_main_input_shortfalls=input_shortfalls,
        daily_pv_comparison=pv_comparison,
        daily_pv_surplus_trigger=(optimisation_trigger if isinstance(
            optimisation_trigger, DailyMainPVSurplusTrigger,
        ) else None),
        status="fallback_active"
        if planning_blocked
        else "winner_selected"
        if canonical_set is not None
        else "plan_retained"
        if retained
        else "fallback_active",
        evaluated_candidate_ids=result.record.evaluated_candidate_ids if result is not None else (),
        decisive_step=result.record.decisive_step if result is not None else None,
        commitment_decision="triggered_revision"
        if canonical_set is not None and optimisation_trigger is not None
        else "initial_binding"
        if canonical_set is not None
        else "retained"
        if retained
        else "not_applicable",
    )
    builder_ms = round((perf_counter() - started) * 1000, 3)
    run, timings = _finish_mep_run(
        snapshot=snapshot,
        opportunities=opportunities,
        candidate_set=candidate_set,
        outcomes=outcomes,
        evaluation=evaluation,
        execution_plan_set=plan_set,
        winning_path=winning_path,
        commitment_store=commitment_store,
        control_change_allowed=control_change_allowed,
        legacy_revisions=False,
        nom_fallback=planning_blocked,
        candidate_engine_ms=candidate_ms,
        evaluation_engine_ms=evaluation_ms,
        execution_plan_builder_ms=builder_ms,
    )
    return run, timings, None
