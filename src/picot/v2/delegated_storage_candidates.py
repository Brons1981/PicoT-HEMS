"""Observer-only delegated storage Candidate construction for V2ADR-050."""

from __future__ import annotations

from hashlib import sha256

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
)
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import PathSegment, ProjectedEnergyState
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import (
    Candidate,
    CandidateSet,
    EnergyPath,
    PlanningInputSnapshot,
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
)


def _stable_id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _not_available(
    snapshot: PlanningInputSnapshot,
    balance: ProjectedHouseholdEnergyBalance,
    requirement: StorageEnergyRequirement,
    reason: str,
) -> CandidateSet:
    return CandidateSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=_stable_id(
            "candidate-set",
            f"{snapshot.snapshot_id}|{requirement.requirement_id}|pv-charge-only",
        ),
        candidates=(),
        energy_paths=(),
        projected_balances=(balance,),
        storage_requirements=(requirement,),
        derivation_status="not_available",
        derivation_reason=reason,
    )


def _required_energy_at_interval_end(
    intervals: tuple[ProjectedHouseholdEnergyBalanceInterval, ...],
    required_energy_wh: float,
) -> dict[object, float]:
    required_at_end: dict[object, float] = {}
    required_after = required_energy_wh
    for interval in reversed(intervals):
        required_at_end[interval.ends_at] = required_after
        required_after = max(
            0.0,
            required_after
            + interval.household_load_forecast_energy_wh
            + interval.known_future_demand_energy_wh
            + interval.conversion_losses_wh
            + interval.other_planned_household_energy_flows_wh
            - interval.expected_usable_pv_energy_wh,
        )
    return required_at_end


def construct_pv_charge_only_candidate(
    *,
    snapshot: PlanningInputSnapshot,
    balance: ProjectedHouseholdEnergyBalance,
    requirement: StorageEnergyRequirement,
) -> CandidateSet:
    """Construct one timed PV-only delegated Candidate without selecting it."""

    if (
        balance.run_id != snapshot.run_id
        or balance.snapshot_id != snapshot.snapshot_id
        or requirement.run_id != snapshot.run_id
        or requirement.snapshot_id != snapshot.snapshot_id
        or requirement.projected_balance_id != balance.balance_id
    ):
        raise ValueError("storage Candidate lineage must match Planning Input")

    storage = next(
        (
            item
            for item in snapshot.current_storage_states
            if item.storage_state_id == requirement.storage_state_id
        ),
        None,
    )
    capability_set = snapshot.capability_snapshot_set
    if storage is None or capability_set is None:
        return _not_available(
            snapshot,
            balance,
            requirement,
            "balance_charge_only_unavailable",
        )
    capability = next(
        (
            item
            for item in capability_set.capabilities
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
            and item.availability is CapabilityAvailability.AVAILABLE
            and item.health is CapabilityHealth.HEALTHY
            and ExecutionPrimitive.BALANCE_CHARGE_ONLY
            in item.supported_primitives
        ),
        None,
    )
    if capability is None:
        return _not_available(
            snapshot,
            balance,
            requirement,
            "balance_charge_only_unavailable",
        )

    intervals = tuple(
        interval
        for interval in balance.intervals
        if interval.starts_at >= snapshot.captured_at
        and interval.ends_at <= requirement.required_by
    )
    required_at_end = _required_energy_at_interval_end(
        intervals,
        requirement.required_energy_wh,
    )
    storage_energy_wh = storage.current_stored_energy_wh
    segments: list[PathSegment] = []
    projected_states: list[ProjectedEnergyState] = []

    for interval in intervals:
        surplus_wh = max(
            0.0,
            interval.expected_usable_pv_energy_wh
            - interval.household_load_forecast_energy_wh
            - interval.known_future_demand_energy_wh
            - interval.conversion_losses_wh
            - interval.other_planned_household_energy_flows_wh,
        )
        energy_needed_wh = max(
            0.0,
            required_at_end[interval.ends_at] - storage_energy_wh,
        )
        acquired_wh = min(surplus_wh, energy_needed_wh)
        if acquired_wh > 0.0:
            segment_id = _stable_id(
                "path-segment",
                f"{snapshot.snapshot_id}|{requirement.requirement_id}|"
                f"{interval.starts_at.isoformat()}|{interval.ends_at.isoformat()}",
            )
            segments.append(
                PathSegment(
                    segment_id=segment_id,
                    order=len(segments) + 1,
                    execution_scope_id=storage.execution_scope_id,
                    starts_at=interval.starts_at,
                    ends_at=interval.ends_at,
                    primitive=ExecutionPrimitive.BALANCE_CHARGE_ONLY,
                    capability_id=capability.capability_id,
                    purpose="Acquire required storage energy from forecast PV surplus",
                    evidence_ids=tuple(
                        dict.fromkeys(
                            (requirement.requirement_id,)
                            + interval.evidence_ids
                            + (capability.capability_id,)
                        )
                    ),
                    requested_power_w=None,
                    charge_source_policy=ChargeSourcePolicy.PV_ONLY,
                )
            )
            storage_energy_wh += acquired_wh
            projected_states.append(
                ProjectedEnergyState(
                    at=interval.ends_at,
                    confidence=min(
                        storage.confidence,
                        capability.confidence,
                        requirement.confidence,
                        interval.confidence,
                    ),
                    storage_energy_wh=storage_energy_wh,
                )
            )
            continue

        deficit_wh = max(
            0.0,
            interval.household_load_forecast_energy_wh
            + interval.known_future_demand_energy_wh
            + interval.conversion_losses_wh
            + interval.other_planned_household_energy_flows_wh
            - interval.expected_usable_pv_energy_wh,
        )
        storage_energy_wh = max(0.0, storage_energy_wh - deficit_wh)

    if not segments:
        return _not_available(
            snapshot,
            balance,
            requirement,
            "pv_surplus_window_unavailable",
        )

    confidence = min(
        storage.confidence,
        capability.confidence,
        requirement.confidence,
        *(interval.confidence for interval in intervals),
    )
    if not projected_states or projected_states[-1].at != requirement.required_by:
        projected_states.append(
            ProjectedEnergyState(
                at=requirement.required_by,
                confidence=confidence,
                storage_energy_wh=storage_energy_wh,
            )
        )
    path_id = _stable_id(
        "energy-path",
        f"{snapshot.snapshot_id}|{requirement.requirement_id}|pv-charge-only",
    )
    path = EnergyPath(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        path_id=path_id,
        family="pv_charge_only",
        segment_ids=tuple(segment.segment_id for segment in segments),
        segments=tuple(segments),
        projected_states=tuple(projected_states),
    )
    candidate = Candidate(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_id=_stable_id("candidate", path_id),
        energy_path_id=path_id,
        family=path.family,
    )
    return CandidateSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=_stable_id(
            "candidate-set",
            f"{snapshot.snapshot_id}|{requirement.requirement_id}|pv-charge-only",
        ),
        candidates=(candidate,),
        energy_paths=(path,),
        projected_balances=(balance,),
        storage_requirements=(requirement,),
        derivation_status="constructed",
        derivation_reason=None,
    )
