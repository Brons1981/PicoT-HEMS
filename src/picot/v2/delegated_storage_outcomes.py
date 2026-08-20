"""Observer-only outcome simulation for delegated storage Candidates."""

from __future__ import annotations

from hashlib import sha256

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.v2.contracts import (
    CandidateOutcomeSet,
    CandidateSet,
    DelegatedStorageCandidateOutcome,
    EnergyPath,
    ProjectedHouseholdEnergyBalance,
    StorageEnergyRequirement,
)

METHOD_VERSION = "delegated-storage-outcome:v1"


def _stable_id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _single_requirement_and_balance(
    candidate_set: CandidateSet,
) -> tuple[StorageEnergyRequirement, ProjectedHouseholdEnergyBalance]:
    if len(candidate_set.storage_requirements) != 1:
        raise ValueError("delegated storage outcome requires exactly one requirement")
    requirement = candidate_set.storage_requirements[0]
    balances = tuple(
        balance
        for balance in candidate_set.projected_balances
        if balance.balance_id == requirement.projected_balance_id
    )
    if len(balances) != 1:
        raise ValueError("delegated storage outcome requires its projected balance")
    return requirement, balances[0]


def _simulate_path(
    candidate_set: CandidateSet,
    path: EnergyPath,
    candidate_id: str,
    requirement: StorageEnergyRequirement,
    balance: ProjectedHouseholdEnergyBalance,
) -> DelegatedStorageCandidateOutcome:
    if not path.segments:
        raise ValueError("delegated storage outcome requires timed segments")
    if any(
        segment.charge_source_policy is not ChargeSourcePolicy.PV_ONLY
        for segment in path.segments
    ):
        raise ValueError("PV-only delegated storage outcomes require PV_ONLY source policy")

    window_start = min(segment.starts_at for segment in path.segments)
    window_end = max(segment.ends_at for segment in path.segments)
    window_state = next(
        (state for state in path.projected_states if state.at == window_end),
        None,
    )
    window_start_state = next(
        (state for state in path.projected_states if state.at == window_start),
        None,
    )
    requirement_state = next(
        (
            state
            for state in path.projected_states
            if state.at == requirement.required_by
        ),
        None,
    )
    if (
        window_state is None
        or window_state.storage_energy_wh is None
        or requirement_state is None
        or requirement_state.storage_energy_wh is None
    ):
        raise ValueError("delegated storage outcome requires both projected energy states")

    window_intervals = tuple(
        interval
        for interval in balance.intervals
        if interval.starts_at >= window_start and interval.ends_at <= window_end
    )
    if not window_intervals or window_intervals[0].starts_at != window_start:
        raise ValueError("delegated storage charge window must match projected intervals")
    starting_energy_wh = (
        window_start_state.storage_energy_wh
        if window_start_state is not None
        and window_start_state.storage_energy_wh is not None
        else window_intervals[0].current_usable_storage_energy_wh
    )
    available_surplus_wh = sum(
        max(
            0.0,
            interval.expected_usable_pv_energy_wh
            - interval.household_load_forecast_energy_wh
            - interval.known_future_demand_energy_wh
            - interval.conversion_losses_wh
            - interval.other_planned_household_energy_flows_wh,
        )
        for interval in window_intervals
    )
    projected_increase_wh = max(
        0.0,
        window_state.storage_energy_wh - starting_energy_wh,
    )
    if projected_increase_wh > available_surplus_wh + 1e-9:
        raise ValueError("projected storage contribution exceeds available PV surplus")

    relevant_intervals = tuple(
        interval
        for interval in balance.intervals
        if interval.starts_at >= window_start
        and interval.ends_at <= requirement.required_by
    )
    confidence_weights = tuple(
        max(
            interval.expected_usable_pv_energy_wh
            + interval.household_load_forecast_energy_wh,
            1.0,
        )
        for interval in relevant_intervals
    )
    interval_confidence = (
        sum(
            interval.confidence * weight
            for interval, weight in zip(
                relevant_intervals,
                confidence_weights,
                strict=True,
            )
        )
        / sum(confidence_weights)
    )
    confidence = min(requirement.confidence, interval_confidence)
    requirement_satisfied = (
        requirement_state.storage_energy_wh + 1e-6
        >= requirement.required_energy_wh
    )
    evidence_ids = tuple(
        dict.fromkeys(
            requirement.evidence_ids
            + tuple(
                evidence_id
                for segment in path.segments
                for evidence_id in segment.evidence_ids
            )
            + tuple(
                evidence_id
                for interval in relevant_intervals
                for evidence_id in interval.evidence_ids
            )
        )
    )
    capability_ids = tuple(
        dict.fromkeys(segment.capability_id for segment in path.segments)
    )
    return DelegatedStorageCandidateOutcome(
        outcome_id=_stable_id(
            "candidate-outcome",
            f"{candidate_set.candidate_set_id}|{candidate_id}|{METHOD_VERSION}",
        ),
        run_id=candidate_set.run_id,
        snapshot_id=candidate_set.snapshot_id,
        candidate_id=candidate_id,
        energy_path_id=path.path_id,
        storage_requirement_id=requirement.requirement_id,
        capability_ids=capability_ids,
        charge_window_starts_at=window_start,
        charge_window_ends_at=window_end,
        storage_energy_at_window_end_wh=window_state.storage_energy_wh,
        storage_energy_at_requirement_wh=requirement_state.storage_energy_wh,
        required_energy_wh=requirement.required_energy_wh,
        pv_storage_contribution_wh=min(
            projected_increase_wh,
            available_surplus_wh,
        ),
        grid_storage_contribution_wh=0.0,
        conversion_losses_wh=sum(
            interval.conversion_losses_wh for interval in relevant_intervals
        ),
        requirement_satisfied=requirement_satisfied,
        recoverability=confidence if requirement_satisfied else 0.0,
        confidence=confidence,
        evidence_ids=evidence_ids,
        method_version=METHOD_VERSION,
    )


def simulate_pv_charge_only_outcomes(
    candidate_set: CandidateSet,
) -> CandidateOutcomeSet:
    """Simulate detailed outcomes without selecting or executing a Candidate."""

    requirement, balance = _single_requirement_and_balance(candidate_set)
    paths = {path.path_id: path for path in candidate_set.energy_paths}
    outcomes = tuple(
        _simulate_path(
            candidate_set,
            paths[candidate.energy_path_id],
            candidate.candidate_id,
            requirement,
            balance,
        )
        for candidate in candidate_set.candidates
        if candidate.family == "pv_charge_only"
    )
    return CandidateOutcomeSet(
        run_id=candidate_set.run_id,
        snapshot_id=candidate_set.snapshot_id,
        candidate_set_id=candidate_set.candidate_set_id,
        outcome_set_id=_stable_id(
            "candidate-outcome-set",
            f"{candidate_set.candidate_set_id}|{METHOD_VERSION}",
        ),
        candidate_ids=tuple(outcome.candidate_id for outcome in outcomes),
        outcomes=outcomes,
    )
