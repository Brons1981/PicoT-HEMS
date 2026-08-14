"""Durable PicoT v2 household-load observation history."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from picot.v2.planning_input import HouseholdLoadObservation


class HouseholdLoadHistoryStore:
    """Append and restore canonical household-load observations as JSONL."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, observation: HouseholdLoadObservation) -> None:
        payload = {
            "schema_version": 1,
            "power_w": observation.power_w,
            "sampled_at": observation.sampled_at.isoformat(),
            "evidence_ids": list(observation.evidence_ids),
            "method_version": observation.method_version,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    payload,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            handle.write("\n")

    def load(self) -> tuple[HouseholdLoadObservation, ...]:
        if not self.path.exists():
            return ()

        observations: list[HouseholdLoadObservation] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

        for line in lines:
            observation = _decode_observation(line)
            if observation is not None:
                observations.append(observation)
        return tuple(observations)


def _decode_observation(
    line: str,
) -> HouseholdLoadObservation | None:
    try:
        payload: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != 1:
        return None

    power_w = payload.get("power_w")
    sampled_at = payload.get("sampled_at")
    raw_evidence_ids = payload.get("evidence_ids")
    method_version = payload.get("method_version")
    if (
        isinstance(power_w, bool)
        or not isinstance(power_w, (int, float))
        or not isinstance(sampled_at, str)
        or not isinstance(raw_evidence_ids, list)
        or not isinstance(method_version, str)
    ):
        return None

    evidence_ids: list[str] = []
    for evidence_id in raw_evidence_ids:
        if not isinstance(evidence_id, str):
            return None
        evidence_ids.append(evidence_id)

    try:
        parsed_at = datetime.fromisoformat(
            sampled_at.replace("Z", "+00:00")
        )
        return HouseholdLoadObservation(
            power_w=float(power_w),
            sampled_at=parsed_at,
            evidence_ids=tuple(evidence_ids),
            method_version=method_version,
        )
    except ValueError:
        return None
