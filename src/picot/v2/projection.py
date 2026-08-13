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
            base("bootstrap", p.snapshot_id, "unchanged"),
        ),
        Card(
            "sensor.picot_v2_pipeline_02_opportunity_engine",
            "ready",
            base(p.snapshot_id, o.opportunity_set_id, "derived")
            | {"opportunity_count": len(o.opportunity_ids)},
        ),
        Card(
            "sensor.picot_v2_pipeline_03_candidate_engine",
            "ready",
            base(o.opportunity_set_id, c.candidate_set_id, "derived")
            | {
                "candidate_count": len(c.candidates),
                "energy_path_ids": [path.path_id for path in c.energy_paths],
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
