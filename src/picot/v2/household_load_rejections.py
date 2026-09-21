"""Bounded rejected-input evidence, never a source of household load or forecasts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from picot.v2.planning_input import PlanningInputBundle

MAX_HISTORY_BYTES = 16 * 1024**2
MAX_RECORD_BYTES = 64 * 1024
ROLES = frozenset({
    "grid_power", "pv_power", "storage_power_signed",
    "storage_power_to_house", "storage_power_from_house",
})


def _time(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


class HouseholdLoadRejectionStore:
    """Single runtime writer, no deletion/rotation or connection to valid history."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, bundle: PlanningInputBundle) -> None:
        if bundle.household_load_observation is not None:
            return
        sources = []
        for item in bundle.evidence:
            if item.semantic_role not in ROLES:
                continue
            # Explicit scalar/time allow-list; no nested forecast/price histories.
            sources.append({
                key: getattr(item, key) for key in {
                    "entity_id", "semantic_role", "raw_state", "raw_unit",
                    "availability", "error", "evidence_id", "mapping_version",
                    "observed_at", "state_read_at", "last_updated_at", "last_changed_at",
                }
            })
        payload = {
            "schema_version": 1,
            "event": "household_load_rejected",
            "observer_only": True,
            "run_id": bundle.snapshot.run_id,
            "snapshot_id": bundle.snapshot.snapshot_id,
            "picot_version": bundle.snapshot.picot_version,
            "sampled_at": bundle.snapshot.captured_at,
            "assembly_started_at": bundle.assembly_started_at,
            "assembly_finished_at": bundle.assembly_finished_at,
            "reason": bundle.household_load_rejection_reason or "unclassified_rejection",
            "sources": sources,
        }
        encoded = (json.dumps(payload, default=_time, allow_nan=False,
                              separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > MAX_RECORD_BYTES:
            raise OSError("household_rejection_record_limit")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            if handle.tell() + len(encoded) > MAX_HISTORY_BYTES:
                raise OSError("household_rejection_storage_limit")
            handle.write(encoded)
