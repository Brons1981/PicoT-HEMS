"""Durable PicoT v2 household-load observation history."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import Lock

from picot.v2.modeled_load_history import apply_reviews, read_reviews
from picot.v2.planning_input import HouseholdLoadObservation


class HouseholdLoadHistoryStore:
    """Append and restore canonical household-load observations as JSONL."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._review_keys: dict[tuple[str | None, str, float, float], None] = {}
        self._append_lock = Lock()

    def append(self, observation: HouseholdLoadObservation) -> None:
        with self._append_lock:
            self._append(observation)

    def _append(self, observation: HouseholdLoadObservation) -> None:
        fresh = [r for r in observation.modeled_reviews
                 if (observation.modeled_source_id, *r) not in self._review_keys]
        payload = {
            "schema_version": 1,
            "power_w": observation.power_w,
            "identified_external_power_w": observation.identified_external_power_w,
            "external_power_observed": observation.external_power_observed,
            "controlled_power_w": observation.controlled_power_w,
            "controlled_source_id": observation.controlled_source_id,
            "modeled_power_w": observation.modeled_power_w,
            "modeled_source_id": observation.modeled_source_id,
            "modeled_reviews": [dict(sampled_at=t, power_w=p, replaceable_power_w=r)
                                for t, p, r in fresh],
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
        for review in fresh:
            self._review_keys[(observation.modeled_source_id, *review)] = None
        while len(self._review_keys) > 4096:
            self._review_keys.pop(next(iter(self._review_keys)))

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
        return apply_reviews(observations)


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
    external = payload.get("identified_external_power_w", 0.0)
    external_observed = payload.get("external_power_observed", False)
    sampled_at = payload.get("sampled_at")
    raw_evidence_ids = payload.get("evidence_ids")
    method_version = payload.get("method_version")
    if (
        not isinstance(external_observed, bool)
        or isinstance(external, bool)
        or not isinstance(external, (int, float))
        or isinstance(power_w, bool)
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
        parsed_at = datetime.fromisoformat(sampled_at.replace("Z", "+00:00"))
        observation = HouseholdLoadObservation(
            power_w=float(power_w),
            identified_external_power_w=float(external),
            external_power_observed=external_observed,
            sampled_at=parsed_at,
            evidence_ids=tuple(evidence_ids),
            method_version=method_version,
        )
        try:
            observation = replace(observation, controlled_power_w=payload.get('controlled_power_w'),
                           controlled_source_id=payload.get('controlled_source_id'))
        except (ValueError, TypeError):
            return observation  # Bad optional attribution must not erase physical history.
        try:
            return replace(observation, modeled_power_w=payload.get("modeled_power_w"),
                           modeled_source_id=payload.get("modeled_source_id"),
                           modeled_reviews=read_reviews(payload.get("modeled_reviews"), parsed_at))
        except (ValueError, TypeError):
            return observation
    except ValueError:
        return None
