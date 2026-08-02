"""Normalize Home Assistant grid-power entities into PicoT household state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from picot.domain.household_state import HouseholdState


def household_state_from_grid_power_entity(
    state: dict[str, Any],
    *,
    import_is_positive: bool = True,
) -> HouseholdState:
    """Build a vendor-independent household state from one HA power entity.

    PicoT uses positive grid power for import and negative grid power for export.
    """

    entity_id = state.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError("Home Assistant grid-power state requires an entity ID.")

    raw_state = state.get("state")
    if not isinstance(raw_state, str) or raw_state in {"unknown", "unavailable", ""}:
        raise ValueError("Home Assistant grid-power state is unavailable.")
    try:
        measured_power_w = float(raw_state)
    except ValueError as exc:
        raise ValueError("Home Assistant grid-power state must be numeric.") from exc

    attributes = state.get("attributes", {})
    if not isinstance(attributes, dict):
        raise ValueError("Home Assistant grid-power attributes must be an object.")
    unit = attributes.get("unit_of_measurement")
    if unit != "W":
        raise ValueError("Home Assistant grid-power entity must use watts.")

    updated = state.get("last_updated")
    if not isinstance(updated, str):
        raise ValueError("Home Assistant grid-power state requires last_updated.")
    measured_at = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    if measured_at.tzinfo is None or measured_at.utcoffset() is None:
        raise ValueError("Home Assistant grid-power timestamp must be timezone-aware.")

    grid_power_w = measured_power_w if import_is_positive else -measured_power_w
    return HouseholdState(
        measured_at=measured_at,
        phases=(),
        grid_power_w=grid_power_w,
    )
