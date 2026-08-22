"""Observer-only execution feasibility for a projected grid winner."""

from __future__ import annotations

from datetime import datetime

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import (
    CandidateOutcomeSet,
    CandidateSet,
    GridRequirementShadowEvaluation,
    GridRequirementShadowExecutionFeasibility,
    PlanningInputSnapshot,
)

METHOD_VERSION = "v2-grid-requirement-shadow-execution-feasibility:v1"


class GridRequirementShadowExecutionFeasibilityProducer:
    """Prove plan prerequisites without building or dispatching a live plan."""

    def assess(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        candidate_set: CandidateSet,
        outcomes: CandidateOutcomeSet,
        shadow: GridRequirementShadowEvaluation,
    ) -> GridRequirementShadowExecutionFeasibility:
        winner_id = shadow.projected_winning_candidate_id
        candidates = {item.candidate_id: item for item in candidate_set.candidates}
        winner = candidates.get(winner_id) if winner_id is not None else None
        if winner is None or winner.family != "grid_requirement":
            if shadow.status == "blocked":
                return self._result(
                    candidate_set.candidate_set_id,
                    None,
                    None,
                    blockers=shadow.blockers or ("shadow_evaluation_unavailable",),
                )
            return self._result(candidate_set.candidate_set_id, None, None)

        paths = {item.path_id: item for item in candidate_set.energy_paths}
        outcomes_by_id = {item.candidate_id: item for item in outcomes.outcomes}
        path = paths.get(winner.energy_path_id)
        outcome = outcomes_by_id.get(winner.candidate_id)
        blockers: list[str] = []
        segments = path.segments if path is not None else ()
        if path is None or outcome is None:
            blockers.append("grid_shadow_execution_lineage_incomplete")
        elif outcome.energy_path_id != path.path_id:
            blockers.append("grid_shadow_execution_lineage_mismatch")

        planned_primitive = (
            ExecutionPrimitive.BALANCE_CHARGE_ONLY
            if segments
            and all(
                item.primitive is ExecutionPrimitive.BALANCE_CHARGE_ONLY
                for item in segments
            )
            else None
        )
        if planned_primitive is None:
            blockers.append("grid_shadow_charge_only_primitive_unproven")
        source_policy = (
            ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT
            if segments
            and all(
                item.charge_source_policy
                is ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT
                for item in segments
            )
            else None
        )
        if source_policy is None:
            blockers.append("grid_shadow_source_policy_unproven")
        if any(item.requested_power_w is not None for item in segments):
            blockers.append("grid_shadow_direct_power_not_allowed")

        valid_from = min((item.starts_at for item in segments), default=None)
        valid_until = max((item.ends_at for item in segments), default=None)
        if outcome is not None and (
            valid_from != outcome.charge_window_starts_at
            or valid_until != outcome.charge_window_ends_at
        ):
            blockers.append("grid_shadow_execution_window_mismatch")
        grid_energy = outcome.grid_storage_contribution_wh if outcome is not None else None
        if grid_energy is None or grid_energy <= 0.0:
            blockers.append("grid_shadow_bounded_energy_missing")

        capability_ids = tuple(dict.fromkeys(item.capability_id for item in segments))
        if outcome is not None and set(capability_ids) != set(outcome.capability_ids):
            blockers.append("grid_shadow_capability_lineage_mismatch")

        planned_vendor_mode = None
        mapping_status = "not_assessed"
        evidence = snapshot.storage_mode_capability_evidence
        if evidence is None:
            mapping_status = "missing"
            blockers.append("storage_mode_capability_evidence_missing")
        elif evidence.status != "available" or planned_primitive is None:
            mapping_status = "unavailable"
            blockers.append("grid_shadow_primitive_vendor_mapping_unavailable")
        else:
            matches = tuple(
                item
                for item in evidence.mappings
                if planned_primitive in item.primitives
            )
            if len(matches) != 1:
                mapping_status = "unavailable"
                blockers.append("grid_shadow_primitive_vendor_mapping_unavailable")
            else:
                planned_vendor_mode = matches[0].vendor_mode
                mapping_status = "primitive_only"
                blockers.append("grid_source_vendor_mapping_unproven")

        return self._result(
            candidate_set.candidate_set_id,
            winner.candidate_id,
            winner.energy_path_id,
            planned_primitive=planned_primitive,
            source_policy=source_policy,
            valid_from=valid_from,
            valid_until=valid_until,
            grid_energy=grid_energy,
            capability_ids=capability_ids,
            planned_vendor_mode=planned_vendor_mode,
            mapping_status=mapping_status,
            blockers=tuple(dict.fromkeys(blockers)),
        )

    @staticmethod
    def _result(
        candidate_set_id: str,
        candidate_id: str | None,
        energy_path_id: str | None,
        *,
        planned_primitive: ExecutionPrimitive | None = None,
        source_policy: ChargeSourcePolicy | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        grid_energy: float | None = None,
        capability_ids: tuple[str, ...] = (),
        planned_vendor_mode: str | None = None,
        mapping_status: str = "not_assessed",
        blockers: tuple[str, ...] = (),
    ) -> GridRequirementShadowExecutionFeasibility:
        return GridRequirementShadowExecutionFeasibility(
            status=(
                "not_applicable"
                if candidate_id is None and not blockers
                else "blocked"
                if blockers
                else "feasible"
            ),
            candidate_set_id=candidate_set_id,
            candidate_id=candidate_id,
            energy_path_id=energy_path_id,
            planned_primitive=planned_primitive,
            charge_source_policy=source_policy,
            valid_from=valid_from,
            valid_until=valid_until,
            bounded_grid_storage_energy_wh=grid_energy,
            requested_power_w=None,
            capability_ids=capability_ids,
            planned_vendor_mode=planned_vendor_mode,
            vendor_mapping_status=mapping_status,
            blockers=blockers,
            observer_only=True,
            influences_live_execution=False,
            adapter_translation_attempted=False,
            dispatch_attempted=False,
            method_version=METHOD_VERSION,
        )
