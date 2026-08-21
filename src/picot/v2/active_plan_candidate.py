"""Forecast-independent incumbent Candidate required by V2ADR-052."""

from __future__ import annotations

from hashlib import sha256

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import PathSegment, ProjectedEnergyState
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import (
    Candidate,
    ConfidenceAssessment,
    ConfidenceComponent,
    DelegatedStorageCandidateOutcome,
    EnergyPath,
    PlanningInputSnapshot,
    StorageEnergyRequirement,
)


def _id(prefix: str, seed: str) -> str:
    return f"{prefix}-{sha256(seed.encode()).hexdigest()[:16]}"


def construct_active_plan_candidate(
    snapshot: PlanningInputSnapshot,
    requirement: StorageEnergyRequirement,
) -> tuple[Candidate, EnergyPath, DelegatedStorageCandidateOutcome] | None:
    storage = next(
        (
            item
            for item in snapshot.current_storage_states
            if item.storage_state_id == requirement.storage_state_id
        ),
        None,
    )
    if storage is None:
        return None
    if storage.current_stored_energy_wh + 1e-6 >= requirement.required_energy_wh:
        return None
    commitment = next(
        (
            item
            for item in snapshot.active_plan_commitments
            if item.execution_scope_id == storage.execution_scope_id
        ),
        None,
    )
    if commitment is None:
        return None
    try:
        primitive = ExecutionPrimitive(commitment.primitive)
        source_policy = ChargeSourcePolicy(commitment.source_policy)
    except ValueError:
        return None
    capability = next(
        (
            item
            for item in (
                snapshot.capability_snapshot_set.capabilities
                if snapshot.capability_snapshot_set is not None
                else ()
            )
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
            and primitive in item.supported_primitives
        ),
        None,
    )
    if capability is None:
        return None

    starts_at = max(snapshot.captured_at, commitment.starts_at)
    segment_id = _id(
        "path-segment",
        f"{commitment.plan_id}|{commitment.plan_revision}|remaining",
    )
    path_id = _id(
        "energy-path",
        f"{snapshot.snapshot_id}|{commitment.plan_id}|{commitment.plan_revision}",
    )
    candidate_id = _id("candidate", path_id)
    evidence_ids = tuple(
        dict.fromkeys(
            (
                commitment.plan_id,
                requirement.requirement_id,
                capability.capability_id,
                *storage.evidence_ids,
            )
        )
    )
    segment = PathSegment(
        segment_id=segment_id,
        order=1,
        execution_scope_id=storage.execution_scope_id,
        starts_at=starts_at,
        ends_at=commitment.ends_at,
        primitive=primitive,
        capability_id=capability.capability_id,
        purpose="Continue the active storage-acquisition commitment",
        evidence_ids=evidence_ids,
        charge_source_policy=source_policy,
    )
    confidence = min(storage.confidence, requirement.confidence, capability.confidence)
    state_times = sorted({starts_at, commitment.ends_at, requirement.required_by})
    projected_target_wh = max(
        storage.current_stored_energy_wh,
        commitment.target_energy_wh,
    )
    states = tuple(
        ProjectedEnergyState(
            at=at,
            confidence=confidence,
            storage_energy_wh=(
                storage.current_stored_energy_wh
                if at == starts_at
                else projected_target_wh
            ),
        )
        for at in state_times
    )
    path = EnergyPath(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        path_id=path_id,
        family="pv_charge_only",
        segment_ids=(segment_id,),
        segments=(segment,),
        projected_states=states,
        capability_confidence=capability.confidence,
    )
    candidate = Candidate(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_id=candidate_id,
        energy_path_id=path_id,
        family=path.family,
    )
    requirement_satisfied = projected_target_wh + 1e-6 >= requirement.required_energy_wh
    outcome = DelegatedStorageCandidateOutcome(
        outcome_id=_id("candidate-outcome", candidate_id),
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_id=candidate_id,
        energy_path_id=path_id,
        storage_requirement_id=requirement.requirement_id,
        capability_ids=(capability.capability_id,),
        charge_window_starts_at=starts_at,
        charge_window_ends_at=commitment.ends_at,
        storage_energy_at_window_end_wh=projected_target_wh,
        storage_energy_at_requirement_wh=projected_target_wh,
        required_energy_wh=requirement.required_energy_wh,
        pv_storage_contribution_wh=max(
            0.0,
            projected_target_wh - storage.current_stored_energy_wh,
        ),
        grid_storage_contribution_wh=0.0,
        conversion_losses_wh=0.0,
        requirement_satisfied=requirement_satisfied,
        recoverability=confidence if requirement_satisfied else 0.0,
        confidence=confidence,
        evidence_ids=evidence_ids,
        method_version="active-plan-incumbent:v1",
        confidence_assessment=ConfidenceAssessment(
            result=confidence,
            limiting_component=min(
                (
                    ("storage_state", storage.confidence),
                    ("requirement", requirement.confidence),
                    ("capability", capability.confidence),
                ),
                key=lambda item: (item[1], item[0]),
            )[0],
            method_version="active-plan-incumbent-confidence:v1",
            components=(
                ConfidenceComponent(
                    "storage_state",
                    storage.confidence,
                    "storage-state-measurement-confidence:v1",
                    storage.evidence_ids,
                ),
                ConfidenceComponent(
                    "requirement",
                    requirement.confidence,
                    requirement.confidence_method_version,
                    requirement.evidence_ids,
                ),
                ConfidenceComponent(
                    "capability",
                    capability.confidence,
                    "capability-snapshot-confidence:v1",
                    (capability.capability_id,),
                ),
            ),
        ),
    )
    return candidate, path, outcome
