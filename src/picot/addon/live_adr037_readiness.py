"""ADR-037 live planning readiness and typed execution handoff boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from picot.addon.live_planner_context import LiveEvidenceConfidenceTracker
from picot.domain.capability_snapshot import CapabilitySnapshotSet
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.forecast import ForecastKind
from picot.domain.opportunity import OpportunitySet
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceAssembler,
)
from picot.planner.adr037_pipeline import ADR037PlannerPipeline, ADR037PlanningResult
from picot.planner.opportunity_engine import OpportunityEngine
from picot.planner.price_opportunity_detection import PriceOpportunityDetectionConfig

PRICE_DETECTION_CONFIG_VERSION = 1


@dataclass(frozen=True, slots=True)
class LiveADR037ReadinessRun:
    """One live ADR-037 run with both presentation evidence and domain result.

    The event is diagnostic/presentation evidence. ``planning_result`` is the
    authoritative typed output of the same planner pass and is preserved for
    the ADR-033 execution handoff. This boundary does not grant execution
    authority and must not reinterpret the winner.
    """

    event: dict[str, object]
    planning_result: ADR037PlanningResult | None


def assemble_live_projected_balance(
    snapshot: PlanningInputSnapshot,
) -> ProjectedHouseholdEnergyBalance | None:
    """Assemble the canonical no-grid baseline when the live energy set is complete."""

    if (
        not snapshot.current_storage_states
        or snapshot.pv_energy_timeline is None
        or snapshot.household_load_forecast is None
    ):
        return None
    storage_state = snapshot.current_storage_states[0]
    return ProjectedHouseholdEnergyBalanceAssembler().assemble(
        balance_id=f"live-balance-{snapshot.snapshot_id}",
        captured_at=snapshot.captured_at,
        storage_state=storage_state,
        pv_timeline=snapshot.pv_energy_timeline,
        load_forecast=snapshot.household_load_forecast,
    )


def detect_live_price_opportunities(
    snapshot: PlanningInputSnapshot,
    *,
    price_margin_eur_per_kwh: float,
) -> OpportunitySet | None:
    """Detect canonical price Opportunities from this exact live snapshot only."""

    if not snapshot.forecasts.by_kind(ForecastKind.ENERGY_PRICE):
        return None
    config = PriceOpportunityDetectionConfig(
        config_version=PRICE_DETECTION_CONFIG_VERSION,
        low_price_margin_eur_per_kwh=price_margin_eur_per_kwh,
        high_price_margin_eur_per_kwh=price_margin_eur_per_kwh,
    )
    return OpportunityEngine().detect(snapshot, price_config=config)


def _context_value(
    planner_context: Mapping[str, object] | None,
    key: str,
) -> object | None:
    return planner_context.get(key) if planner_context is not None else None


def run_adr037_readiness(
    snapshot: PlanningInputSnapshot,
    *,
    capabilities: CapabilitySnapshotSet | None = None,
    effective_limit: EffectiveStorageLimit | None = None,
    confidence_tracker: LiveEvidenceConfidenceTracker | None = None,
    planner_context: Mapping[str, object] | None = None,
    price_margin_eur_per_kwh: float = 0.04,
) -> LiveADR037ReadinessRun:
    """Run live ADR-037 once and preserve its typed result without execution authority."""

    balance = assemble_live_projected_balance(snapshot)
    blockers: list[str] = []
    if balance is None:
        blockers.append("incomplete_energy_input_set")

    storage_capability = None
    if capabilities is not None:
        storage_capability = next(
            (
                item
                for item in capabilities.capabilities
                if item.execution_scope_id == "storage-primary"
            ),
            None,
        )
    if storage_capability is None:
        blockers.append("live_storage_capability_snapshot_unavailable")
    if effective_limit is None:
        blockers.append("live_effective_storage_limit_unwired")

    confidence_assessment = None
    if balance is not None and confidence_tracker is not None:
        confidence_assessment = confidence_tracker.assess(
            balance=balance,
            snapshot=snapshot,
        )
    if confidence_assessment is None:
        blockers.append("live_evidence_confidence_assessment_unwired")

    opportunities = detect_live_price_opportunities(
        snapshot,
        price_margin_eur_per_kwh=price_margin_eur_per_kwh,
    )
    if opportunities is None:
        blockers.append("authoritative_live_price_forecast_unavailable")

    planning_result = None
    if (
        not blockers
        and balance is not None
        and effective_limit is not None
        and confidence_assessment is not None
        and storage_capability is not None
        and opportunities is not None
        and capabilities is not None
        and snapshot.current_storage_states
    ):
        planning_result = ADR037PlannerPipeline().run(
            requirement_id=f"live-storage-requirement:{snapshot.snapshot_id}",
            evaluated_at=snapshot.captured_at,
            snapshot=snapshot,
            balance=balance,
            effective_limit=effective_limit,
            confidence_assessment=confidence_assessment,
            storage_state=snapshot.current_storage_states[0],
            storage_capability=storage_capability,
            opportunities=opportunities,
            capabilities=capabilities,
        )

    winner = (
        planning_result.evaluation.winning_candidate
        if planning_result is not None
        else None
    )
    storage_state = (
        snapshot.current_storage_states[0]
        if snapshot.current_storage_states
        else None
    )
    live_min_soc = _context_value(
        planner_context,
        "zendure_allowed_min_soc_percent",
    )
    live_max_soc = _context_value(
        planner_context,
        "zendure_allowed_max_soc_percent",
    )
    operating_window_wh = None
    if (
        isinstance(live_min_soc, (int, float))
        and not isinstance(live_min_soc, bool)
        and isinstance(live_max_soc, (int, float))
        and not isinstance(live_max_soc, bool)
        and storage_state is not None
    ):
        operating_window_wh = max(
            0.0,
            storage_state.usable_capacity_wh
            * (float(live_max_soc) - float(live_min_soc))
            / 100.0,
        )

    recoverability = (
        planning_result.technical_recoverability
        if planning_result is not None
        else None
    )
    remaining_charge_wh = (
        recoverability.extra_energy_required_wh
        if recoverability is not None
        else None
    )
    latest_charge_start = (
        recoverability.latest_full_power_charge_start
        if recoverability is not None
        else None
    )
    acquisition_required = (
        recoverability.additional_acquisition_required
        if recoverability is not None
        else None
    )
    recovery_start_due = (
        acquisition_required is True
        and latest_charge_start is not None
        and snapshot.captured_at >= latest_charge_start
    )
    requirement = (
        planning_result.requirement if planning_result is not None else None
    )

    event: dict[str, object] = {
        "event": "picot_live_adr037_readiness",
        "layer": "planner",
        "snapshot_id": snapshot.snapshot_id,
        "captured_at": snapshot.captured_at.isoformat(),
        "projected_balance_available": balance is not None,
        "projected_balance_id": (
            balance.balance_id if balance is not None else None
        ),
        "projected_balance_confidence": (
            balance.confidence if balance is not None else None
        ),
        "projected_balance_end_energy_wh": (
            balance.points[-1].projected_storage_energy_wh
            if balance is not None
            else None
        ),
        "projected_balance_cumulative_pv_wh": (
            balance.points[-1].cumulative_pv_energy_wh
            if balance is not None
            else None
        ),
        "projected_balance_cumulative_household_load_wh": (
            balance.points[-1].cumulative_household_load_wh
            if balance is not None
            else None
        ),
        "storage_capability_available": storage_capability is not None,
        "storage_max_charge_power_w": (
            storage_capability.maximum_power_w
            if storage_capability is not None
            else None
        ),
        "current_storage_soc": (
            storage_state.current_soc if storage_state is not None else None
        ),
        "current_storage_energy_wh": (
            storage_state.current_stored_energy_wh
            if storage_state is not None
            else None
        ),
        "live_storage_min_soc_percent": live_min_soc,
        "live_storage_max_soc_percent": live_max_soc,
        "live_storage_operating_window_wh": operating_window_wh,
        "effective_storage_limit_available": effective_limit is not None,
        "effective_storage_max_soc": (
            effective_limit.max_soc if effective_limit else None
        ),
        "effective_storage_max_energy_wh": (
            effective_limit.max_energy_wh if effective_limit else None
        ),
        "evidence_confidence_available": confidence_assessment is not None,
        "evidence_confidence_current": (
            confidence_assessment.current_confidence
            if confidence_assessment
            else None
        ),
        "evidence_confidence_own_mean": (
            confidence_assessment.baseline_mean_confidence
            if confidence_assessment
            else None
        ),
        "evidence_confidence_decision": (
            confidence_assessment.decision.value
            if confidence_assessment
            else None
        ),
        "evidence_confidence_reason": (
            confidence_assessment.reason if confidence_assessment else None
        ),
        "canonical_price_opportunities_available": opportunities is not None,
        "canonical_price_opportunity_count": (
            len(opportunities.opportunities)
            if opportunities is not None
            else 0
        ),
        "price_opportunity_source": "live_planning_snapshot",
        "price_window_context": _context_value(
            planner_context,
            "price_entry_opportunity_context",
        ),
        "price_window_starts_at": _context_value(
            planner_context,
            "price_entry_opportunity_starts_at",
        ),
        "price_window_ends_at": _context_value(
            planner_context,
            "price_entry_opportunity_ends_at",
        ),
        "price_window_best_later_starts_at": _context_value(
            planner_context,
            "price_entry_best_later_starts_at",
        ),
        "price_window_best_later_price_eur_per_kwh": _context_value(
            planner_context,
            "price_entry_best_later_price_eur_per_kwh",
        ),
        "adr037_pipeline_stage_reached": (
            "evaluation"
            if planning_result is not None
            else "projected_household_energy_balance"
            if balance is not None
            else "planning_input"
        ),
        "adr037_live_ready": not blockers,
        "adr037_live_blockers": blockers,
        "adr037_requirement_energy_wh": (
            requirement.required_energy_wh if requirement else None
        ),
        "adr037_requirement_protection_starts_at": (
            requirement.protection_starts_at.isoformat()
            if requirement
            else None
        ),
        "adr037_requirement_protected_through": (
            requirement.protected_through.isoformat()
            if requirement
            else None
        ),
        "adr037_remaining_charge_energy_wh": remaining_charge_wh,
        "adr037_additional_acquisition_required": acquisition_required,
        "adr037_latest_full_power_charge_start": (
            latest_charge_start.isoformat()
            if latest_charge_start is not None
            else None
        ),
        "adr037_recovery_start_due": recovery_start_due,
        "adr037_technically_recoverable": (
            recoverability.technically_recoverable
            if recoverability is not None
            else None
        ),
        "adr037_charge_needed_now": acquisition_required,
        "adr037_pv_only_sufficient": (
            planning_result.pv_only_feasibility.energy_sufficient
            if planning_result
            else None
        ),
        "adr037_candidate_count": (
            len(planning_result.candidate_set.candidates)
            if planning_result
            else 0
        ),
        "adr037_evaluation_status": (
            planning_result.evaluation.status.value
            if planning_result
            else None
        ),
        "adr037_winning_candidate_id": (
            winner.candidate_id if winner is not None else None
        ),
        "adr037_winning_candidate_family": (
            winner.family.value if winner is not None else None
        ),
        "control_change_allowed": False,
        "observer_only": True,
    }
    return LiveADR037ReadinessRun(event=event, planning_result=planning_result)


def adr037_readiness_log_event(
    snapshot: PlanningInputSnapshot,
    *,
    capabilities: CapabilitySnapshotSet | None = None,
    effective_limit: EffectiveStorageLimit | None = None,
    confidence_tracker: LiveEvidenceConfidenceTracker | None = None,
    planner_context: Mapping[str, object] | None = None,
    price_margin_eur_per_kwh: float = 0.04,
) -> dict[str, object]:
    """Return presentation evidence for callers that do not need the typed result."""

    return run_adr037_readiness(
        snapshot,
        capabilities=capabilities,
        effective_limit=effective_limit,
        confidence_tracker=confidence_tracker,
        planner_context=planner_context,
        price_margin_eur_per_kwh=price_margin_eur_per_kwh,
    ).event
