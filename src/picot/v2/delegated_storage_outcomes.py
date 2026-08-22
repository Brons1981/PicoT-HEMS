"""Observer-only outcome simulation for delegated storage Candidates."""

from __future__ import annotations

from hashlib import sha256

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.v2.contracts import (
    CandidateOutcomeSet,
    CandidateSet,
    ConfidenceAssessment,
    ConfidenceComponent,
    DelegatedStorageCandidateOutcome,
    EnergyPath,
    ProjectedHouseholdEnergyBalance,
    StorageEnergyRequirement,
)

METHOD_VERSION = "delegated-storage-outcome:v4"
CONFIDENCE_METHOD_VERSION = "delegated-storage-outcome-confidence:v2"


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
    minimum_reserve_energy_wh: float | None,
    source_policy: ChargeSourcePolicy,
    charge_efficiency: float,
) -> DelegatedStorageCandidateOutcome:
    candidate = next(
        item
        for item in candidate_set.candidates
        if item.candidate_id == candidate_id
    )
    charge_segments = tuple(
        segment
        for segment in path.segments
        if segment.charge_source_policy is source_policy
    )
    if not charge_segments:
        if any(
            segment.charge_source_policy is not None
            for segment in path.segments
        ):
            raise ValueError(
                "delegated storage outcome requires "
                f"{source_policy.name} source policy"
            )
        raise ValueError("delegated storage outcome requires timed segments")

    window_start = min(segment.starts_at for segment in charge_segments)
    window_end = max(segment.ends_at for segment in charge_segments)
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
    projected_increase_wh = max(0.0, window_state.storage_energy_wh - starting_energy_wh)
    if (
        source_policy is ChargeSourcePolicy.PV_ONLY
        and projected_increase_wh > available_surplus_wh + 1e-9
    ):
        raise ValueError("projected storage contribution exceeds available PV surplus")
    if source_policy is ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT:
        storage_without_grid_wh = starting_energy_wh
        pv_storage_contribution_wh = 0.0
        for interval in window_intervals:
            demand_wh = (
                interval.household_load_forecast_energy_wh
                + interval.known_future_demand_energy_wh
                + interval.conversion_losses_wh
                + interval.other_planned_household_energy_flows_wh
            )
            acquired_pv_wh = max(
                0.0,
                interval.expected_usable_pv_energy_wh - demand_wh,
            )
            storage_without_grid_wh += acquired_pv_wh
            pv_storage_contribution_wh += acquired_pv_wh
        grid_storage_contribution_wh = max(
            0.0,
            window_state.storage_energy_wh - storage_without_grid_wh,
        )
        grid_charge_loss_wh = grid_storage_contribution_wh * (
            1.0 / charge_efficiency - 1.0
        )
    else:
        pv_storage_contribution_wh = min(
            projected_increase_wh,
            available_surplus_wh,
        )
        grid_storage_contribution_wh = 0.0
        grid_charge_loss_wh = 0.0

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
        if confidence_weights
        else requirement.confidence
    )
    capability_confidence = (
        path.capability_confidence
        if path.capability_confidence is not None
        else 1.0
    )
    confidence = min(
        requirement.confidence,
        interval_confidence,
        capability_confidence,
    )
    source_components: list[ConfidenceComponent] = [
        ConfidenceComponent(
            "requirement",
            requirement.confidence,
            requirement.confidence_method_version,
            requirement.evidence_ids,
        ),
        ConfidenceComponent(
            "charge_window",
            interval_confidence,
            "projected-interval-energy-weighted-confidence:v1",
            tuple(
                dict.fromkeys(
                    evidence_id
                    for interval in relevant_intervals
                    for evidence_id in interval.evidence_ids
                )
            ),
        ),
        ConfidenceComponent(
            "capability",
            capability_confidence,
            "capability-snapshot-confidence:v1",
            tuple(dict.fromkeys(segment.capability_id for segment in charge_segments)),
        ),
    ]
    for name, attribute in (
        ("storage_state", "storage_confidence"),
        ("pv_source", "pv_confidence"),
        ("household_load", "load_confidence"),
    ):
        values = tuple(
            (getattr(interval, attribute), weight)
            for interval, weight in zip(
                relevant_intervals,
                confidence_weights,
                strict=True,
            )
            if getattr(interval, attribute) is not None
        )
        if values:
            source_components.append(
                ConfidenceComponent(
                    name,
                    sum(value * weight for value, weight in values)
                    / sum(weight for _, weight in values),
                    "source-component-energy-weighted-confidence:v1",
                )
            )
    limiting_component = min(
        source_components[:3],
        key=lambda item: (item.value, item.name),
    ).name
    confidence_assessment = ConfidenceAssessment(
        result=confidence,
        limiting_component=limiting_component,
        method_version=CONFIDENCE_METHOD_VERSION,
        components=tuple(source_components),
    )
    charge_target_satisfied = (
        window_state.storage_energy_wh + 1e-6 >= requirement.required_energy_wh
    )
    reserve_energy_required_wh = (
        minimum_reserve_energy_wh
        if minimum_reserve_energy_wh is not None
        else requirement.required_energy_wh
    )
    reserve_satisfied = (
        requirement_state.storage_energy_wh + 1e-6
        >= reserve_energy_required_wh
    )
    requirement_satisfied = charge_target_satisfied and reserve_satisfied
    evidence_ids = tuple(
        dict.fromkeys(
            requirement.evidence_ids
            + tuple(
                evidence_id
                for segment in charge_segments
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
        dict.fromkeys(segment.capability_id for segment in charge_segments)
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
        pv_storage_contribution_wh=pv_storage_contribution_wh,
        grid_storage_contribution_wh=grid_storage_contribution_wh,
        conversion_losses_wh=sum(
            interval.conversion_losses_wh for interval in relevant_intervals
        )
        + grid_charge_loss_wh,
        requirement_satisfied=requirement_satisfied,
        recoverability=confidence if requirement_satisfied else 0.0,
        confidence=confidence,
        evidence_ids=evidence_ids,
        method_version=METHOD_VERSION,
        confidence_assessment=confidence_assessment,
        pv_forecast_basis=candidate.pv_forecast_basis,
        storage_energy_at_window_start_wh=starting_energy_wh,
        projected_storage_use_before_window_wh=max(
            0.0,
            balance.intervals[0].current_usable_storage_energy_wh
            - starting_energy_wh,
        ),
        required_storage_addition_wh=max(
            0.0,
            requirement.required_energy_wh - starting_energy_wh,
        ),
        charge_target_satisfied=charge_target_satisfied,
        reserve_satisfied=reserve_satisfied,
        reserve_energy_required_wh=reserve_energy_required_wh,
    )


def simulate_pv_charge_only_outcomes(
    candidate_set: CandidateSet,
    *,
    minimum_reserve_energy_wh: float | None = None,
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
            minimum_reserve_energy_wh,
            ChargeSourcePolicy.PV_ONLY,
            1.0,
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


def simulate_grid_requirement_outcomes(
    candidate_set: CandidateSet,
    *,
    charge_efficiency: float,
    minimum_reserve_energy_wh: float | None = None,
) -> CandidateOutcomeSet:
    """Simulate observer-only necessary grid-acquisition outcomes."""

    if not 0.0 < charge_efficiency <= 1.0:
        raise ValueError("charge efficiency must be between zero and one")
    requirement, balance = _single_requirement_and_balance(candidate_set)
    paths = {path.path_id: path for path in candidate_set.energy_paths}
    outcomes = tuple(
        _simulate_path(
            candidate_set,
            paths[candidate.energy_path_id],
            candidate.candidate_id,
            requirement,
            balance,
            minimum_reserve_energy_wh,
            ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT,
            charge_efficiency,
        )
        for candidate in candidate_set.candidates
        if candidate.family == "grid_requirement"
    )
    return CandidateOutcomeSet(
        run_id=candidate_set.run_id,
        snapshot_id=candidate_set.snapshot_id,
        candidate_set_id=candidate_set.candidate_set_id,
        outcome_set_id=_stable_id(
            "candidate-outcome-set",
            f"{candidate_set.candidate_set_id}|{METHOD_VERSION}|grid-requirement",
        ),
        candidate_ids=tuple(outcome.candidate_id for outcome in outcomes),
        outcomes=outcomes,
    )
