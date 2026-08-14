"""Pure read-only data projection for the PicoT v2 web UI."""

from __future__ import annotations

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.projection import Projection


def build_web_view(
    run: CanonicalPipelineRun,
    projection: Projection,
) -> dict[str, object]:
    """Build one JSON-serializable observer view without side effects."""
    planning_input = run.planning_input
    timeline = planning_input.pv_energy_timeline
    intervals = (
        timeline.intervals
        if timeline is not None
        else ()
    )

    pipeline = [
        {
            "stage": stage,
            "entity_id": card.entity_id,
            "state": card.state,
            "attributes": dict(card.attributes),
        }
        for stage, card in enumerate(projection.cards, start=1)
    ]
    pv_energy_timeline: dict[str, object] = {
        "available": timeline is not None,
        "timeline_id": (
            timeline.timeline_id
            if timeline is not None
            else None
        ),
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "interval_count": len(intervals),
        "total_wh": sum(
            interval.pv_energy_wh
            for interval in intervals
        ),
        "starts_at": (
            intervals[0].starts_at.isoformat()
            if intervals
            else None
        ),
        "ends_at": (
            intervals[-1].ends_at.isoformat()
            if intervals
            else None
        ),
        "intervals": [
            {
                "interval_id": interval.interval_id,
                "starts_at": interval.starts_at.isoformat(),
                "ends_at": interval.ends_at.isoformat(),
                "pv_energy_wh": interval.pv_energy_wh,
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
            for interval in intervals
        ],
    }

    return {
        "schema_version": 1,
        "observer_only": True,
        "picot_version": planning_input.picot_version,
        "run_id": planning_input.run_id,
        "snapshot_id": planning_input.snapshot_id,
        "captured_at": planning_input.captured_at.isoformat(),
        "pipeline": pipeline,
        "pv_energy_timeline": pv_energy_timeline,
    }
