"""Observer-only delegated storage Candidate construction for V2ADR-050."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
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
    *,
    selected_window_indexes: frozenset[int] | None = None,
) -> dict[object, float]:
    required_at_end: dict[object, float] = {}
    required_after = required_energy_wh
    for index in reversed(range(len(intervals))):
        interval = intervals[index]
        required_at_end[interval.ends_at] = required_after
        demand_wh = (
            interval.household_load_forecast_energy_wh
            + interval.known_future_demand_energy_wh
            + interval.conversion_losses_wh
            + interval.other_planned_household_energy_flows_wh
        )
        usable_pv_wh = interval.expected_usable_pv_energy_wh
        if (
            selected_window_indexes is not None
            and index not in selected_window_indexes
        ):
            usable_pv_wh = min(usable_pv_wh, demand_wh)
        required_after = max(
            0.0,
            required_after
            + demand_wh
            - usable_pv_wh,
        )
    return required_at_end


def _surplus_wh(interval: ProjectedHouseholdEnergyBalanceInterval) -> float:
    return max(
        0.0,
        interval.expected_usable_pv_energy_wh
        - interval.household_load_forecast_energy_wh
        - interval.known_future_demand_energy_wh
        - interval.conversion_losses_wh
        - interval.other_planned_household_energy_flows_wh,
    )


def _surplus_windows(
    intervals: tuple[ProjectedHouseholdEnergyBalanceInterval, ...],
) -> tuple[tuple[int, ...], ...]:
    windows: list[tuple[int, ...]] = []
    current: list[int] = []
    for index, interval in enumerate(intervals):
        if _surplus_wh(interval) <= 0.0:
            if current:
                windows.append(tuple(current))
                current = []
            continue
        if (
            current
            and intervals[current[-1]].ends_at != interval.starts_at
        ):
            windows.append(tuple(current))
            current = []
        current.append(index)
    if current:
        windows.append(tuple(current))
    return tuple(windows)


def _window_selections(
    windows: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], ...]:
    selections: list[tuple[int, ...]] = []
    for width in range(1, len(windows) + 1):
        for start in range(0, len(windows) - width + 1):
            selections.append(
                tuple(
                    index
                    for window in windows[start : start + width]
                    for index in window
                )
            )
    return tuple(selections)


def _progressive_window_selections(
    intervals: tuple[ProjectedHouseholdEnergyBalanceInterval, ...],
    preferred_price_windows: tuple[tuple[datetime, datetime], ...],
) -> tuple[tuple[int, ...], ...]:
    """Order PV-only NOM windows from preferred price window to full horizon."""

    selections: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()

    def add(indexes: tuple[int, ...]) -> None:
        if indexes and indexes not in seen:
            seen.add(indexes)
            selections.append(indexes)

    for preferred_start, preferred_end in preferred_price_windows:
        preferred = tuple(
            index
            for index, interval in enumerate(intervals)
            if interval.ends_at > preferred_start
            and interval.starts_at < preferred_end
        )
        if not preferred:
            continue
        first = preferred[0]
        last = preferred[-1]
        expansions = sorted(
            (
                (
                    (first - left) + (right - last),
                    intervals[left].starts_at,
                    tuple(range(left, right + 1)),
                )
                for left in range(first, -1, -1)
                for right in range(last, len(intervals))
            ),
            key=lambda item: (item[0], item[1]),
        )
        for _, _, indexes in expansions:
            add(indexes)

    for indexes in _window_selections(_surplus_windows(intervals)):
        add(indexes)
    return tuple(selections)


def _clip_interval_to_snapshot(
    interval: ProjectedHouseholdEnergyBalanceInterval,
    snapshot: PlanningInputSnapshot,
) -> ProjectedHouseholdEnergyBalanceInterval | None:
    if interval.ends_at <= snapshot.captured_at:
        return None
    if interval.starts_at >= snapshot.captured_at:
        return interval
    full_seconds = (interval.ends_at - interval.starts_at).total_seconds()
    remaining_seconds = (
        interval.ends_at - snapshot.captured_at
    ).total_seconds()
    fraction = remaining_seconds / full_seconds
    return replace(
        interval,
        starts_at=snapshot.captured_at,
        expected_usable_pv_energy_wh=(
            interval.expected_usable_pv_energy_wh * fraction
        ),
        planned_grid_energy_wh=interval.planned_grid_energy_wh * fraction,
        household_load_forecast_energy_wh=(
            interval.household_load_forecast_energy_wh * fraction
        ),
        known_future_demand_energy_wh=(
            interval.known_future_demand_energy_wh * fraction
        ),
        conversion_losses_wh=interval.conversion_losses_wh * fraction,
        other_planned_household_energy_flows_wh=(
            interval.other_planned_household_energy_flows_wh * fraction
        ),
    )


def construct_pv_charge_only_candidate(
    *,
    snapshot: PlanningInputSnapshot,
    balance: ProjectedHouseholdEnergyBalance,
    requirement: StorageEnergyRequirement,
    preferred_price_windows: tuple[tuple[datetime, datetime], ...] = (),
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
            and any(
                primitive in item.supported_primitives
                for primitive in (
                    ExecutionPrimitive.BALANCE_CHARGE_ONLY,
                    ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                )
            )
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
    # Ordinary PV acquisition needs the bidirectional delegated controller so
    # short household-load changes are absorbed without a PicoT mode flip.
    # Charge-only remains a distinct capability for an explicit non-discharge
    # purpose (for example a later EV-charging override).
    planned_primitive = (
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL
        if ExecutionPrimitive.BALANCE_BIDIRECTIONAL
        in capability.supported_primitives
        else ExecutionPrimitive.BALANCE_CHARGE_ONLY
    )

    intervals = tuple(
        clipped
        for interval in balance.intervals
        if interval.ends_at <= requirement.required_by
        for clipped in (_clip_interval_to_snapshot(interval, snapshot),)
        if clipped is not None
    )
    candidate_balance = replace(balance, intervals=intervals)
    candidates: list[Candidate] = []
    paths: list[EnergyPath] = []
    seen_segment_windows: set[tuple[tuple[datetime, datetime], ...]] = set()
    confidence = min(
        storage.confidence,
        capability.confidence,
        requirement.confidence,
        *(interval.confidence for interval in intervals),
    )
    for window_indexes in _progressive_window_selections(
        intervals,
        preferred_price_windows,
    ):
        selected_indexes = frozenset(window_indexes)
        required_at_end = _required_energy_at_interval_end(
            intervals,
            requirement.required_energy_wh,
            selected_window_indexes=selected_indexes,
        )
        storage_energy_wh = storage.current_stored_energy_wh
        segments: list[PathSegment] = []
        projected_states: list[ProjectedEnergyState] = []
        storage_energy_at_interval_start: dict[object, float] = {}
        storage_energy_at_interval_end: dict[object, float] = {}
        acquired_energy_by_index: dict[int, float] = {}
        total_acquired_wh = 0.0
        for index, interval in enumerate(intervals):
            storage_energy_at_interval_start[interval.starts_at] = (
                storage_energy_wh
            )
            acquired_wh = 0.0
            if index in selected_indexes:
                energy_needed_wh = max(
                    0.0,
                    required_at_end[interval.ends_at] - storage_energy_wh,
                )
                acquired_wh = min(
                    _surplus_wh(interval),
                    energy_needed_wh,
                    max(0.0, storage.usable_capacity_wh - storage_energy_wh),
                )
            acquired_energy_by_index[index] = acquired_wh
            total_acquired_wh += acquired_wh
            if acquired_wh > 0.0:
                storage_energy_wh += acquired_wh
            else:
                deficit_wh = max(
                    0.0,
                    interval.household_load_forecast_energy_wh
                    + interval.known_future_demand_energy_wh
                    + interval.conversion_losses_wh
                    + interval.other_planned_household_energy_flows_wh
                    - interval.expected_usable_pv_energy_wh,
                )
                storage_energy_wh = max(0.0, storage_energy_wh - deficit_wh)
            storage_energy_at_interval_end[interval.ends_at] = storage_energy_wh

        acquisition_indexes = tuple(
            index
            for index in window_indexes
            if acquired_energy_by_index[index] > 0.0
        )
        if not acquisition_indexes or total_acquired_wh <= 0.0:
            continue
        first_acquisition_index = acquisition_indexes[0]
        last_acquisition_index = acquisition_indexes[-1]
        reserved_indexes = tuple(
            index
            for index in window_indexes
            if first_acquisition_index <= index <= last_acquisition_index
        )
        for index in reserved_indexes:
            interval = intervals[index]
            segment_id = _stable_id(
                "path-segment",
                f"{snapshot.snapshot_id}|{requirement.requirement_id}|"
                f"{intervals[first_acquisition_index].starts_at.isoformat()}|"
                f"{intervals[last_acquisition_index].ends_at.isoformat()}|"
                f"{interval.starts_at.isoformat()}|"
                f"{interval.ends_at.isoformat()}",
            )
            segments.append(
                PathSegment(
                    segment_id=segment_id,
                    order=len(segments) + 1,
                    execution_scope_id=storage.execution_scope_id,
                    starts_at=interval.starts_at,
                    ends_at=interval.ends_at,
                    primitive=planned_primitive,
                    capability_id=capability.capability_id,
                    purpose=(
                        "Reserve the progressive PV-only NOM window and "
                        "acquire available forecast PV surplus"
                    ),
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
            projected_states.append(
                ProjectedEnergyState(
                    at=interval.ends_at,
                    confidence=min(
                        storage.confidence,
                        capability.confidence,
                        requirement.confidence,
                        interval.confidence,
                    ),
                    storage_energy_wh=storage_energy_at_interval_end[
                        interval.ends_at
                    ],
                )
            )

        window_start = segments[0].starts_at
        if window_start > snapshot.captured_at:
            projected_states.insert(
                0,
                ProjectedEnergyState(
                    at=window_start,
                    confidence=confidence,
                    storage_energy_wh=storage_energy_at_interval_start[
                        window_start
                    ],
                ),
            )
        segment_window = tuple(
            (segment.starts_at, segment.ends_at) for segment in segments
        )
        if segment_window in seen_segment_windows:
            continue
        seen_segment_windows.add(segment_window)
        if projected_states[-1].at != requirement.required_by:
            projected_states.append(
                ProjectedEnergyState(
                    at=requirement.required_by,
                    confidence=confidence,
                    storage_energy_wh=storage_energy_wh,
                )
            )
        window_start = segments[0].starts_at
        window_end = segments[-1].ends_at
        path_id = _stable_id(
            "energy-path",
            f"{snapshot.snapshot_id}|{requirement.requirement_id}|"
            f"pv-charge-only|{window_start.isoformat()}|{window_end.isoformat()}",
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
        paths.append(path)
        candidates.append(
            Candidate(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                candidate_id=_stable_id("candidate", path_id),
                energy_path_id=path_id,
                family=path.family,
            )
        )

    if not candidates:
        return _not_available(
            snapshot,
            balance,
            requirement,
            "pv_surplus_window_unavailable",
        )

    return CandidateSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=_stable_id(
            "candidate-set",
            f"{snapshot.snapshot_id}|{requirement.requirement_id}|pv-charge-only",
        ),
        candidates=tuple(candidates),
        energy_paths=tuple(paths),
        projected_balances=(candidate_balance,),
        storage_requirements=(requirement,),
        derivation_status="constructed",
        derivation_reason=None,
    )
