"""Observer-only projection of live sunset diagnostics."""

from __future__ import annotations

from picot.v2.projection import Card, Projection
from picot.v2.pv_sunset_offsets import SUNSET_OFFSET_METHOD_VERSION
from picot.v2.pv_sunset_source import SunsetReadResult


def project_pv_sunset_runtime_diagnostics(
    *,
    source: SunsetReadResult,
    local_timezone: str,
    offsets_by_interval_id: dict[str, float],
) -> dict[str, object]:
    """Expose source and offset lineage without recalculation."""

    if not local_timezone.strip():
        raise ValueError("local_timezone must be explicit")

    return {
        "pv_sunset_source_status": source.status,
        "pv_sunset_source_entity_id": source.source_entity_id,
        "pv_sunset_source_error": source.error,
        "pv_sunset_source_updated_at": (
            source.source_updated_at.isoformat()
            if source.source_updated_at is not None
            else None
        ),
        "pv_sunset_source_method_version": source.method_version,
        "pv_sunset_local_timezone": local_timezone,
        "pv_sunset_date_count": len(source.sunsets_by_local_date),
        "pv_sunset_dates": [
            local_date.isoformat()
            for local_date, _ in source.sunsets_by_local_date
        ],
        "pv_sunset_values": [
            {
                "local_date": local_date.isoformat(),
                "sunset_at": sunset_at.isoformat(),
            }
            for local_date, sunset_at in source.sunsets_by_local_date
        ],
        "pv_sunset_offset_interval_count": len(
            offsets_by_interval_id
        ),
        "pv_sunset_offset_method_version": (
            SUNSET_OFFSET_METHOD_VERSION
        ),
    }


def attach_pv_sunset_runtime_diagnostics(
    projection: Projection,
    *,
    source: SunsetReadResult,
    local_timezone: str,
    offsets_by_interval_id: dict[str, float],
) -> Projection:
    """Attach sunset diagnostics to card 1 and preserve later cards."""

    first = projection.cards[0]
    enriched = Card(
        first.entity_id,
        first.state,
        first.attributes
        | project_pv_sunset_runtime_diagnostics(
            source=source,
            local_timezone=local_timezone,
            offsets_by_interval_id=offsets_by_interval_id,
        ),
    )
    return Projection(
        cards=(enriched, *projection.cards[1:]),
        projection_ms=projection.projection_ms,
    )
