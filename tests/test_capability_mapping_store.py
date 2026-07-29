"""Contract tests for the PicoT HEMS Capability Mapping Store."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from capability_mapping_store import (  # noqa: E402
    CapabilityMappingStore,
    MappingStoreError,
)


CAPABILITY_ID = "battery.system.observation.soc"


def _clock() -> Any:
    values = iter(
        [
            "2026-07-29T18:00:00+00:00",
            "2026-07-29T18:01:00+00:00",
            "2026-07-29T18:02:00+00:00",
            "2026-07-29T18:03:00+00:00",
            "2026-07-29T18:04:00+00:00",
        ]
    )
    return lambda: next(values)


def _selection_record(
    *,
    record_id: str = "sel_1",
    candidate_id: str = "cand_1",
    entity_id: str = "sensor.zendure_system_soc",
    action: str = "CREATE_MAPPING",
    approved: bool = True,
    mapping_creation_requested: bool = True,
) -> dict[str, Any]:
    return {
        "selection_record_id": record_id,
        "capability_id": CAPABILITY_ID,
        "capability_role": "primary",
        "candidates": [
            {
                "candidate_id": candidate_id,
                "source": {
                    "source_type": "HOME_ASSISTANT_ENTITY",
                    "source_id": f"ha_entity:{entity_id}",
                    "entity_id": entity_id,
                },
                "eligibility": {"eligible": True},
                "semantic_validation": {"status": "VALID"},
            }
        ],
        "proposal": {"proposed_action": action},
        "decision": {
            "status": "APPROVED" if approved else "PENDING",
            "selected_candidate_id": candidate_id,
            "mapping_creation_requested": mapping_creation_requested,
        },
    }


def test_initial_activation_creates_version_one_mapping() -> None:
    store = CapabilityMappingStore(now=_clock(), id_factory=lambda prefix: f"{prefix}_1")

    mapping = store.activate_from_selection(_selection_record())

    assert mapping["mapping_id"] == "map_1"
    assert mapping["mapping_version"] == 1
    assert mapping["status"] == "ACTIVE"
    assert mapping["source"]["entity_id"] == "sensor.zendure_system_soc"
    assert mapping["selection_record_id"] == "sel_1"
    assert mapping["replaces_mapping_version"] is None


def test_active_mapping_cannot_be_silently_replaced() -> None:
    store = CapabilityMappingStore(now=_clock(), id_factory=lambda prefix: f"{prefix}_1")
    store.activate_from_selection(_selection_record())

    with pytest.raises(MappingStoreError, match="silently replaced"):
        store.activate_from_selection(
            _selection_record(
                record_id="sel_2",
                candidate_id="cand_2",
                entity_id="sensor.other_soc",
                action="REPLACE_MAPPING",
            )
        )


def test_temporary_unavailability_preserves_source_and_mapping_identity() -> None:
    store = CapabilityMappingStore(now=_clock(), id_factory=lambda prefix: f"{prefix}_1")
    original = store.activate_from_selection(_selection_record())

    unavailable = store.mark_temporarily_unavailable(CAPABILITY_ID)

    assert unavailable["mapping_id"] == original["mapping_id"]
    assert unavailable["mapping_version"] == 2
    assert unavailable["status"] == "TEMPORARILY_UNAVAILABLE"
    assert unavailable["source"] == original["source"]
    assert store.get_active(CAPABILITY_ID) == unavailable


def test_temporarily_unavailable_mapping_can_return_to_active() -> None:
    store = CapabilityMappingStore(now=_clock(), id_factory=lambda prefix: f"{prefix}_1")
    store.activate_from_selection(_selection_record())
    store.mark_temporarily_unavailable(CAPABILITY_ID)

    restored = store.restore_available(CAPABILITY_ID)

    assert restored["status"] == "ACTIVE"
    assert restored["mapping_version"] == 3
    assert restored["source"]["entity_id"] == "sensor.zendure_system_soc"


def test_objective_invalidity_creates_new_historical_version() -> None:
    store = CapabilityMappingStore(now=_clock(), id_factory=lambda prefix: f"{prefix}_1")
    store.activate_from_selection(_selection_record())

    invalid = store.invalidate(CAPABILITY_ID, "entity_removed")

    assert invalid["status"] == "INVALID"
    assert invalid["mapping_version"] == 2
    assert invalid["invalidity_reason"] == "entity_removed"
    assert store.get_active(CAPABILITY_ID) is None
    assert len(store.get_history(CAPABILITY_ID)) == 2


def test_invalid_mapping_can_be_replaced_only_by_explicit_replacement_selection() -> None:
    store = CapabilityMappingStore(now=_clock(), id_factory=lambda prefix: f"{prefix}_1")
    original = store.activate_from_selection(_selection_record())
    store.invalidate(CAPABILITY_ID, "entity_removed")

    replacement = store.activate_from_selection(
        _selection_record(
            record_id="sel_2",
            candidate_id="cand_2",
            entity_id="sensor.replacement_soc",
            action="REPLACE_MAPPING",
        )
    )

    assert replacement["mapping_id"] == original["mapping_id"]
    assert replacement["mapping_version"] == 3
    assert replacement["status"] == "ACTIVE"
    assert replacement["source"]["entity_id"] == "sensor.replacement_soc"
    assert replacement["replaces_mapping_version"] == 2


def test_pending_selection_is_rejected() -> None:
    store = CapabilityMappingStore()

    with pytest.raises(MappingStoreError, match="not approved"):
        store.activate_from_selection(_selection_record(approved=False))


def test_selection_without_mapping_request_is_rejected() -> None:
    store = CapabilityMappingStore()

    with pytest.raises(MappingStoreError, match="did not request"):
        store.activate_from_selection(
            _selection_record(mapping_creation_requested=False)
        )


def test_history_is_returned_as_a_copy() -> None:
    store = CapabilityMappingStore(now=_clock(), id_factory=lambda prefix: f"{prefix}_1")
    store.activate_from_selection(_selection_record())

    history = store.get_history(CAPABILITY_ID)
    history[0]["status"] = "CORRUPTED"

    assert store.get_current(CAPABILITY_ID)["status"] == "ACTIVE"
