"""Capability discovery for PicoT HEMS.

Scaffold for step 2.6.2.
"""

from __future__ import annotations

from typing import Any


def discover_capabilities(structure: dict[str, list[dict[str, Any]]], states: list[dict[str, Any]]) -> dict[str, Any]:
    """Return an empty capability model scaffold.

    Full candidate resolution will be added in subsequent commits.
    """
    return {
        "metadata": {
            "schema": "picot_hems.capability.discovery",
            "schema_version": "0.1.0",
            "method": "deterministic_rules"
        },
        "capabilities": [],
        "summary": {
            "capability_count": 0,
            "candidate_count": 0
        }
    }
