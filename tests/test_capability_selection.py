"""Characterization tests for deterministic capability selection.

These tests describe the behaviour of the current selection proposal engine.
They intentionally do not treat its output as a persistent capability mapping.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from capability_selection import select_capabilities  # noqa: E402


def _candidate(
    entity_id: str,
    *,
    state: str = "42",
    device_id: str | None = "device-1",
    config_entry_id: str | None = "config-1",
    platform: str | None = "sensor",
    discovery_reasons: list[str] | None = None,
    semantic_status: str = "valid",
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "domain": "sensor",
        "state": state,
        "device_id": device_id,
        "config_entry_id": config_entry_id,
        "platform": platform,
        "reasons": discovery_reasons or [],
        "semantic_validation": {
            "status": semantic_status,
            "reasons": [],
        },
    }


def _select(*candidates: dict[str, Any]) -> dict[str, Any]:
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


def test_single_valid_candidate_is_selected() -> None:
    selection = _select(_candidate("sensor.zendure_system_soc"))

    assert selection["status"] == "SELECTED"
    assert selection["selected"]["entity_id"] == "sensor.zendure_system_soc"
    assert selection["eligible_candidate_count"] == 1


def test_semantically_invalid_candidate_is_never_selected() -> None:
    selection = _select(
        _candidate(
            "sensor.zendure_rated_capacity",
            semantic_status="invalid",
        )
    )

    assert selection["status"] == "NO_USABLE_CANDIDATE"
    assert selection["selected"] is None
    assert selection["candidate_audit"][0]["selection_status"] == "INELIGIBLE"


def test_unavailable_candidate_is_not_activated_during_initial_selection() -> None:
    selection = _select(
        _candidate("sensor.zendure_system_soc", state="unavailable")
    )

    assert selection["status"] == "NO_USABLE_CANDIDATE"
    assert selection["selected"] is None
    assert "state_not_usable:unavailable" in selection["candidate_audit"][0][
        "eligibility_reasons"
    ]


def test_selection_is_deterministic_when_candidates_are_otherwise_equal() -> None:
    selection = _select(
        _candidate("sensor.source_b"),
        _candidate("sensor.source_a"),
    )

    assert selection["selected"]["entity_id"] == "sensor.source_a"


def test_more_discovery_evidence_has_priority_before_entity_id_tiebreaker() -> None:
    selection = _select(
        _candidate("sensor.source_a", discovery_reasons=["matched_name"]),
        _candidate(
            "sensor.source_b",
            discovery_reasons=["matched_name", "matched_unit"],
        ),
    )

    assert selection["selected"]["entity_id"] == "sensor.source_b"


def test_all_candidates_remain_available_in_audit_output() -> None:
    selection = _select(
        _candidate("sensor.source_a"),
        _candidate("sensor.source_b"),
    )

    assert selection["candidate_count"] == 2
    assert len(selection["candidate_audit"]) == 2
    statuses = {
        record["entity_id"]: record["selection_status"]
        for record in selection["candidate_audit"]
    }
    assert statuses == {
        "sensor.source_a": "SELECTED",
        "sensor.source_b": "NOT_SELECTED",
    }
