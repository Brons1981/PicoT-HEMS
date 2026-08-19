"""Persistent diagnostic history for canonical plan changes and fallback incidents."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.planning_input import PlanningInputBundle

SCHEMA_VERSION = 1
DEFAULT_PRECEDING_POLLS = 5


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported incident value: {type(value).__name__}")


def _entity_observations(bundle: PlanningInputBundle) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for evidence in bundle.evidence:
        observations.append(
            {
                "entity_id": evidence.entity_id,
                "category": evidence.category,
                "semantic_role": evidence.semantic_role,
                "state": evidence.raw_state,
                "unit": evidence.raw_unit,
                "availability": evidence.availability,
                "observed_at": evidence.observed_at,
                "last_changed_at": evidence.last_changed_at,
                "last_updated_at": evidence.last_updated_at,
                "error": evidence.error,
                "evidence_id": evidence.evidence_id,
                "mapping_version": evidence.mapping_version,
                "price_points": [asdict(point) for point in evidence.price_points],
                "pv_energy_intervals": [
                    asdict(interval) for interval in evidence.pv_energy_intervals
                ],
            }
        )
    mode = bundle.snapshot.storage_mode_capability_evidence
    if mode is not None:
        observations.append(
            {
                "entity_id": mode.source_entity_id,
                "category": "zendure",
                "semantic_role": "storage_mode",
                "state": mode.current_vendor_mode,
                "unit": None,
                "availability": mode.status,
                "observed_at": mode.captured_at,
                "last_changed_at": None,
                "last_updated_at": None,
                "error": mode.unavailable_reason,
                "capability_id": mode.capability_id,
                "usable_vendor_modes": list(mode.usable_vendor_modes),
                "excluded_dynamic_vendor_modes": list(
                    mode.excluded_dynamic_vendor_modes
                ),
            }
        )
    return observations


def _poll_snapshot(
    bundle: PlanningInputBundle,
    run: CanonicalPipelineRun,
    *,
    local_timezone: ZoneInfo,
    runtime_diagnostics: dict[str, object] | None,
) -> dict[str, object]:
    captured_at = bundle.snapshot.captured_at
    household = bundle.snapshot.household_load_forecast
    return {
        "captured_at_utc": captured_at.astimezone(UTC).isoformat(),
        "captured_at_local": captured_at.astimezone(local_timezone).isoformat(),
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "picot_version": run.planning_input.picot_version,
        "horizon_end": run.planning_input.horizon_end,
        "entities": _entity_observations(bundle),
        "canonical_facts": [asdict(fact) for fact in bundle.facts],
        "household_load_observation": (
            asdict(bundle.household_load_observation)
            if bundle.household_load_observation is not None
            else None
        ),
        "household_load_forecast": asdict(household) if household is not None else None,
        "candidate_set": asdict(run.candidate_set),
        "outcomes": asdict(run.outcomes),
        "evaluation": asdict(run.evaluation),
        "execution_plan_set": asdict(run.execution_plan_set),
        "execution_record": asdict(run.execution_record),
        "primitive_boundary": asdict(run.primitive_boundary),
        "vendor_result": asdict(run.vendor_result),
        "runtime_diagnostics": runtime_diagnostics or {},
    }


@dataclass(slots=True)
class PlanningIncidentHistory:
    """Persist meaningful plan changes plus the complete fallback lifecycle."""

    path: Path
    preceding_poll_count: int = DEFAULT_PRECEDING_POLLS
    local_timezone_name: str = "Europe/Amsterdam"
    _polls: deque[dict[str, object]] = field(init=False)
    _active_incident_id: str | None = field(default=None, init=False)
    _active_fingerprint: str | None = field(default=None, init=False)
    _planning_outcome_fingerprint: str | None = field(default=None, init=False)
    _household_fallback_active: bool | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.preceding_poll_count < 1:
            raise ValueError("preceding_poll_count must be positive")
        self._polls = deque(maxlen=self.preceding_poll_count)
        ZoneInfo(self.local_timezone_name)

    def record(
        self,
        *,
        bundle: PlanningInputBundle,
        run: CanonicalPipelineRun,
        runtime_diagnostics: dict[str, object] | None = None,
    ) -> None:
        snapshot = _poll_snapshot(
            bundle,
            run,
            local_timezone=ZoneInfo(self.local_timezone_name),
            runtime_diagnostics=runtime_diagnostics,
        )
        household_forecast = bundle.snapshot.household_load_forecast
        planning_outcome_fingerprint = self._planning_fingerprint(run)
        if (
            run.evaluation.status != "fallback_active"
            and planning_outcome_fingerprint != self._planning_outcome_fingerprint
        ):
            self._append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event": "planning_outcome_changed",
                    "poll": snapshot,
                }
            )
            self._planning_outcome_fingerprint = planning_outcome_fingerprint
        household_fallback = bool(
            household_forecast is not None and household_forecast.fallback_active
        )
        if household_fallback and self._household_fallback_active is not True:
            self._append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event": "household_fallback_started",
                    "preceding_polls": list(self._polls),
                    "poll": snapshot,
                }
            )
        elif not household_fallback and self._household_fallback_active is True:
            self._append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event": "household_fallback_recovered",
                    "poll": snapshot,
                }
            )
        self._household_fallback_active = household_fallback
        fallback = run.evaluation.status == "fallback_active"
        fingerprint = ":".join(
            (
                run.evaluation.reason,
                run.candidate_set.derivation_status,
                run.candidate_set.derivation_reason or "none",
            )
        )
        if fallback and self._active_incident_id is None:
            self._active_incident_id = (
                f"planning-fallback-{run.planning_input.run_id}"
            )
            self._append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event": "fallback_started",
                    "incident_id": self._active_incident_id,
                    "preceding_polls": list(self._polls),
                    "poll": snapshot,
                }
            )
            self._active_fingerprint = fingerprint
        elif fallback and fingerprint != self._active_fingerprint:
            self._append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event": "fallback_cause_changed",
                    "incident_id": self._active_incident_id,
                    "poll": snapshot,
                }
            )
            self._active_fingerprint = fingerprint
        elif not fallback and self._active_incident_id is not None:
            self._append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event": "fallback_recovered",
                    "incident_id": self._active_incident_id,
                    "poll": snapshot,
                }
            )
            self._active_incident_id = None
            self._active_fingerprint = None
        self._polls.append(snapshot)

    @staticmethod
    def _planning_fingerprint(run: CanonicalPipelineRun) -> str:
        winning_candidate = next(
            (
                candidate
                for candidate in run.candidate_set.candidates
                if candidate.candidate_id == run.evaluation.winning_candidate_id
            ),
            None,
        )
        value = {
            "evaluation_status": run.evaluation.status,
            "evaluation_reason": run.evaluation.reason,
            "decisive_step": run.evaluation.decisive_step,
            "winning_family": (
                winning_candidate.family if winning_candidate is not None else None
            ),
            "plans": [
                {
                    "execution_scope_id": plan.execution_scope_id,
                    "valid_from": (
                        plan.valid_from
                        if plan.lifecycle_status.startswith("scheduled")
                        else None
                    ),
                    "valid_until": plan.valid_until,
                    "planned_primitive": plan.planned_primitive,
                    "planned_vendor_mode": plan.planned_vendor_mode,
                    "lifecycle_status": plan.lifecycle_status,
                }
                for plan in run.execution_plan_set.plans
            ],
        }
        return json.dumps(
            value,
            default=_json_value,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record, default=_json_value, separators=(",", ":"))
                + "\n"
            )
