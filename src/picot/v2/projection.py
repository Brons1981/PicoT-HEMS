"""Read-only live projection of one canonical PicoT v2 run."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.storage_energy_source_need import (
    derive_storage_energy_source_need,
)


@dataclass(frozen=True, slots=True)
class Card:
    entity_id: str
    state: str
    attributes: dict[str, object]


@dataclass(frozen=True, slots=True)
class Projection:
    cards: tuple[Card, ...]
    projection_ms: float


def project(run: CanonicalPipelineRun) -> Projection:
    started = perf_counter()
    p = run.planning_input
    pv_timeline = p.pv_energy_timeline
    pv_intervals = (
        pv_timeline.intervals
        if pv_timeline is not None
        else ()
    )

    def base(
        input_ref: str,
        output_ref: str,
        lineage_status: str,
    ) -> dict[str, object]:
        return {
            "picot_version": p.picot_version,
            "run_id": p.run_id,
            "snapshot_id": p.snapshot_id,
            "captured_at": p.captured_at.isoformat(),
            "input_reference": input_ref,
            "output_reference": output_ref,
            "lineage_status": lineage_status,
            "observer_only": True,
        }

    o = run.opportunities
    c = run.candidate_set
    e = run.evaluation
    ps = run.execution_plan_set
    er = run.execution_record
    pb = run.primitive_boundary
    ab = run.adapter_boundary
    vr = run.vendor_result

    storage_states_by_id = {
        state.storage_state_id: state
        for state in p.current_storage_states
    }
    projected_balances_by_id = {
        balance.balance_id: balance
        for balance in c.projected_balances
    }
    storage_source_needs = tuple(
        derive_storage_energy_source_need(
            storage_state=storage_states_by_id[requirement.storage_state_id],
            balance=projected_balances_by_id[
                requirement.projected_balance_id
            ],
            requirement=requirement,
        )
        for requirement in c.storage_requirements
        if requirement.storage_state_id in storage_states_by_id
        and requirement.projected_balance_id in projected_balances_by_id
    )
    detailed_outcomes_by_candidate_id = {
        outcome.candidate_id: outcome
        for outcome in run.outcomes.outcomes
    }
    timed_storage_candidates = []
    for candidate in c.candidates:
        if candidate.family != "pv_charge_only":
            continue
        path = next(
            (
                item
                for item in c.energy_paths
                if item.path_id == candidate.energy_path_id
            ),
            None,
        )
        outcome = detailed_outcomes_by_candidate_id.get(candidate.candidate_id)
        if path is None or not path.segments or outcome is None:
            continue
        segment = path.segments[0]
        timed_storage_candidates.append(
            {
                "candidate_id": candidate.candidate_id,
                "energy_path_id": path.path_id,
                "family": candidate.family,
                "primitive": segment.primitive.value,
                "charge_source_policy": (
                    segment.charge_source_policy.value
                    if segment.charge_source_policy is not None
                    else None
                ),
                "starts_at": outcome.charge_window_starts_at.isoformat(),
                "ends_at": outcome.charge_window_ends_at.isoformat(),
                "pv_storage_contribution_kwh": (
                    outcome.pv_storage_contribution_wh / 1000.0
                ),
                "grid_storage_contribution_kwh": (
                    outcome.grid_storage_contribution_wh / 1000.0
                ),
                "storage_energy_at_window_end_kwh": (
                    outcome.storage_energy_at_window_end_wh / 1000.0
                ),
                "storage_energy_at_requirement_kwh": (
                    outcome.storage_energy_at_requirement_wh / 1000.0
                ),
                "required_energy_kwh": outcome.required_energy_wh / 1000.0,
                "requirement_satisfied": outcome.requirement_satisfied,
                "recoverability": outcome.recoverability,
                "confidence": outcome.confidence,
            }
        )
    winning_candidate = next(
        (
            candidate
            for candidate in c.candidates
            if candidate.candidate_id == e.winning_candidate_id
        ),
        None,
    )
    projected_plans = [
        {
            "plan_id": plan.plan_id,
            "execution_scope_id": plan.execution_scope_id,
            "observer_only": plan.observer_only,
            "winning_candidate_id": plan.winning_candidate_id,
            "winning_energy_path_id": plan.winning_energy_path_id,
            "segment_count": len(plan.segments),
            "segments": [
                {
                    "segment_id": segment.segment_id,
                    "source_path_segment_id": segment.source_path_segment_id,
                    "starts_at": segment.starts_at.isoformat(),
                    "ends_at": segment.ends_at.isoformat(),
                    "primitive": segment.primitive.value,
                    "capability_id": segment.capability_id,
                    "requested_power_w": segment.requested_power_w,
                    "charge_source_policy": (
                        segment.charge_source_policy.value
                        if segment.charge_source_policy is not None
                        else None
                    ),
                }
                for segment in plan.segments
            ],
        }
        for plan in ps.plans
    ]

    cards = (
        Card(
            "sensor.picot_v2_pipeline_01_planning_input",
            "ready",
            base("bootstrap", p.snapshot_id, "unchanged")
            | {
                "current_storage_state_count": len(
                    p.current_storage_states
                ),
                "current_storage_states": [
                    {
                        "storage_state_id": state.storage_state_id,
                        "execution_scope_id": state.execution_scope_id,
                        "capability_id": state.capability_id,
                        "current_soc": state.current_soc,
                        "usable_capacity_wh": state.usable_capacity_wh,
                        "current_stored_energy_wh": (
                            state.current_stored_energy_wh
                        ),
                        "measured_at": state.measured_at.isoformat(),
                        "confidence": state.confidence,
                        "evidence_ids": list(state.evidence_ids),
                    }
                    for state in p.current_storage_states
                ],
                "pv_energy_timeline_available": pv_timeline is not None,
                "pv_energy_interval_count": len(pv_intervals),
                "pv_energy_total_wh": sum(
                    interval.pv_energy_wh
                    for interval in pv_intervals
                ),
                "pv_energy_starts_at": (
                    pv_intervals[0].starts_at.isoformat()
                    if pv_intervals
                    else None
                ),
                "pv_energy_ends_at": (
                    pv_intervals[-1].ends_at.isoformat()
                    if pv_intervals
                    else None
                ),
                "pv_energy_confidence_min": (
                    min(
                        interval.confidence
                        for interval in pv_intervals
                    )
                    if pv_intervals
                    else None
                ),
                "pv_energy_confidence_average": (
                    sum(
                        interval.confidence
                        for interval in pv_intervals
                    )
                    / len(pv_intervals)
                    if pv_intervals
                    else None
                ),
                "pv_energy_intervals": [
                    {
                        "interval_id": interval.interval_id,
                        "starts_at": interval.starts_at.isoformat(),
                        "ends_at": interval.ends_at.isoformat(),
                        "pv_energy_wh": interval.pv_energy_wh,
                        "forecast_lower_energy_wh": (
                            interval.forecast_lower_energy_wh
                        ),
                        "forecast_central_energy_wh": (
                            interval.forecast_central_energy_wh
                        ),
                        "forecast_upper_energy_wh": (
                            interval.forecast_upper_energy_wh
                        ),
                        "forecast_range_status": (
                            interval.forecast_range_status
                        ),
                        "forecast_range_source_fields": list(
                            interval.forecast_range_source_fields
                        ),
                        "forecast_range_method_version": (
                            interval.forecast_range_method_version
                        ),
                        "evidence_type": interval.evidence_type,
                        "confidence": interval.confidence,
                        "actual_evidence_ids": list(
                            interval.actual_evidence_ids
                        ),
                        "forecast_evidence_ids": list(
                            interval.forecast_evidence_ids
                        ),
                        "conversion_method_version": (
                            interval.conversion_method_version
                        ),
                    }
                    for interval in pv_intervals
                ],
            },
        ),
        Card(
            "sensor.picot_v2_pipeline_02_opportunity_engine",
            o.detection_status,
            base(p.snapshot_id, o.opportunity_set_id, "derived")
            | {
                "opportunity_count": len(o.opportunities),
                "detection_reason": o.detection_reason,
                "detector_config_version": o.detector_config_version,
                "opportunities": [
                    {
                        "opportunity_id": item.opportunity_id,
                        "kind": item.kind,
                        "starts_at": item.starts_at.isoformat(),
                        "ends_at": item.ends_at.isoformat(),
                        "duration_seconds": item.metrics.duration_seconds,
                        "confidence": item.confidence,
                        "lifecycle_status": item.lifecycle_status,
                        "average_price_eur_per_kwh": item.metrics.average_price_eur_per_kwh,
                        "minimum_price_eur_per_kwh": item.metrics.minimum_price_eur_per_kwh,
                        "maximum_price_eur_per_kwh": item.metrics.maximum_price_eur_per_kwh,
                        "boundary_eur_per_kwh": item.metrics.boundary_eur_per_kwh,
                        "source_interval_count": item.metrics.source_interval_count,
                        "bridged_interval_count": item.metrics.bridged_interval_count,
                        "evidence": [
                            {
                                "evidence_id": evidence.evidence_id,
                                "point_ids": list(evidence.point_ids),
                            }
                            for evidence in item.evidence
                        ],
                    }
                    for item in o.opportunities
                ],
            },
        ),
        Card(
            "sensor.picot_v2_pipeline_03_candidate_engine",
            "ready",
            base(o.opportunity_set_id, c.candidate_set_id, "derived")
            | {
                "candidate_count": len(c.candidates),
                "energy_path_ids": [path.path_id for path in c.energy_paths],
                "timed_storage_candidate_count": len(
                    timed_storage_candidates
                ),
                "timed_storage_candidates": timed_storage_candidates,
                "projected_balance_count": len(
                    c.projected_balances
                ),
                "storage_requirement_count": len(
                    c.storage_requirements
                ),
                "storage_source_need_count": len(
                    storage_source_needs
                ),
                "storage_source_needs": [
                    {
                        "storage_state_id": need.storage_state_id,
                        "target_energy_wh": need.target_energy_wh,
                        "energy_to_target_wh": need.energy_to_target_wh,
                        "expected_usable_pv_energy_wh": (
                            need.expected_usable_pv_energy_wh
                        ),
                        "household_load_forecast_energy_wh": (
                            need.household_load_forecast_energy_wh
                        ),
                        "pv_storage_contribution_wh": (
                            need.pv_storage_contribution_wh
                        ),
                        "grid_energy_required_wh": (
                            need.grid_energy_required_wh
                        ),
                        "pv_only_feasible": need.pv_only_feasible,
                        "status": need.status,
                        "required_by": need.required_by.isoformat(),
                        "confidence": need.confidence,
                        "method_version": need.method_version,
                    }
                    for need in storage_source_needs
                ],
                "derivation_status": c.derivation_status,
                "derivation_reason": c.derivation_reason,
                "pv_forecast_assumption_set_id": (
                    c.pv_forecast_assumption_set.assumption_set_id
                    if c.pv_forecast_assumption_set is not None
                    else None
                ),
                "pv_forecast_assumption_count": (
                    len(c.pv_forecast_assumption_set.assumptions)
                    if c.pv_forecast_assumption_set is not None
                    else 0
                ),
                "pv_forecast_maximum_assumption_count": (
                    c.pv_forecast_assumption_set
                    .maximum_assumption_count
                    if c.pv_forecast_assumption_set is not None
                    else 3
                ),
                "pv_forecast_assumption_method_version": (
                    c.pv_forecast_assumption_set.method_version
                    if c.pv_forecast_assumption_set is not None
                    else None
                ),
                "pv_forecast_assumptions": [
                    {
                        "assumption_id": assumption.assumption_id,
                        "basis": assumption.basis,
                        "scope": assumption.scope,
                        "status": assumption.status,
                        "unavailable_reason": (
                            assumption.unavailable_reason
                        ),
                        "method_version": assumption.method_version,
                        "intervals": [
                            {
                                "source_interval_id": (
                                    interval.source_interval_id
                                ),
                                "starts_at": (
                                    interval.starts_at.isoformat()
                                ),
                                "ends_at": interval.ends_at.isoformat(),
                                "selected_energy_wh": (
                                    interval.selected_energy_wh
                                ),
                                "confidence": interval.confidence,
                                "forecast_evidence_ids": list(
                                    interval.forecast_evidence_ids
                                ),
                                "forecast_range_status": (
                                    interval.forecast_range_status
                                ),
                                "forecast_range_method_version": (
                                    interval
                                    .forecast_range_method_version
                                ),
                                "conversion_method_version": (
                                    interval.conversion_method_version
                                ),
                            }
                            for interval in assumption.intervals
                        ],
                    }
                    for assumption in (
                        c.pv_forecast_assumption_set.assumptions
                        if c.pv_forecast_assumption_set is not None
                        else ()
                    )
                ],
                "planning_gaps": [
                    {
                        "kind": gap.kind,
                        "starts_at": gap.starts_at.isoformat(),
                        "ends_at": gap.ends_at.isoformat(),
                        "duration_seconds": gap.duration_seconds,
                        "assumption": gap.assumption,
                        "confidence": gap.confidence,
                    }
                    for gap in c.planning_gaps
                ],
                "storage_requirements": [
                    {
                        "required_energy_wh": requirement.required_energy_wh,
                        "required_soc": requirement.required_soc,
                        "required_by": requirement.required_by.isoformat(),
                        "reason": requirement.reason,
                        "confidence": requirement.confidence,
                        "reserve_contribution_wh": (
                            requirement.reserve_contribution_wh
                        ),
                    }
                    for requirement in c.storage_requirements
                ],
                "projected_balances": [
                    {
                        "balance_id": balance.balance_id,
                        "storage_state_id": balance.storage_state_id,
                        "intervals": [
                            {
                                "starts_at": interval.starts_at.isoformat(),
                                "ends_at": interval.ends_at.isoformat(),
                                "current_usable_storage_energy_wh": (
                                    interval.current_usable_storage_energy_wh
                                ),
                                "expected_usable_pv_energy_wh": (
                                    interval.expected_usable_pv_energy_wh
                                ),
                                "planned_grid_energy_wh": (
                                    interval.planned_grid_energy_wh
                                ),
                                "household_load_forecast_energy_wh": (
                                    interval.household_load_forecast_energy_wh
                                ),
                                "known_future_demand_energy_wh": (
                                    interval.known_future_demand_energy_wh
                                ),
                                "conversion_losses_wh": (
                                    interval.conversion_losses_wh
                                ),
                                "other_planned_household_energy_flows_wh": (
                                    interval.other_planned_household_energy_flows_wh
                                ),
                                "projected_storage_energy_wh": (
                                    interval.projected_storage_energy_wh
                                ),
                                "confidence": interval.confidence,
                                "evidence_ids": list(
                                    interval.evidence_ids
                                ),
                            }
                            for interval in balance.intervals
                        ],
                    }
                    for balance in c.projected_balances
                ],
            },
        ),
        Card(
            "sensor.picot_v2_pipeline_04_evaluation_engine",
            e.status,
            base(c.candidate_set_id, e.evaluation_id, "derived")
            | {
                "winning_candidate_id": e.winning_candidate_id,
                "winning_energy_path_id": e.winning_energy_path_id,
                "winning_family": (
                    winning_candidate.family
                    if winning_candidate is not None
                    else None
                ),
                "evaluated_candidate_ids": list(e.evaluated_candidate_ids),
                "decisive_step": e.decisive_step,
                "reason": e.reason,
            },
        ),
        Card(
            "sensor.picot_v2_pipeline_05_execution_plan_builder",
            (
                "blocked"
                if e.winning_candidate_id is None
                else ("observer_only" if ps.plans else "ready")
            ),
            base(e.evaluation_id, ps.plan_set_id, "derived")
            | {
                "plan_count": len(ps.plan_ids),
                "plans": projected_plans,
            },
        ),
        Card(
            "sensor.picot_v2_pipeline_06_execution_engine",
            er.status,
            base(ps.plan_set_id, er.execution_record_id, "derived")
            | {"reason": er.reason},
        ),
        Card(
            "sensor.picot_v2_pipeline_07_execution_primitive",
            pb.status,
            base(er.execution_record_id, pb.request_id or "none", "not_consumed")
            | {
                "planned_primitive": (
                    pb.planned_primitive.value
                    if pb.planned_primitive is not None
                    else None
                ),
                "mapping_status": pb.mapping_status,
                "source_entity_id": pb.source_entity_id,
                "current_vendor_mode": pb.current_vendor_mode,
                "planned_vendor_mode": pb.planned_vendor_mode,
                "mapping_method_version": pb.mapping_method_version,
                "blockers": list(pb.blockers),
                "mode_provenance_status": (
                    p.storage_mode_control_provenance.status
                    if p.storage_mode_control_provenance is not None
                    else "unverified"
                ),
                "manual_override_active": (
                    p.storage_mode_control_provenance.manual_override_active
                    if p.storage_mode_control_provenance is not None
                    else False
                ),
                "mode_provenance_reason": (
                    p.storage_mode_control_provenance.transition_reason
                    if p.storage_mode_control_provenance is not None
                    else "no_provenance_evidence"
                ),
            },
        ),
        Card(
            "sensor.picot_v2_pipeline_08_device_adapter",
            ab.status,
            base(pb.request_id or "none", ab.translation_id or "none", "not_consumed"),
        ),
        Card(
            "sensor.picot_v2_pipeline_09_vendor_result",
            vr.status,
            base(ab.translation_id or "none", vr.command_id or "none", "not_consumed"),
        ),
    )
    elapsed_ms = round((perf_counter() - started) * 1000.0, 3)
    return Projection(cards=cards, projection_ms=elapsed_ms)
