"""Read-only live projection of one canonical PicoT v2 run."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from picot.v2.contracts import CanonicalPipelineRun


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
                "projected_balance_count": len(
                    c.projected_balances
                ),
                "storage_requirement_count": len(
                    c.storage_requirements
                ),
                "derivation_status": c.derivation_status,
                "derivation_reason": c.derivation_reason,
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
            },
        ),
        Card(
            "sensor.picot_v2_pipeline_04_evaluation_engine",
            "winner_selected",
            base(c.candidate_set_id, e.evaluation_id, "derived")
            | {
                "winning_candidate_id": e.winning_candidate_id,
                "winning_energy_path_id": e.winning_energy_path_id,
            },
        ),
        Card(
            "sensor.picot_v2_pipeline_05_execution_plan_builder",
            "ready",
            base(e.evaluation_id, ps.plan_set_id, "derived")
            | {"plan_count": len(ps.plan_ids)},
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
            base(er.execution_record_id, pb.request_id or "none", "not_consumed"),
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
