"""Durable active execution commitment state required by V2ADR-052."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from picot.architecture_ownership import architecture_ownership
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.daily_reference_charge_window import DailyMainChargeWindow
from picot.domain.energy_path import RetainedExecutionOrigin, SocConstraint
from picot.domain.execution_plan import ExecutionPlan, ExecutionPlanLifecycle, ExecutionPlanSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.daily_charge_assignment import (
    DailyChargeAssignment,
    DailyChargeRevisionReason,
    DailyChargeSegment,
    DailyMainShortfallTrigger,
    published_assignments,
)
from picot.v2.daily_pv_comparison import (
    DailyMainPVSurplusTrigger,
    DailyPVComparisonBasis,
    DailyPVComparisonState,
)

ARCHITECTURE_OWNERSHIP = architecture_ownership("plan_store", __name__)
COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v9"
COMPARISON_PREVIOUS_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v7"
MATERIALITY_PREVIOUS_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v6"
TIMING_PREVIOUS_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v5"
DEFECTIVE_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v4"
PREVIOUS_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v3"
EARLIER_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v2"
LEGACY_COMMITMENT_METHOD_VERSION = "legacy-pre-household-simulation"


@dataclass(frozen=True, slots=True)
class CommittedPlanSegment:
    """Canonical segment retained as part of the durable incumbent path."""

    starts_at: datetime
    ends_at: datetime
    primitive: str
    source_policy: str | None
    storage_export_target_wh: float | None = None

    def __post_init__(self) -> None:
        for value in (self.starts_at, self.ends_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("committed segment timestamps must be timezone-aware")
        if self.starts_at >= self.ends_at:
            raise ValueError("committed segment start must precede end")
        if not self.primitive.strip():
            raise ValueError("committed segment primitive must be explicit")
        if self.source_policy is not None and not self.source_policy.strip():
            raise ValueError("committed segment source policy must be explicit")
        if self.storage_export_target_wh is not None:
            if self.storage_export_target_wh <= 0.0:
                raise ValueError("committed export target must be positive")
            if self.primitive != "discharge_at_power":
                raise ValueError("only committed discharge may carry an export target")


@dataclass(frozen=True, slots=True)
class CommittedHouseholdLoadInterval:
    """Frozen household forecast evidence used by the admitted plan."""

    interval_id: str
    starts_at: datetime
    ends_at: datetime
    expected_energy_wh: float
    confidence: float
    source_reference: str
    method_version: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.interval_id,
                self.source_reference,
                self.method_version,
            )
        ):
            raise ValueError("committed household-load lineage must be explicit")
        for value in (self.starts_at, self.ends_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    "committed household-load timestamps must be timezone-aware"
                )
        if self.starts_at >= self.ends_at:
            raise ValueError("committed household-load interval must be positive")
        if self.expected_energy_wh < 0.0:
            raise ValueError("committed household energy must be non-negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("committed household confidence must be bounded")


@dataclass(frozen=True, slots=True)
class CommittedStorageEnergyCheckpoint:
    """Frozen lower/central/upper storage corridor for one plan checkpoint."""

    at: datetime
    lower_energy_wh: float
    central_energy_wh: float
    upper_energy_wh: float

    def __post_init__(self) -> None:
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("committed storage checkpoint must be timezone-aware")
        if not (
            0.0
            <= self.lower_energy_wh
            <= self.central_energy_wh
            <= self.upper_energy_wh
        ):
            raise ValueError("committed storage corridor must be ordered")


@dataclass(frozen=True, slots=True)
class ActivePlanCommitment:
    execution_scope_id: str
    plan_id: str
    plan_revision: int
    primitive: str
    source_policy: str
    starts_at: datetime
    ends_at: datetime
    target_energy_wh: float
    selection_method_version: str = COMMITMENT_METHOD_VERSION
    planner_id: str = "canonical"
    schedule_id: str | None = None
    worst_case_financial_result_eur: float | None = None
    average_charge_window_price_eur_per_kwh: float | None = None
    minimum_confidence: float | None = None
    reserve_respected_across_scenarios: bool | None = None
    target_held_across_scenarios: bool | None = None
    minimum_storage_energy_at_horizon_end_wh: float | None = None
    segments: tuple[CommittedPlanSegment, ...] = ()
    selection_reason: str | None = None
    replaced_plan_id: str | None = None
    selected_at: datetime | None = None
    household_load_intervals: tuple[CommittedHouseholdLoadInterval, ...] = ()
    storage_energy_checkpoints: tuple[CommittedStorageEnergyCheckpoint, ...] = ()
    candidate_family: str | None = None
    pv_preservation_dates: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.execution_scope_id,
                self.plan_id,
                self.primitive,
                self.source_policy,
                self.selection_method_version,
                self.planner_id,
            )
        ):
            raise ValueError("active plan commitment fields must be explicit")
        if self.plan_revision < 1:
            raise ValueError("plan revision must be positive")
        if self.target_energy_wh <= 0.0:
            raise ValueError("commitment target energy must be positive")
        for value in (self.starts_at, self.ends_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("commitment timestamps must be timezone-aware")
        if self.starts_at >= self.ends_at:
            raise ValueError("commitment start must precede end")
        if self.schedule_id is not None and not self.schedule_id.strip():
            raise ValueError("commitment schedule id must be explicit")
        for evidence_value in (self.selection_reason, self.replaced_plan_id):
            if evidence_value is not None and not evidence_value.strip():
                raise ValueError("commitment replacement evidence must be explicit")
        if self.candidate_family is not None and not self.candidate_family.strip():
            raise ValueError("commitment candidate family must be explicit")
        if self.selected_at is not None:
            if (
                self.selected_at.tzinfo is None
                or self.selected_at.utcoffset() is None
            ):
                raise ValueError("commitment selection time must be timezone-aware")
            if self.selected_at >= self.ends_at:
                raise ValueError("commitment selection must precede plan end")
        if (
            self.household_load_intervals or self.storage_energy_checkpoints
        ) and self.selected_at is None:
            raise ValueError("commitment monitoring baselines require selection time")
        if any(
            left.ends_at > right.starts_at
            for left, right in zip(self.segments, self.segments[1:], strict=False)
        ):
            raise ValueError("committed plan segments must not overlap")
        if self.minimum_confidence is not None and not (
            0.0 <= self.minimum_confidence <= 1.0
        ):
            raise ValueError("commitment confidence must be bounded")
        if (
            self.minimum_storage_energy_at_horizon_end_wh is not None
            and self.minimum_storage_energy_at_horizon_end_wh < 0.0
        ):
            raise ValueError("commitment horizon energy must be non-negative")
        if any(
            left.ends_at > right.starts_at
            for left, right in zip(
                self.household_load_intervals,
                self.household_load_intervals[1:],
                strict=False,
            )
        ):
            raise ValueError("committed household-load intervals must not overlap")
        checkpoint_times = tuple(
            checkpoint.at for checkpoint in self.storage_energy_checkpoints
        )
        if checkpoint_times != tuple(sorted(set(checkpoint_times))):
            raise ValueError(
                "committed storage checkpoints must be unique and ordered"
            )
        if self.pv_preservation_dates != tuple(
            sorted(set(self.pv_preservation_dates))
        ):
            raise ValueError("PV preservation dates must be unique and ordered")


def active_pv_preservation_dates(
    commitment: ActivePlanCommitment,
    *,
    captured_at: datetime,
) -> tuple[date, ...]:
    """Return active User Rule dates, including pre-DEV.235 commitments."""

    current_date = captured_at.date()
    derived = {
        segment.starts_at.date()
        for segment in commitment.segments
        if segment.primitive == "charge_at_power"
        and segment.starts_at.date() >= current_date
    }
    derived.update(
        item for item in commitment.pv_preservation_dates if item >= current_date
    )
    return tuple(sorted(derived))


class ActivePlanCommitmentStore:
    """Atomically persist at most one active commitment per execution scope."""

    def __init__(self, path: Path, *, incident_path: Path | None = None) -> None:
        self._path = path
        self._incident_path = incident_path

    def load(self, execution_scope_id: str) -> ActivePlanCommitment | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            commitments = payload["commitments"]
            raw = commitments.get(execution_scope_id)
            return _deserialize(raw) if raw is not None else None
        except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
            self._record_incident("commitment_store_unreadable", exc)
            return None

    def save(self, commitment: ActivePlanCommitment) -> None:
        payload = self._load_payload()
        serialized = asdict(commitment)
        serialized["starts_at"] = commitment.starts_at.isoformat()
        serialized["ends_at"] = commitment.ends_at.isoformat()
        serialized["selected_at"] = (
            commitment.selected_at.isoformat()
            if commitment.selected_at is not None
            else None
        )
        serialized["pv_preservation_dates"] = [
            item.isoformat() for item in commitment.pv_preservation_dates
        ]
        serialized["segments"] = [
            {
                "starts_at": segment.starts_at.isoformat(),
                "ends_at": segment.ends_at.isoformat(),
                "primitive": segment.primitive,
                "source_policy": segment.source_policy,
                "storage_export_target_wh": segment.storage_export_target_wh,
            }
            for segment in commitment.segments
        ]
        serialized["household_load_intervals"] = [
            {
                "interval_id": interval.interval_id,
                "starts_at": interval.starts_at.isoformat(),
                "ends_at": interval.ends_at.isoformat(),
                "expected_energy_wh": interval.expected_energy_wh,
                "confidence": interval.confidence,
                "source_reference": interval.source_reference,
                "method_version": interval.method_version,
            }
            for interval in commitment.household_load_intervals
        ]
        serialized["storage_energy_checkpoints"] = [
            {
                "at": checkpoint.at.isoformat(),
                "lower_energy_wh": checkpoint.lower_energy_wh,
                "central_energy_wh": checkpoint.central_energy_wh,
                "upper_energy_wh": checkpoint.upper_energy_wh,
            }
            for checkpoint in commitment.storage_energy_checkpoints
        ]
        payload["commitments"][commitment.execution_scope_id] = serialized
        self._write(payload)

    def load_daily_assignments(self) -> tuple[DailyChargeAssignment, ...]:
        """Load durable daily tasks without treating corrupt state as a new day."""
        payload = self._load_payload()
        try:
            records = payload.get("daily_assignments", {})
            if not isinstance(records, dict):
                raise ValueError("daily assignments must be an object")
            assignments = tuple(_deserialize_daily(item) for item in records.values())
            if any(key != item.assignment_id for key, item in zip(
                records, assignments, strict=True
            )):
                raise ValueError("daily assignment identity does not match its storage key")
            return assignments
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            self._record_incident("daily_charge_state_unreadable", exc)
            raise ValueError("daily charge state unreadable; refusing to recreate tasks") from exc

    def reconcile_daily_publication(
        self, *, now: datetime, timezone: str, execution_scope_id: str,
        price_intervals: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[DailyChargeAssignment, ...]:
        """Create missing daily identities once, including after an offline start.

        This entry point consumes canonical price coverage; it neither selects
        windows nor binds legacy execution segments to the new main task.
        """
        existing = self.load_daily_assignments()
        reconciled = published_assignments(
            now=now, timezone=timezone, execution_scope_id=execution_scope_id,
            price_intervals=price_intervals, existing=existing,
        )
        previous = {a.assignment_id: a for a in existing}
        additions = tuple(a for a in reconciled if a.assignment_id not in previous)
        if additions:
            payload = self._load_payload()
            records = payload.setdefault("daily_assignments", {})
            for assignment in additions:
                records[assignment.assignment_id] = _serialize_daily(assignment)
            self._write(payload)
        return reconciled

    def save_daily_assignment(self, assignment: DailyChargeAssignment) -> None:
        """Persist one lifecycle transition using the existing single-writer store.

        A stale route or duplicate publication cannot reset completion. Active
        execution-plan resets intentionally do not remove daily goal history.
        """
        existing = {a.assignment_id: a for a in self.load_daily_assignments()}
        previous = existing.get(assignment.assignment_id)
        if previous == assignment:
            return
        if previous is not None:
            if previous.completed_at is not None:
                raise ValueError("completed daily assignment cannot be overwritten")
            if assignment.created_at != previous.created_at:
                raise ValueError("daily assignment creation identity cannot be replaced")
            if assignment.revision == previous.revision:
                expected = replace(previous, completed_at=assignment.completed_at,
                                   completion_evidence_id=assignment.completion_evidence_id,
                                   completion_segment_id=assignment.completion_segment_id)
                if assignment != expected:
                    raise ValueError("route changes require a new daily revision")
            elif assignment.revision != previous.revision + 1:
                raise ValueError("stale or skipped daily assignment revision")
            elif previous.revised_at is not None and (
                assignment.revised_at is None or assignment.revised_at < previous.revised_at
            ):
                raise ValueError("daily assignment revision time cannot move backwards")
        payload = self._load_payload()
        payload.setdefault("daily_assignments", {})[assignment.assignment_id] = _serialize_daily(
            assignment
        )
        self._write(payload)

    def bind_daily_main_plan(
        self,
        *,
        plan: ExecutionPlan,
        window: DailyMainChargeWindow,
        activate: bool = False,
        optimisation_trigger: DailyMainShortfallTrigger | DailyMainPVSurplusTrigger | None = None,
        pv_comparison_basis: DailyPVComparisonBasis | None = None,
    ) -> DailyChargeAssignment:
        """Bind explicit winning source segments, never infer ownership from mode.

        The canonical Plan Builder supplies the plan and its source-path IDs.
        The full immutable execution plan and ownership are written atomically.
        This does not admit execution or complete the daily goal from a forecast.
        """
        assignment = next(
            (a for a in self.load_daily_assignments() if a.assignment_id == window.assignment_id),
            None,
        )
        if assignment is None:
            raise ValueError("daily assignment must exist before binding its winning plan")
        if plan.snapshot_id != window.projection.snapshot_id:
            raise ValueError("winning plan and main window snapshot must match")
        if plan.execution_scope_id != assignment.execution_scope_id:
            raise ValueError("winning main plan belongs to another execution scope")
        owned = {s.segment_id: s for s in window.main_segments}
        matched = tuple(s for s in plan.segments if s.source_path_segment_id in owned)
        if len(matched) != len(owned) or {s.source_path_segment_id for s in matched} != set(owned):
            raise ValueError("winning plan must preserve every explicit main source segment")
        for segment in matched:
            source = owned[segment.source_path_segment_id]
            if (segment.starts_at, segment.ends_at) != (source.starts_at, source.ends_at):
                raise ValueError("winning plan must preserve main segment boundaries")
            if segment.main_assignment_id not in (None, assignment.assignment_id):
                raise ValueError("winning main segment belongs to another daily assignment")
            if segment.retained_execution_origin is not None:
                raise ValueError("new main goal cannot claim another route's execution origin")
        main_segments = tuple(
            DailyChargeSegment(s.segment_id, s.starts_at, s.ends_at) for s in matched
        )
        same_binding = (
            assignment.route_plan_id == plan.plan_id and assignment.main_segments == main_segments
        )
        if same_binding and (plan.evaluation_id, plan.created_at) != (
            assignment.revision_evidence_id, assignment.revised_at,
        ):
            raise ValueError("winning plan does not match the stored daily revision evidence")
        if optimisation_trigger is not None:
            optimisation_trigger.validate(assignment, plan.snapshot_id, plan.created_at)
            if optimisation_trigger.target_wh != window.target_storage_energy_wh:
                raise ValueError("shortfall trigger and revised target must match")
            active_plan = self.load_active_daily_main_plan(plan.execution_scope_id)
            if active_plan is None or active_plan.plan_id != optimisation_trigger.active_plan_id:
                raise ValueError("shortfall trigger active plan has changed")
            if not activate:
                raise ValueError("a main revision must atomically activate its execution plan")
        elif assignment.revision and not same_binding:
            raise ValueError("bound daily main route requires an explicit optimisation trigger")
        if not same_binding:
            self._validate_retained_main_segments(plan, window)
        bound = assignment if same_binding else assignment.bind_main_route(
            plan_id=plan.plan_id,
            segments=main_segments,
            at=plan.created_at,
            reason=(optimisation_trigger.revision_reason if optimisation_trigger is not None
                    else DailyChargeRevisionReason.INITIAL),
            evidence_id=plan.evaluation_id,
        )
        payload = self._load_payload()
        plans = payload.setdefault("daily_execution_plans", {})
        if not isinstance(plans, dict):
            raise ValueError("daily execution plans must be an object")
        serialized = _serialize_execution_plan(plan)
        previous = plans.get(bound.assignment_id)
        if previous is not None and _deserialize_execution_plan(previous) != plan:
            if optimisation_trigger is None:
                raise ValueError("stored daily execution plan is immutable; revision required")
            history = payload.setdefault("daily_main_history", {})
            if not isinstance(history, dict):
                raise ValueError("daily main history must be an object")
            record = {"assignment": _serialize_daily(assignment), "plan": previous}
            if assignment.route_plan_id in history and history[assignment.route_plan_id] != record:
                raise ValueError("historical daily main revision is immutable")
            history[assignment.route_plan_id] = record
            triggers = payload.setdefault("daily_main_revision_triggers", {})
            triggers[plan.plan_id] = {
                **asdict(optimisation_trigger),
                "assessed_at": optimisation_trigger.assessed_at.isoformat(),
            }
        if same_binding and previous is not None:
            return bound
        pv_records = payload.setdefault("daily_pv_comparison", {})
        if pv_comparison_basis is not None:
            if assignment.revision or (
                pv_comparison_basis.assignment_id != assignment.assignment_id
                or pv_comparison_basis.snapshot_id != plan.snapshot_id
                or pv_comparison_basis.captured_at != plan.created_at
                or (pv_comparison_basis.day_starts_at, pv_comparison_basis.day_ends_at)
                != (assignment.starts_at, assignment.ends_at)
            ):
                raise ValueError("PV reference must belong to the first main binding")
            if assignment.assignment_id in pv_records:
                raise ValueError("initial PV comparison reference is immutable")
            pv_records[assignment.assignment_id] = {
                "basis": pv_comparison_basis.to_payload(), "assessed": {},
            }
        if isinstance(optimisation_trigger, DailyMainPVSurplusTrigger):
            pv_state = self.load_daily_pv_comparison(assignment.assignment_id)
            if pv_state.basis is None or pv_state.basis.basis_id != optimisation_trigger.basis_id:
                raise ValueError("PV trigger requires the saved initial reference")
            if optimisation_trigger.comparison_evidence_id in pv_state.assessed_evidence_ids:
                raise ValueError("PV comparison evidence was already assessed")
            prior_plan = self.load_active_daily_main_plan(plan.execution_scope_id)
            assert prior_plan is not None
            prior_grid = tuple(
                s for s in prior_plan.segments
                if s.main_assignment_id == assignment.assignment_id
                and s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
                and s.ends_at > plan.created_at
            )
            if any(s.requested_power_w is None for s in prior_grid) or any(
                s.requested_power_w is None for s in matched
                if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
            ):
                raise ValueError("PV revision requires explicit grid power")
            prior_grid_wh = sum(
                float(s.requested_power_w)
                * (s.ends_at - max(s.starts_at, plan.created_at)).total_seconds() / 3600
                for s in prior_grid if s.requested_power_w is not None
            )
            if abs(prior_grid_wh - optimisation_trigger.prior_grid_input_wh) > 1e-6:
                raise ValueError("PV trigger must match the active remaining grid charge")
            new_grid_wh = sum(
                float(part.requested_power_w)
                * (part.ends_at - part.starts_at).total_seconds() / 3600
                for part in matched if part.primitive is ExecutionPrimitive.CHARGE_AT_POWER
                and part.requested_power_w is not None
            )
            if new_grid_wh >= optimisation_trigger.prior_grid_input_wh - 1e-6:
                raise ValueError("PV revision must reduce the owned future grid charge")
            assessed = pv_records[assignment.assignment_id]["assessed"]
            assessed[optimisation_trigger.comparison_evidence_id] = {
                "outcome": "route_revised", "plan_id": plan.plan_id,
            }
        plans[bound.assignment_id] = serialized
        payload.setdefault("daily_assignments", {})[bound.assignment_id] = _serialize_daily(bound)
        if activate:
            active = payload.setdefault("active_daily_main_assignments", {})
            if not isinstance(active, dict):
                raise ValueError("active daily main assignments must be an object")
            active[plan.execution_scope_id] = bound.assignment_id
        self._write(payload)
        return bound

    def load_daily_pv_comparison(self, assignment_id: str) -> DailyPVComparisonState:
        """Unavailable optional comparison evidence cannot erase the main route."""
        try:
            raw = self._load_payload().get("daily_pv_comparison", {}).get(assignment_id)
            if raw is None:
                return DailyPVComparisonState(assignment_id, None,
                                              unavailable_reason="initial_reference_unavailable")
            basis = DailyPVComparisonBasis.from_payload(raw["basis"])
            if basis.assignment_id != assignment_id:
                raise ValueError("PV reference belongs to another daily assignment")
            assessed = raw["assessed"]
            if not isinstance(assessed, dict) or any(not isinstance(k, str) for k in assessed):
                raise ValueError("PV assessment history is invalid")
            return DailyPVComparisonState(assignment_id, basis, tuple(sorted(assessed)))
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
            self._record_incident("daily_pv_comparison_unreadable", exc)
            return DailyPVComparisonState(assignment_id, None,
                                          unavailable_reason="initial_reference_unreadable")

    def record_daily_pv_assessment(
        self, *, assignment_id: str, basis_id: str, evidence_id: str, outcome: str,
    ) -> None:
        state = self.load_daily_pv_comparison(assignment_id)
        if state.basis is None or state.basis.basis_id != basis_id:
            raise ValueError("PV assessment requires its saved initial reference")
        if evidence_id in state.assessed_evidence_ids:
            return
        if not evidence_id or not outcome:
            raise ValueError("PV assessment requires explicit evidence and outcome")
        payload = self._load_payload()
        assessed = payload["daily_pv_comparison"][assignment_id]["assessed"]
        assessed[evidence_id] = {"outcome": outcome}
        self._write(payload)

    def load_active_daily_main_plan(self, execution_scope_id: str) -> ExecutionPlan | None:
        """Read the explicit active pointer; never guess from plan timestamps."""
        active = self._load_payload().get("active_daily_main_assignments", {})
        if not isinstance(active, dict):
            raise ValueError("active daily main assignments must be an object")
        assignment_id = active.get(execution_scope_id)
        if assignment_id is None:
            return None
        if not isinstance(assignment_id, str):
            raise ValueError("active daily main assignment must be an identity")
        plan = self.load_daily_main_plan(assignment_id)
        if plan is None or plan.execution_scope_id != execution_scope_id:
            raise ValueError("active daily main plan scope or binding invalid")
        return plan

    def observe_daily_main_completion(
        self, *, execution_scope_id: str, plan_id: str, segment_id: str,
        confirmed_since: datetime, observed_at: datetime, measured_at: datetime,
        soc: float, evidence_id: str,
    ) -> DailyChargeAssignment | None:
        """Resolve validated execution origin after the runtime confirms the mode.

        A dispatch acknowledgement or old SOC sample is not completion evidence.
        The runtime supplies the start of its uninterrupted confirmation interval.
        """
        if not confirmed_since <= measured_at <= observed_at:
            return None
        plan = self.load_active_daily_main_plan(execution_scope_id)
        if plan is None or plan.plan_id != plan_id:
            return None
        segment = next((s for s in plan.segments if s.segment_id == segment_id), None)
        if segment is None or segment.main_assignment_id is None:
            return None
        if not segment.starts_at <= measured_at <= segment.ends_at:
            return None
        owner = next((a for a in self.load_daily_assignments()
                      if a.assignment_id == segment.main_assignment_id), None)
        if owner is None:
            raise ValueError("confirmed main segment has no daily owner")
        origin = segment.retained_execution_origin
        completed = owner.observe_completion(
            measured_at=measured_at, soc=soc, execution_allowed=True,
            plan_id=origin.plan_id if origin is not None else plan_id,
            segment_id=origin.segment_id if origin is not None else segment_id,
            evidence_id=(f"confirmed-execution:{plan_id}:{segment_id}:"
                         f"{confirmed_since.isoformat()}:{evidence_id}"),
        )
        if completed != owner:
            self.save_daily_assignment(completed)
        return completed

    def _validate_retained_main_segments(
        self, plan: ExecutionPlan, window: DailyMainChargeWindow,
    ) -> None:
        expected = {}
        for owner in self.load_daily_assignments():
            if (
                owner.assignment_id == window.assignment_id
                or owner.execution_scope_id != plan.execution_scope_id
            ):
                continue
            for main in owner.main_segments:
                if main.ends_at <= plan.valid_from or main.starts_at >= plan.valid_until:
                    continue
                original_plan = self.load_daily_main_plan(owner.assignment_id)
                assert original_plan is not None
                original = next(
                    s for s in original_plan.segments if s.segment_id == main.segment_id
                )
                expected[(original_plan.plan_id, main.segment_id)] = (owner, original)
        declared = {(r.plan_id, r.segment.segment_id): r for r in window.retained_main_segments}
        if set(declared) != set(expected):
            raise ValueError("new horizon must preserve every overlapping daily main segment")
        for key, (owner, original) in expected.items():
            reference = declared[key]
            if reference.assignment_id != owner.assignment_id or reference.segment != original:
                raise ValueError("retained main reference differs from its stored origin")
            origin = RetainedExecutionOrigin(*key)
            remaining = sorted(
                (s for s in plan.segments if s.retained_execution_origin == origin),
                key=lambda s: s.starts_at,
            )
            cursor = max(plan.valid_from, original.starts_at)
            end = min(plan.valid_until, original.ends_at)
            for segment in remaining:
                if segment.main_assignment_id != owner.assignment_id or segment.starts_at != cursor:
                    raise ValueError("retained main execution has changed ownership or a gap")
                if segment.ends_at > end or any(
                    getattr(segment, field) != getattr(original, field) for field in (
                        "primitive", "capability_id", "requested_power_w", "soc_constraint",
                        "charge_source_policy", "energy_profile_id",
                    )
                ):
                    raise ValueError("retained main execution changed without an explicit revision")
                cursor = segment.ends_at
            if cursor != end:
                raise ValueError("new horizon omits remaining main execution")
        for segment in plan.segments:
            actual_origin = segment.retained_execution_origin
            if actual_origin is None and segment.main_assignment_id not in (
                None, window.assignment_id,
            ):
                raise ValueError("other main ownership requires a verified execution origin")
            if actual_origin is not None and (
                actual_origin.plan_id, actual_origin.segment_id
            ) not in expected:
                raise ValueError("execution refers to an unverified retained main origin")

    def load_daily_main_plan(self, assignment_id: str) -> ExecutionPlan | None:
        """Recover the exact main route, without selecting or admitting execution.

        A bound assignment without its plan is an explicit recovery error, not
        permission to replace the route. Older identity-only records are kept.
        """
        assignments = self.load_daily_assignments()
        assignment = next((a for a in assignments if a.assignment_id == assignment_id), None)
        if assignment is None:
            raise ValueError("daily assignment does not exist")
        try:
            records = self._load_payload().get("daily_execution_plans", {})
            if not isinstance(records, dict):
                raise ValueError("daily execution plans must be an object")
            raw = records.get(assignment_id)
            if assignment.route_plan_id is None:
                if raw is not None:
                    raise ValueError("unbound daily assignment has an execution plan")
                return None
            if raw is None:
                raise ValueError("bound daily assignment has no stored execution plan")
            plan = _deserialize_execution_plan(raw)
            if (plan.plan_id, plan.execution_scope_id, plan.evaluation_id, plan.created_at) != (
                assignment.route_plan_id, assignment.execution_scope_id,
                assignment.revision_evidence_id, assignment.revised_at,
            ):
                raise ValueError("stored execution plan does not match daily ownership")
            segments = {s.segment_id: s for s in plan.segments}
            for main in assignment.main_segments:
                segment = segments.get(main.segment_id)
                if segment is None or (segment.starts_at, segment.ends_at) != (
                    main.starts_at, main.ends_at,
                ):
                    raise ValueError("stored execution plan does not preserve main segments")
                if segment.main_assignment_id not in (None, assignment_id):
                    raise ValueError("stored main segment belongs to another assignment")
                if segment.retained_execution_origin is not None:
                    raise ValueError("stored own main segment cannot claim a retained origin")
            for segment in plan.segments:
                origin = segment.retained_execution_origin
                if origin is None:
                    continue
                owner = next((a for a in assignments
                              if a.assignment_id == segment.main_assignment_id), None)
                if owner is None:
                    raise ValueError("stored retained main origin no longer matches its owner")
                if owner.route_plan_id == origin.plan_id:
                    original_plan = _deserialize_execution_plan(records[owner.assignment_id])
                else:
                    historical = self._load_payload().get("daily_main_history", {}).get(
                        origin.plan_id,
                    )
                    if historical is None:
                        raise ValueError("stored retained main origin has no historical revision")
                    historical_owner = _deserialize_daily(historical["assignment"])
                    original_plan = _deserialize_execution_plan(historical["plan"])
                    if (historical_owner.assignment_id != owner.assignment_id
                        or historical_owner.route_plan_id != origin.plan_id
                        or original_plan.evaluation_id != historical_owner.revision_evidence_id
                        or original_plan.created_at != historical_owner.revised_at):
                        raise ValueError("historical main revision lineage mismatch")
                    owner = historical_owner
                if original_plan.plan_id != origin.plan_id or (
                    original_plan.execution_scope_id != plan.execution_scope_id
                ):
                    raise ValueError("stored retained plan identity or scope does not match")
                original = next((s for s in original_plan.segments
                                 if s.segment_id == origin.segment_id), None)
                if original is None or not any(
                    s.segment_id == origin.segment_id for s in owner.main_segments
                ):
                    raise ValueError("stored retained origin is not an owned main segment")
                if not (
                    original.starts_at <= segment.starts_at < segment.ends_at <= original.ends_at
                ):
                    raise ValueError("stored retained main interval exceeds its original bounds")
                if any(getattr(segment, field) != getattr(original, field) for field in (
                    "primitive", "capability_id", "requested_power_w", "soc_constraint",
                    "charge_source_policy", "energy_profile_id",
                )):
                    raise ValueError("stored retained main action differs from its original")
            return plan
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            self._record_incident("daily_main_plan_unreadable", exc)
            raise ValueError(
                "daily main plan unreadable; refusing to invent a replacement"
            ) from exc

    def clear(self, execution_scope_id: str) -> None:
        payload = self._load_payload()
        if payload["commitments"].pop(execution_scope_id, None) is not None:
            self._write(payload)

    def clear_all(self) -> tuple[ActivePlanCommitment, ...]:
        """Atomically remove all commitments and return the removed records."""

        payload = self._load_payload()
        removed = tuple(
            _deserialize(item)
            for item in payload["commitments"].values()
        )
        if removed:
            payload["commitments"] = {}
            self._write(payload)
        return removed

    def record_manual_reset(
        self,
        *,
        reset_id: str,
        removed: tuple[ActivePlanCommitment, ...],
    ) -> None:
        if not reset_id.strip():
            raise ValueError("reset_id must be explicit")
        self._record_incident(
            "manual_planning_reset_requested",
            ValueError(
                json.dumps(
                    {
                        "reset_id": reset_id,
                        "removed_plan_ids": [item.plan_id for item in removed],
                        "removed_scope_ids": [
                            item.execution_scope_id for item in removed
                        ],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        )

    def record_recovery_rejection(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("recovery rejection reason must be explicit")
        self._record_incident(
            "commitment_recovery_rejected",
            ValueError(reason),
        )

    def _load_payload(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"schema_version": 1, "commitments": {}}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("commitment state must be an object")
            if payload.get("schema_version") != 1:
                raise ValueError("unsupported commitment schema")
            if not isinstance(payload.get("commitments"), dict):
                raise ValueError("commitments must be an object")
            return cast(dict[str, Any], payload)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            self._record_incident("commitment_store_write_refused", exc)
            raise ValueError("commitment state unreadable; refusing destructive reset") from exc

    def _write(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)

    def _record_incident(self, code: str, exc: Exception) -> None:
        if self._incident_path is None:
            return
        fingerprint = sha256(
            f"{code}|{type(exc).__name__}|{exc}".encode()
        ).hexdigest()[:16]
        existing = (
            self._incident_path.read_text(encoding="utf-8")
            if self._incident_path.exists()
            else ""
        )
        if f'"fingerprint":"{fingerprint}"' in existing:
            return
        self._incident_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "occurred_at": datetime.now(UTC).isoformat(),
            "code": code,
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "fingerprint": fingerprint,
        }
        with self._incident_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def _deserialize(payload: dict[str, Any]) -> ActivePlanCommitment:
    return ActivePlanCommitment(
        execution_scope_id=str(payload["execution_scope_id"]),
        plan_id=str(payload["plan_id"]),
        plan_revision=int(payload["plan_revision"]),
        primitive=str(payload["primitive"]),
        source_policy=str(payload["source_policy"]),
        starts_at=datetime.fromisoformat(payload["starts_at"]),
        ends_at=datetime.fromisoformat(payload["ends_at"]),
        target_energy_wh=float(payload["target_energy_wh"]),
        selection_method_version=str(
            payload.get(
                "selection_method_version",
                LEGACY_COMMITMENT_METHOD_VERSION,
            )
        ),
        planner_id=str(payload.get("planner_id", "canonical")),
        schedule_id=(
            str(payload["schedule_id"])
            if payload.get("schedule_id") is not None
            else None
        ),
        worst_case_financial_result_eur=(
            float(payload["worst_case_financial_result_eur"])
            if payload.get("worst_case_financial_result_eur") is not None
            else None
        ),
        average_charge_window_price_eur_per_kwh=(
            float(payload["average_charge_window_price_eur_per_kwh"])
            if payload.get("average_charge_window_price_eur_per_kwh") is not None
            else None
        ),
        minimum_confidence=(
            float(payload["minimum_confidence"])
            if payload.get("minimum_confidence") is not None
            else None
        ),
        reserve_respected_across_scenarios=(
            bool(payload["reserve_respected_across_scenarios"])
            if payload.get("reserve_respected_across_scenarios") is not None
            else None
        ),
        target_held_across_scenarios=(
            bool(payload["target_held_across_scenarios"])
            if payload.get("target_held_across_scenarios") is not None
            else None
        ),
        minimum_storage_energy_at_horizon_end_wh=(
            float(payload["minimum_storage_energy_at_horizon_end_wh"])
            if payload.get("minimum_storage_energy_at_horizon_end_wh") is not None
            else None
        ),
        segments=tuple(
            CommittedPlanSegment(
                starts_at=datetime.fromisoformat(item["starts_at"]),
                ends_at=datetime.fromisoformat(item["ends_at"]),
                primitive=str(item["primitive"]),
                source_policy=(
                    str(item["source_policy"])
                    if item.get("source_policy") is not None
                    else None
                ),
                storage_export_target_wh=(
                    float(item["storage_export_target_wh"])
                    if item.get("storage_export_target_wh") is not None
                    else None
                ),
            )
            for item in payload.get("segments", ())
        ),
        selection_reason=(
            str(payload["selection_reason"])
            if payload.get("selection_reason") is not None
            else None
        ),
        replaced_plan_id=(
            str(payload["replaced_plan_id"])
            if payload.get("replaced_plan_id") is not None
            else None
        ),
        selected_at=(
            datetime.fromisoformat(payload["selected_at"])
            if payload.get("selected_at") is not None
            else None
        ),
        household_load_intervals=tuple(
            CommittedHouseholdLoadInterval(
                interval_id=str(item["interval_id"]),
                starts_at=datetime.fromisoformat(item["starts_at"]),
                ends_at=datetime.fromisoformat(item["ends_at"]),
                expected_energy_wh=float(item["expected_energy_wh"]),
                confidence=float(item["confidence"]),
                source_reference=str(item["source_reference"]),
                method_version=str(item["method_version"]),
            )
            for item in payload.get("household_load_intervals", ())
        ),
        storage_energy_checkpoints=tuple(
            CommittedStorageEnergyCheckpoint(
                at=datetime.fromisoformat(item["at"]),
                lower_energy_wh=float(item["lower_energy_wh"]),
                central_energy_wh=float(item["central_energy_wh"]),
                upper_energy_wh=float(item["upper_energy_wh"]),
            )
            for item in payload.get("storage_energy_checkpoints", ())
        ),
        candidate_family=(
            str(payload["candidate_family"])
            if payload.get("candidate_family") is not None
            else None
        ),
        pv_preservation_dates=tuple(
            date.fromisoformat(str(item))
            for item in payload.get("pv_preservation_dates", ())
        ),
    )


def _serialize_execution_plan(plan: ExecutionPlan) -> dict[str, Any]:
    record = asdict(plan)
    for field in ("created_at", "valid_from", "valid_until"):
        record[field] = getattr(plan, field).isoformat()
    for segment in record["segments"]:
        for field in ("starts_at", "ends_at"):
            segment[field] = segment[field].isoformat()
        segment["evidence_ids"] = list(segment["evidence_ids"])
    # JSON normalization also prevents tuple/list differences from defeating
    # idempotence immediately after an on-disk round trip.
    return cast(dict[str, Any], json.loads(json.dumps(record)))


def _deserialize_execution_plan(record: dict[str, Any]) -> ExecutionPlan:
    data = dict(record)
    for field in ("created_at", "valid_from", "valid_until"):
        data[field] = datetime.fromisoformat(data[field])
    data["lifecycle"] = ExecutionPlanLifecycle(data["lifecycle"])
    segments = []
    for raw in data["segments"]:
        item = dict(raw)
        for field in ("starts_at", "ends_at"):
            item[field] = datetime.fromisoformat(item[field])
        item["primitive"] = ExecutionPrimitive(item["primitive"])
        item["charge_source_policy"] = (
            ChargeSourcePolicy(item["charge_source_policy"])
            if item["charge_source_policy"] is not None else None
        )
        item["soc_constraint"] = (
            SocConstraint(**item["soc_constraint"])
            if item["soc_constraint"] is not None else None
        )
        item["evidence_ids"] = tuple(item["evidence_ids"])
        item["retained_execution_origin"] = (
            RetainedExecutionOrigin(**item["retained_execution_origin"])
            if item.get("retained_execution_origin") is not None else None
        )
        segments.append(ExecutionPlanSegment(**item))
    data["segments"] = tuple(segments)
    return ExecutionPlan(**data)


def _serialize_daily(assignment: DailyChargeAssignment) -> dict[str, Any]:
    record = asdict(assignment)
    for key, value in record.items():
        if isinstance(value, (date, datetime)):
            record[key] = value.isoformat()
    record["main_segments"] = [
        {"segment_id": s.segment_id, "starts_at": s.starts_at.isoformat(),
         "ends_at": s.ends_at.isoformat()} for s in assignment.main_segments
    ]
    return record


def _deserialize_daily(item: dict[str, Any]) -> DailyChargeAssignment:
    return DailyChargeAssignment(
        execution_scope_id=item["execution_scope_id"],
        delivery_date=date.fromisoformat(item["delivery_date"]),
        timezone=item["timezone"], created_at=datetime.fromisoformat(item["created_at"]),
        route_plan_id=item.get("route_plan_id"),
        main_segments=tuple(DailyChargeSegment(
            segment_id=s["segment_id"], starts_at=datetime.fromisoformat(s["starts_at"]),
            ends_at=datetime.fromisoformat(s["ends_at"])
        ) for s in item.get("main_segments", ())),
        revision=item.get("revision", 0),
        revised_at=datetime.fromisoformat(item["revised_at"]) if item.get("revised_at") else None,
        revision_reason=(DailyChargeRevisionReason(item["revision_reason"])
                         if item.get("revision_reason") else None),
        revision_evidence_id=item.get("revision_evidence_id"),
        completed_at=datetime.fromisoformat(item["completed_at"])
                     if item.get("completed_at") else None,
        completion_evidence_id=item.get("completion_evidence_id"),
        completion_segment_id=item.get("completion_segment_id"),
    )
