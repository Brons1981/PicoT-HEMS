"""Observer-only hard admission for necessary grid-supported acquisition."""

from __future__ import annotations

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import (
    Candidate,
    CandidateOutcomeSet,
    CandidateSet,
    DelegatedStorageCandidateOutcome,
    EnergyPath,
    GridRequirementAdmissionCondition,
    GridRequirementAdmissionSet,
    GridRequirementCandidateAdmission,
    PlanningInputSnapshot,
    ReferenceCandidateSimulation,
    StorageEnergyRequirement,
)

METHOD_VERSION = "v2-grid-requirement-admission:v1"


class GridRequirementAdmissionProducer:
    """Evaluate hard evidence without selecting or dispatching a Candidate."""

    def assess(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        candidate_set: CandidateSet,
        outcomes: CandidateOutcomeSet,
        observations: tuple[ReferenceCandidateSimulation, ...],
    ) -> GridRequirementAdmissionSet:
        grid_candidates = tuple(
            item for item in candidate_set.candidates if item.family == "grid_requirement"
        )
        if not grid_candidates:
            return GridRequirementAdmissionSet(
                candidate_set_id=candidate_set.candidate_set_id,
                status="not_applicable",
                assessments=(),
                observer_only=True,
                influences_live_selection=False,
                method_version=METHOD_VERSION,
            )
        paths = {item.path_id: item for item in candidate_set.energy_paths}
        outcome_by_id = {item.candidate_id: item for item in outcomes.outcomes}
        observation_by_id = {item.candidate_id: item for item in observations}
        requirements = {
            item.requirement_id: item for item in candidate_set.storage_requirements
        }
        capabilities = {
            item.capability_id: item
            for item in (
                snapshot.capability_snapshot_set.capabilities
                if snapshot.capability_snapshot_set is not None
                else ()
            )
        }
        assessments = tuple(
            self._candidate(
                snapshot=snapshot,
                candidate=candidate,
                path=paths.get(candidate.energy_path_id),
                outcome=outcome_by_id.get(candidate.candidate_id),
                observation=observation_by_id.get(candidate.candidate_id),
                candidate_set=candidate_set,
                all_outcomes=outcomes,
                requirements=requirements,
                capabilities=capabilities,
            )
            for candidate in grid_candidates
        )
        return GridRequirementAdmissionSet(
            candidate_set_id=candidate_set.candidate_set_id,
            status="ready",
            assessments=assessments,
            observer_only=True,
            influences_live_selection=False,
            method_version=METHOD_VERSION,
        )

    def _candidate(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        candidate: Candidate,
        path: EnergyPath | None,
        outcome: DelegatedStorageCandidateOutcome | None,
        observation: ReferenceCandidateSimulation | None,
        candidate_set: CandidateSet,
        all_outcomes: CandidateOutcomeSet,
        requirements: dict[str, StorageEnergyRequirement],
        capabilities: dict[str, LogicalCapabilitySnapshot],
    ) -> GridRequirementCandidateAdmission:
        path_value = path
        outcome_value = outcome
        requirement = (
            requirements.get(outcome_value.storage_requirement_id)
            if outcome_value is not None
            else None
        )
        storage_requirement_id = (
            outcome_value.storage_requirement_id if outcome_value is not None else "missing"
        )
        conditions: list[GridRequirementAdmissionCondition] = []

        def add(name: str, passed: bool, evidence: tuple[str, ...], blocker: str) -> None:
            conditions.append(
                GridRequirementAdmissionCondition(
                    condition=name,
                    satisfied=passed,
                    evidence_ids=tuple(dict.fromkeys(evidence)),
                    blocker=None if passed else blocker,
                )
            )

        requirement_ok = (
            requirement is not None
            and outcome_value is not None
            and snapshot.horizon_end is not None
            and snapshot.captured_at < requirement.required_by <= snapshot.horizon_end
        )
        add(
            "named_requirement_and_deadline",
            requirement_ok,
            (storage_requirement_id,),
            "named_requirement_or_deadline_missing",
        )
        pv_outcomes = tuple(
            item
            for item in all_outcomes.outcomes
            if item.storage_requirement_id == storage_requirement_id
            and item.candidate_id != candidate.candidate_id
            and item.grid_storage_contribution_wh == 0.0
        )
        pv_derivation_evidence = (
            (candidate_set.pv_forecast_assumption_set.assumption_set_id,)
            if candidate_set.derivation_status == "ready"
            and candidate_set.pv_forecast_assumption_set is not None
            else ()
        )
        pv_evaluated = bool(pv_outcomes or pv_derivation_evidence)
        add(
            "pv_only_feasibility_and_recoverability_evaluated",
            pv_evaluated,
            tuple(item.outcome_id for item in pv_outcomes) + pv_derivation_evidence,
            "pv_only_feasibility_or_recoverability_missing",
        )
        grid_justified = (
            outcome_value is not None
            and outcome_value.grid_storage_contribution_wh > 0.0
            and pv_evaluated
            and not any(item.requirement_satisfied for item in pv_outcomes)
        )
        add(
            "adr037_grid_use_justified",
            grid_justified,
            tuple(item.outcome_id for item in pv_outcomes) + pv_derivation_evidence,
            "adr037_grid_use_not_justified",
        )
        shortfall_bounded = (
            outcome_value is not None
            and outcome_value.required_storage_addition_wh is not None
            and outcome_value.grid_storage_contribution_wh > 0.0
            and outcome_value.pv_storage_contribution_wh
            + outcome_value.grid_storage_contribution_wh
            <= outcome_value.required_storage_addition_wh + 1e-6
        )
        add(
            "grid_energy_bounded_to_requirement_shortfall",
            shortfall_bounded,
            (outcome_value.outcome_id,) if outcome_value is not None else (),
            "grid_energy_exceeds_or_lacks_requirement_shortfall",
        )
        grid_segments = tuple(
            item
            for item in (path_value.segments if path_value is not None else ())
            if item.charge_source_policy
            is ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT
        )
        add(
            "required_grid_source_policy",
            bool(grid_segments),
            tuple(item.segment_id for item in grid_segments),
            "required_grid_source_policy_missing",
        )
        contract_ok = (
            snapshot.energy_contract_snapshot is not None
            and snapshot.energy_contract_snapshot.permits_grid_import
        )
        add(
            "contract_permits_grid_import",
            contract_ok,
            (
                (snapshot.energy_contract_snapshot.contract_snapshot_id,)
                if snapshot.energy_contract_snapshot is not None
                else ()
            ),
            "grid_import_permission_missing",
        )
        storage_capabilities = tuple(
            capabilities.get(item)
            for item in (outcome_value.capability_ids if outcome_value is not None else ())
        )
        storage_ok = bool(storage_capabilities) and all(
            item is not None
            and item.availability is CapabilityAvailability.AVAILABLE
            and item.health is CapabilityHealth.HEALTHY
            and ExecutionPrimitive.BALANCE_CHARGE_ONLY in item.supported_primitives
            and EnergyFlowDirection.CHARGE in item.flow_directions
            and item.maximum_power_w is not None
            and item.minimum_soc is not None
            and item.maximum_soc is not None
            for item in storage_capabilities
        )
        add(
            "storage_charge_limits_proven",
            storage_ok,
            tuple(item for item in (outcome_value.capability_ids if outcome_value else ())),
            "storage_charge_limit_evidence_missing",
        )
        reserve_ok = outcome_value is not None and outcome_value.reserve_satisfied is True
        add(
            "minimum_reserve_preserved",
            reserve_ok,
            (outcome_value.outcome_id,) if outcome_value is not None else (),
            "minimum_reserve_not_proven",
        )
        grid_interfaces = tuple(
            item
            for item in capabilities.values()
            if item.role is CapabilityRole.GRID_INTERFACE
            and EnergyFlowDirection.CONSUME in item.flow_directions
            and item.maximum_power_w is not None
            and item.availability is CapabilityAvailability.AVAILABLE
            and item.health is CapabilityHealth.HEALTHY
        )
        connection_ok = (
            bool(grid_interfaces)
            and observation is not None
            and observation.ledger is not None
        )
        if connection_ok:
            limit_w = min(item.maximum_power_w for item in grid_interfaces if item.maximum_power_w)
            assert observation is not None and observation.ledger is not None
            connection_ok = all(
                interval.grid_import_wh
                <= limit_w
                * (interval.ends_at - interval.starts_at).total_seconds()
                / 3600.0
                + 1e-6
                for interval in observation.ledger.intervals
            )
        add(
            "connection_limit_respected",
            connection_ok,
            tuple(item.capability_id for item in grid_interfaces),
            "connection_limit_missing_or_exceeded",
        )
        scope_ids = {
            item.execution_scope_id for item in grid_segments
        }
        conflicting = tuple(
            item
            for item in snapshot.active_plan_commitments
            if item.execution_scope_id in scope_ids
        )
        add(
            "active_commitments_preserved",
            not conflicting,
            tuple(item.plan_id for item in conflicting) or ("no-active-conflict",),
            "active_commitment_conflict",
        )
        complete = (
            observation is not None
            and observation.status == "ready"
            and observation.ledger is not None
            and observation.financial_settlement is not None
            and snapshot.horizon_end is not None
            and observation.ledger.horizon_start == snapshot.captured_at
            and observation.ledger.horizon_end == snapshot.horizon_end
        )
        add(
            "complete_ledger_settlement_and_horizon",
            complete,
            (
                (observation.ledger.ledger_id, observation.financial_settlement.settlement_id)
                if complete
                and observation is not None
                and observation.ledger is not None
                and observation.financial_settlement is not None
                else ()
            ),
            "complete_ledger_settlement_or_horizon_missing",
        )
        evidence_fresh = (
            snapshot.capability_snapshot_set is not None
            and snapshot.capability_snapshot_set.captured_at == snapshot.captured_at
            and snapshot.energy_contract_snapshot is not None
            and snapshot.energy_contract_snapshot.captured_at == snapshot.captured_at
            and all(
                item is not None and item.fresh_at == snapshot.captured_at
                for item in storage_capabilities
            )
            and all(item.fresh_at == snapshot.captured_at for item in grid_interfaces)
            and observation is not None
            and observation.candidate_id == candidate.candidate_id
            and observation.energy_path_id == candidate.energy_path_id
        )
        add(
            "evidence_fresh_and_lineage_consistent",
            evidence_fresh,
            tuple(
                dict.fromkeys(
                    (
                        snapshot.snapshot_id,
                        *(
                            item.capability_id
                            for item in storage_capabilities
                            if item is not None
                        ),
                        *(item.capability_id for item in grid_interfaces),
                    )
                )
            ),
            "admission_evidence_stale_or_contradictory",
        )
        blockers = tuple(
            item.blocker
            for item in conditions
            if not item.satisfied and item.blocker is not None
        )
        return GridRequirementCandidateAdmission(
            candidate_id=candidate.candidate_id,
            energy_path_id=candidate.energy_path_id,
            storage_requirement_id=storage_requirement_id,
            status="admissible" if not blockers else "blocked",
            conditions=tuple(conditions),
            blockers=blockers,
            observer_only=True,
            method_version=METHOD_VERSION,
        )
