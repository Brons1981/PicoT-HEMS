"""Contract tests for the minimal PicoT SelectionRecord."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from capability_selection import select_capabilities  # noqa: E402
from selection_record import build_selection_record  # noqa: E402


FIXED_TIME = "2026-07-29T19:30:00+00:00"


def _id_factory() -> Any:
    counters: dict[str, int] = {}

    def factory(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}_{counters[prefix]}"

    return factory


def _candidate(entity_id: str, *, state: str = "42") -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "domain": "sensor",
        "state": state,
        "device_id": "device-1",
        "config_entry_id": "config-1",
        "platform": "sensor",
        "reasons": ["matched_name", "matched_unit"],
        "semantic_validation": {"status": "valid", "reasons": []},
    }


def _selection(*candidates: dict[str, Any]) -> dict[str, Any]:
    result = select_capabilities(
        {
            "capabilities": [
                {
                    "id": "battery.system.observation.soc",
                    "category": "battery",
                    "kind": "observation",
                    "candidates": list(candidates),
                }
            ]
        }
    )
    return result["mappings"][0]


def _record(
    selection: dict[str, Any],
    *,
    current_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_selection_record(
        selection,
        current_mapping=current_mapping,
        now=lambda: FIXED_TIME,
        id_factory=_id_factory(),
    )


def test_single_candidate_allows_automatic_initial_mapping_request() -> None:
    record = _record(_selection(_candidate("sensor.zendure_system_soc")))

    assert record["schema"] == "picot_hems.capability.selection_record"
    assert record["proposal"]["activation_policy"] == "AUTO_ALLOWED"
    assert record["proposal"]["proposed_action"] == "CREATE_MAPPING"
    assert record["confirmation"]["required"] is False
    assert record["decision"]["decision_type"] == "AUTOMATIC_INITIAL_SELECTION"
    assert record["decision"]["mapping_creation_requested"] is True
    assert record["decision"]["created_mapping_id"] is None


def test_multiple_eligible_candidates_require_user_confirmation() -> None:
    record = _record(
        _selection(
            _candidate("sensor.source_b"),
            _candidate("sensor.source_a"),
        )
    )

    assert record["proposal"]["status"] == "AMBIGUOUS"
    assert record["proposal"]["activation_policy"] == "USER_CONFIRMATION_REQUIRED"
    assert record["confirmation"]["status"] == "PENDING"
    assert record["decision"]["status"] == "PENDING"
    assert record["decision"]["mapping_creation_requested"] is False
    assert len(record["candidates"]) == 2


def test_active_mapping_is_never_silently_replaced() -> None:
    mapping = {
        "mapping_id": "map_1",
        "mapping_version": 2,
        "status": "ACTIVE",
        "source_id": "ha_entity:sensor.existing_soc",
    }
    record = _record(
        _selection(_candidate("sensor.new_soc")),
        current_mapping=mapping,
    )

    assert record["proposal"]["proposed_action"] == "KEEP_EXISTING_MAPPING"
    assert record["proposal"]["activation_policy"] == "AUTO_BLOCKED"
    assert record["decision"]["decision_type"] == "KEEP_EXISTING_MAPPING"
    assert record["decision"]["mapping_creation_requested"] is False
    assert record["current_mapping"] == mapping


def test_temporary_unavailability_preserves_existing_mapping() -> None:
    mapping = {
        "mapping_id": "map_1",
        "mapping_version": 2,
        "status": "TEMPORARILY_UNAVAILABLE",
        "source_id": "ha_entity:sensor.existing_soc",
    }
    record = _record(
        _selection(_candidate("sensor.alternative_soc")),
        current_mapping=mapping,
    )

    assert record["proposal"]["proposed_action"] == "KEEP_EXISTING_MAPPING"
    assert "temporary_unavailability_is_not_invalidity" in record["proposal"][
        "proposal_reasons"
    ]
    assert record["confirmation"]["required"] is False


def test_invalid_mapping_may_propose_replacement_but_requires_confirmation() -> None:
    mapping = {
        "mapping_id": "map_1",
        "mapping_version": 2,
        "status": "INVALID",
        "source_id": "ha_entity:sensor.removed_soc",
    }
    record = _record(
        _selection(_candidate("sensor.replacement_soc")),
        current_mapping=mapping,
    )

    assert record["proposal"]["proposed_action"] == "REPLACE_MAPPING"
    assert record["proposal"]["activation_policy"] == "USER_CONFIRMATION_REQUIRED"
    assert record["confirmation"]["status"] == "PENDING"
    assert record["decision"]["status"] == "PENDING"
    assert record["decision"]["mapping_creation_requested"] is False


def test_no_usable_candidate_closes_without_mapping_request() -> None:
    record = _record(
        _selection(_candidate("sensor.zendure_system_soc", state="unavailable"))
    )

    assert record["proposal"]["status"] == "NO_ELIGIBLE_CANDIDATE"
    assert record["proposal"]["proposed_action"] == "NO_ACTION"
    assert record["decision"]["status"] == "NO_SELECTION"
    assert record["decision"]["mapping_creation_requested"] is False


def test_finished_record_is_immutable_but_pending_record_is_not() -> None:
    automatic = _record(_selection(_candidate("sensor.single")))
    pending = _record(
        _selection(_candidate("sensor.a"), _candidate("sensor.b"))
    )

    assert automatic["audit"]["immutable"] is True
    assert automatic["audit"]["completed_at"] == FIXED_TIME
    assert pending["audit"]["immutable"] is False
    assert pending["audit"]["completed_at"] is None
