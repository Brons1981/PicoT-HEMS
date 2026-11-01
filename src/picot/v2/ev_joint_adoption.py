"""Main-thread publication of an explicitly accepted joint EV/battery route."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.daily_charge_assignment import DailyChargeSegment
from picot.v2.ev_joint_selection import JointEVSelection
from picot.v2.external_load_policy import SESSION_METHOD
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore, JointEVAcceptance


class JointEVAdopter:
    """No worker-thread writes and no actuator access: Store owns publication."""

    def __init__(
        self, store: ActivePlanCommitmentStore,
        conversion_model: Callable[[PlanningInputSnapshot], StorageConversionModel],
        *, execution_enabled: bool = True,
    ) -> None:
        self.store = store
        self.conversion_model = conversion_model
        self.execution_enabled = execution_enabled

    def receipt(self, selection_id: str) -> dict[str, Any] | None:
        receipt = self.store.load_joint_ev_receipt(selection_id)
        if receipt is None or not self.execution_enabled:
            return None
        active = self.store.load_active_daily_main_plan(receipt["execution_scope_id"])
        return (receipt if active is not None and active.plan_id == receipt["battery_plan_id"]
                else None)

    def adopt(
        self, selection: JointEVSelection, snapshot: PlanningInputSnapshot,
    ) -> dict[str, Any]:
        if not self.execution_enabled:
            raise ValueError("joint_ev_execution_disabled")
        previous = self.receipt(selection.selection_id)
        if previous is not None:
            return previous
        if not 0 <= (snapshot.captured_at - selection.snapshot.captured_at).total_seconds() <= 240:
            raise ValueError("joint_ev_selection_expired")
        if (not selection.selection_id or selection.starts_at is None or selection.ends_at is None
                or selection.starts_at < snapshot.captured_at
                or selection.ends_at > selection.plan.valid_until):
            raise ValueError("joint_ev_slot_requires_fresh_advice")
        active = self.store.load_active_daily_main_plan(selection.plan.execution_scope_id)
        if active is None or active.plan_id != selection.retained_plan_id:
            raise ValueError("joint_ev_battery_owner_changed")
        context = snapshot.daily_charge_context
        if context is None or context.status != "ready":
            raise ValueError("joint_ev_context_unavailable")
        policy = snapshot.external_load_policy
        already_overlaid = policy is not None and policy.session_id is not None
        if already_overlaid:
            assert policy is not None
            if (policy.session_id != selection.request["session_id"]
                    or policy.session_state != "planned" or policy.storage_support_allowed
                    or policy.planned_start != selection.starts_at
                    or policy.expected_power_w != selection.request["fixed_power_w"]
                    or policy.remaining_energy_wh != selection.request["remaining_energy_wh"]
                    or policy.expected_duration_seconds
                    != (selection.ends_at - selection.starts_at).total_seconds()
                    or not policy.physical_evidence_available
                    or not 0 <= (snapshot.captured_at - policy.measured_at).total_seconds() <= 15):
                raise ValueError("joint_ev_existing_load_requires_reconciliation")
            forecast = snapshot.household_load_forecast
            expected_power = policy.expected_power_w
            assert expected_power is not None
            covered = sum((
                min(i.battery_excluded_energy_wh,
                    expected_power * (i.ends_at - i.starts_at).total_seconds() / 3600)
                for i in forecast.intervals
                if selection.starts_at <= i.starts_at and i.ends_at <= selection.ends_at
                and i.method_version == SESSION_METHOD
            ), 0.0) if forecast is not None else 0.0
            if covered + 0.01 < float(selection.request["remaining_energy_wh"]):
                raise ValueError("joint_ev_accepted_forecast_missing")
        elif policy is not None and policy.power_w > 5:
            raise ValueError("joint_ev_existing_load_requires_reconciliation")
        # Recheck the exact winning plan against current measurements and forecasts.
        # This virtual ownership context is never persisted or treated as admission.
        from picot.v2.ev_deadline_advice import _overlay

        changed = snapshot if already_overlaid else _overlay(
            snapshot, selection.starts_at, selection.ends_at,
            float(selection.request["fixed_power_w"]), selection.plan.valid_until)
        assignments = context.assignments
        if selection.window is not None:
            if selection.trigger is None or selection.evaluation is None:
                raise ValueError("joint_ev_revision_evidence_missing")
            owner = next((a for a in self.store.load_daily_assignments()
                          if a.assignment_id == selection.window.assignment_id), None)
            if owner is None:
                raise ValueError("joint_ev_daily_owner_missing")
            selection.trigger.validate(owner, selection.plan.snapshot_id, selection.plan.created_at)
            source_ids = {s.segment_id for s in selection.window.main_segments}
            bound = owner.bind_main_route(
                plan_id=selection.plan.plan_id,
                segments=tuple(DailyChargeSegment(s.segment_id, s.starts_at, s.ends_at)
                               for s in selection.plan.segments
                               if s.source_path_segment_id in source_ids),
                at=selection.plan.created_at, reason=selection.trigger.revision_reason,
                evidence_id=selection.plan.evaluation_id,
            )
            assignments = tuple(bound if a.assignment_id == owner.assignment_id else a
                                for a in assignments)
        market_bindings = self.store.preview_retained_market_bindings(selection.plan)
        referenced = {a.route_plan_id for a in assignments}
        referenced.update(b.plan_id for b in market_bindings)
        referenced.update(context.reserve_plan_ids)
        virtual = replace(context, assignments=assignments, market_plan_bindings=market_bindings,
                          main_plans=tuple(p for p in context.main_plans
                                           if p.plan_id != selection.plan.plan_id
                                           and p.plan_id in referenced) + (selection.plan,),
                          active_main_plan_ids=(selection.plan.plan_id,))
        changed = replace(changed, daily_charge_context=virtual)
        adapter = IndependentDailyReferenceAdapter()
        conversion = self.conversion_model(changed)
        invalid = adapter.committed_execution_invalidity_reasons(
            snapshot=changed, plan=selection.plan, conversion_model=conversion)
        if invalid:
            raise ValueError("joint_ev_fresh_validation_failed:" + ";".join(invalid))
        projection, _ = adapter.committed_plan_projection(
            snapshot=changed, plan=selection.plan, conversion_model=conversion)
        if (projection.intervals[-1].storage_energy_at_end_wh + 1e-6
                < selection.terminal_storage_requirement_wh):
            raise ValueError("joint_ev_terminal_reserve_changed")
        acceptance = JointEVAcceptance(
            selection.selection_id, str(selection.request["session_id"]),
            selection.request["request_revision"], snapshot.captured_at,
        )
        if selection.window is None:
            return self.store.retain_joint_ev_plan(acceptance=acceptance, plan=selection.plan)
        self.store.bind_daily_main_plan(
            plan=selection.plan, window=selection.window, activate=True,
            optimisation_trigger=selection.trigger, joint_ev_acceptance=acceptance,
        )
        receipt = self.receipt(selection.selection_id)
        if receipt is None:
            raise ValueError("joint_ev_publication_receipt_missing")
        return receipt
