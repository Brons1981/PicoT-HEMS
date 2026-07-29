"""Contract tests for the PicoT HEMS Capability Lifecycle Engine."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from capability_lifecycle import (  # noqa: E402
    CapabilityLifecycleEngine,
    LifecycleError,
)
from capability_mapping_store import CapabilityMappingStore  # noqa: E402

CAPABILITY_ID = "battery.system.observation.soc"


def _clock() -> Any:
    values = iter(
        [
            "2026-07-29T18:00:00+00:00",
            "2026-07-29T18:01:00+00:00",
            "2026-07-29T18:02:00+00:00",
            "2026-07-29T18:03:00+00:00",
            "2026-07-29T18:04:00+00:00",
            "2026-07-29T18:05:00+00:00",
        ]
    )
    return lambda: next(values)


def _selection_record() -> dict[str, Any]:
    return {
        "selection_record_id": "sel_1",
        "capability_id": CAPABILITY_ID,
        "capability_role": "primary",
        "candidates": [
            {
                "candidate_id": "cand_1",
                "source": {
                    "source_type": "HOME_ASSISTANT_ENTITY",
                    "source_id": "ha_entity:sensor.zendure_system_soc",
                    "entity_id": "sensor.zendure_system_soc",
                },
                "eligibility": {"eligible": True},
                "semantic_validation": {"status": "VALID"},
            }
        ],
        "proposal": {"proposed_action": "CREATE_MAPPING"},
        "decision": {
            "status": "APPROVED",
            "selected_candidate_id": "cand_1",
            "mapping_creation_requested": True,
        },
    }


def _engine() -> tuple[CapabilityMappingStore, CapabilityLifecycleEngine]:
    clock = _clock()
    store = CapabilityMappingStore(now=clock, id_factory=lambda prefix: f"{prefix}_1")
    store.activate_from_selection(_selection_record())
    engine = CapabilityLifecycleEngine(
        store,
        now=clock,
        id_factory=lambda prefix: f"{prefix}_1",
    )
    return store, engine


def test_source_unavailable_marks_mapping_temporarily_unavailable() -> None:
    store, engine = _engine()

    record = engine.process_event(
        capability_id=CAPABILITY_ID,
        event_type="SOURCE_UNAVAILABLE",
        evidence={"state": "unavailable"},
    )

    assert store.get_current(CAPABILITY_ID)["status"] == "TEMPORARILY_UNAVAILABLE"
    assert record["transition"]["from_status"] == "ACTIVE"
    assert record["transition"]["to_status"] == "TEMPORARILY_UNAVAILABLE"
    assert record["rediscovery"]["required"] is False
    assert record["selection_required"] is False
    assert record["source_replacement_performed"] is False


def test_source_available_restores_same_mapping() -> None:
    store, engine = _engine()
    engine.process_event(capability_id=CAPABILITY_ID, event_type="SOURCE_UNAVAILABLE")

    record = engine.process_event(
        capability_id=CAPABILITY_ID,
        event_type="SOURCE_AVAILABLE",
    )

    current = store.get_current(CAPABILITY_ID)
    assert current["status"] == "ACTIVE"
    assert current["mapping_id"] == "map_1"
    assert current["source"]["entity_id"] == "sensor.zendure_system_soc"
    assert record["rediscovery"]["required"] is False


def test_objective_invalidity_requires_capability_scoped_rediscovery() -> None:
    store, engine = _engine()

    record = engine.process_event(
        capability_id=CAPABILITY_ID,
        event_type="ENTITY_REMOVED",
        evidence={"entity_id": "sensor.zendure_system_soc"},
    )

    assert store.get_current(CAPABILITY_ID)["status"] == "INVALID"
    assert record["transition"]["reason"] == "entity_removed"
    assert record["rediscovery"] == {
        "required": True,
        "scope": {
            "capability_id": CAPABILITY_ID,
            "capability_role": "primary",
        },
    }
    assert record["selection_required"] is True
    assert record["source_replacement_performed"] is False


def test_semantic_invalidity_is_objective_invalidity() -> None:
    store, engine = _engine()

    record = engine.process_event(
        capability_id=CAPABILITY_ID,
        event_type="SEMANTIC_INVALID",
    )

    assert store.get_current(CAPABILITY_ID)["invalidity_reason"] == "semantic_invalid"
    assert record["rediscovery"]["required"] is True


def test_duplicate_unavailable_event_is_idempotent_and_audited() -> None:
    store, engine = _engine()
    first = engine.process_event(
        capability_id=CAPABILITY_ID,
        event_type="SOURCE_UNAVAILABLE",
    )
    second = engine.process_event(
        capability_id=CAPABILITY_ID,
        event_type="SOURCE_UNAVAILABLE",
    )

    assert first["transition"]["changed"] is True
    assert second["transition"]["changed"] is False
    assert second["transition"]["from_mapping_version"] == 2
    assert second["transition"]["to_mapping_version"] == 2
    assert len(store.get_history(CAPABILITY_ID)) == 2
    assert len(engine.get_records(capability_id=CAPABILITY_ID)) == 2


def test_restore_is_rejected_when_mapping_is_not_temporarily_unavailable() -> None:
    _, engine = _engine()

    with pytest.raises(LifecycleError, match="temporarily unavailable"):
        engine.process_event(
            capability_id=CAPABILITY_ID,
            event_type="SOURCE_AVAILABLE",
        )


def test_unsupported_event_is_rejected() -> None:
    _, engine = _engine()

    with pytest.raises(LifecycleError, match="unsupported lifecycle event"):
        engine.process_event(
            capability_id=CAPABILITY_ID,
            event_type="LOW_BATTERY",
        )


def test_lifecycle_records_are_returned_as_copies() -> None:
    _, engine = _engine()
    engine.process_event(
        capability_id=CAPABILITY_ID,
        event_type="SOURCE_UNAVAILABLE",
    )

    records = engine.get_records()
    records[0]["transition"]["to_status"] = "CORRUPTED"

    assert engine.get_records()[0]["transition"]["to_status"] == "TEMPORARILY_UNAVAILABLE"
