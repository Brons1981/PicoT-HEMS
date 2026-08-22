"""Observer-only delegated storage Candidate construction for V2ADR-050."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    EnergyFlowDirection,
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
    seen: set[tuple[int, ...]] = set()

    def add(indexes: tuple[int, ...]) -> None:
        if indexes and indexes not in seen:
            seen.add(indexes)
            selections.append(indexes)

    # A continuous PV-surplus period is a technical envelope, not one atomic
    # Candidate. Expose one progressive selection per possible end interval.
    # The backward storage requirement then derives the latest technically
    # minimal acquisition window for that endpoint. This provides rolling
    # alternatives without quadratic duplicate paths or Candidate price policy.
    for window in windows:
        for end in range(1, len(window) + 1):
            add(window[:end])

    # Preserve combined alternatives when the usable surplus is interrupted.
    for width in range(1, len(windows) + 1):
        for start in range(0, len(windows) - width + 1):
            add(
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


def complete_storage_path_with_baseline(
    snapshot: PlanningInputSnapshot,
    path: EnergyPath,
) -> EnergyPath:
    """Add the canonical discharge-only complement in the Candidate layer."""
    storage = next(iter(snapshot.current_storage_states), None)
    capabilities = (
        snapshot.capability_snapshot_set.capabilities
        if snapshot.capability_snapshot_set is not None
        else ()
    )
    capability = next(
        (
            item
            for item in capabilities
            if storage is not None
            and item.execution_scope_id == storage.execution_scope_id
            and item.capability_id == storage.capability_id
            and ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
            in item.supported_primitives
            and item.availability is CapabilityAvailability.AVAILABLE
            and item.health is CapabilityHealth.HEALTHY
        ),
        None,
    )
    if storage is None or capability is None or snapshot.horizon_end is None:
        return path

    horizon_start = snapshot.captured_at
    horizon_end = snapshot.horizon_end
    controlled = tuple(
        sorted(
            (
                segment
                for segment in path.segments
                if segment.ends_at > horizon_start
                and segment.starts_at < horizon_end
            ),
            key=lambda item: (item.starts_at, item.ends_at),
        )
    )
    baseline: list[PathSegment] = []
    cursor = horizon_start
    for segment in controlled:
        if cursor < segment.starts_at:
            baseline.append(
                _baseline_segment(
                    snapshot,
                    capability.capability_id,
                    storage.execution_scope_id,
                    cursor,
                    segment.starts_at,
                )
            )
        cursor = max(cursor, segment.ends_at)
    if cursor < horizon_end:
        baseline.append(
            _baseline_segment(
                snapshot,
                capability.capability_id,
                storage.execution_scope_id,
                cursor,
                horizon_end,
            )
        )
    segments = tuple(
        replace(segment, order=index)
        for index, segment in enumerate(
            sorted((*controlled, *baseline), key=lambda item: item.starts_at),
            start=1,
        )
    )
    return replace(
        path,
        segment_ids=tuple(item.segment_id for item in segments),
        segments=segments,
    )


def _baseline_segment(
    snapshot: PlanningInputSnapshot,
    capability_id: str,
    execution_scope_id: str,
    starts_at: datetime,
    ends_at: datetime,
) -> PathSegment:
    segment_id = _stable_id(
        "path-segment",
        f"{snapshot.snapshot_id}|baseline-discharge|"
        f"{starts_at.isoformat()}|{ends_at.isoformat()}",
    )
    return PathSegment(
        segment_id=segment_id,
        order=1,
        execution_scope_id=execution_scope_id,
        starts_at=starts_at,
        ends_at=ends_at,
        primitive=ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
        capability_id=capability_id,
        purpose="Apply the household baseline outside PV acquisition windows",
        evidence_ids=(capability_id,),
    )


def construct_pv_charge_only_candidate(
    *,
    snapshot: PlanningInputSnapshot,
    balance: ProjectedHouseholdEnergyBalance,
    requirement: StorageEnergyRequirement,
    preferred_price_windows: tuple[tuple[datetime, datetime], ...] = (),
    pv_forecast_basis: str = "central",
) -> CandidateSet:
    """Construct one timed PV-only delegated Candidate without selecting it."""

    if pv_forecast_basis not in {"lower", "central", "upper"}:
        raise ValueError("PV forecast basis must be lower, central, or upper")

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
    active_commitment = next(
        (
            item
            for item in snapshot.active_plan_commitments
            if item.execution_scope_id == storage.execution_scope_id
            and item.primitive == planned_primitive.value
            and item.source_policy == ChargeSourcePolicy.PV_ONLY
        ),
        None,
    )

    candidate_deadline = (
        max(requirement.required_by, active_commitment.ends_at)
        if active_commitment is not None
        else requirement.required_by
    )
    intervals = tuple(
        clipped
        for interval in balance.intervals
        if interval.ends_at <= candidate_deadline
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
    incumbent_indexes = (
        tuple(
            index
            for index, interval in enumerate(intervals)
            if active_commitment is not None
            and interval.ends_at > active_commitment.starts_at
            and interval.ends_at > snapshot.captured_at
            and interval.starts_at < active_commitment.ends_at
        )
        if active_commitment is not None
        else ()
    )
    selections = tuple(
        dict.fromkeys(
            (
                *((incumbent_indexes,) if incumbent_indexes else ()),
                *_progressive_window_selections(
                    intervals,
                    preferred_price_windows,
                ),
            )
        )
    )
    for window_indexes in selections:
        is_incumbent = bool(
            active_commitment is not None
            and window_indexes == incumbent_indexes
        )
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
        if (
            not is_incumbent
            and (not acquisition_indexes or total_acquired_wh <= 0.0)
        ):
            continue
        retained_indexes = (
            window_indexes if is_incumbent else acquisition_indexes
        )
        first_acquisition_index = retained_indexes[0]
        last_acquisition_index = retained_indexes[-1]
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
        if not any(
            state.at == requirement.required_by for state in projected_states
        ):
            projected_states.append(
                ProjectedEnergyState(
                    at=requirement.required_by,
                    confidence=confidence,
                    storage_energy_wh=(
                        storage_energy_at_interval_start[window_start]
                        if requirement.required_by <= window_start
                        else storage_energy_wh
                    ),
                )
            )
            projected_states.sort(key=lambda state: state.at)
        window_start = segments[0].starts_at
        window_end = segments[-1].ends_at
        path_id = _stable_id(
            "energy-path",
            f"{snapshot.snapshot_id}|{requirement.requirement_id}|"
            f"pv-charge-only|{pv_forecast_basis}|"
            f"{window_start.isoformat()}|{window_end.isoformat()}",
        )
        path = EnergyPath(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            path_id=path_id,
            family="pv_charge_only",
            segment_ids=tuple(segment.segment_id for segment in segments),
            segments=tuple(segments),
            projected_states=tuple(projected_states),
            capability_confidence=capability.confidence,
        )
        paths.append(path)
        candidates.append(
            Candidate(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                candidate_id=_stable_id("candidate", path_id),
                energy_path_id=path_id,
                family=path.family,
                pv_forecast_basis=pv_forecast_basis,
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


def construct_grid_requirement_candidates(
    *,
    snapshot: PlanningInputSnapshot,
    balance: ProjectedHouseholdEnergyBalance,
    requirement: StorageEnergyRequirement,
    maximum_candidates: int = 8,
) -> CandidateSet:
    """Construct bounded observer-only grid alternatives for one requirement."""

    if maximum_candidates < 1:
        raise ValueError("maximum grid Candidate count must be positive")
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
    contract = snapshot.energy_contract_snapshot
    conversion = snapshot.storage_conversion_model
    if (
        storage is None
        or capability_set is None
        or contract is None
        or conversion is None
        or not contract.permits_grid_import
    ):
        return _not_available(
            snapshot,
            balance,
            requirement,
            "grid_requirement_contract_or_conversion_unavailable",
        )
    capability = next(
        (
            item
            for item in capability_set.capabilities
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
            and item.availability is CapabilityAvailability.AVAILABLE
            and item.health is CapabilityHealth.HEALTHY
            and ExecutionPrimitive.BALANCE_CHARGE_ONLY in item.supported_primitives
            and EnergyFlowDirection.CHARGE in item.flow_directions
            and item.maximum_power_w is not None
        ),
        None,
    )
    if capability is None or capability.maximum_power_w is None:
        return _not_available(
            snapshot,
            balance,
            requirement,
            "grid_requirement_directional_charge_capability_unavailable",
        )
    intervals = tuple(
        clipped
        for interval in balance.intervals
        if interval.ends_at <= requirement.required_by
        for clipped in (_clip_interval_to_snapshot(interval, snapshot),)
        if clipped is not None
    )
    if not intervals:
        return _not_available(
            snapshot,
            balance,
            requirement,
            "grid_requirement_interval_unavailable",
        )
    prices = {
        (item.starts_at, item.ends_at): item for item in snapshot.price_points
    }
    if any((item.starts_at, item.ends_at) not in prices for item in intervals):
        return _not_available(
            snapshot,
            balance,
            requirement,
            "grid_requirement_price_evidence_unavailable",
        )
    feasible: list[tuple[float, datetime, tuple[int, ...]]] = []
    projections: dict[tuple[int, ...], tuple[float, float, float]] = {}
    for start in range(len(intervals)):
        capacity_wh = 0.0
        weighted_price = 0.0
        duration_seconds = 0.0
        for end in range(start, len(intervals)):
            interval = intervals[end]
            seconds = (interval.ends_at - interval.starts_at).total_seconds()
            capacity_wh += capability.maximum_power_w * seconds / 3600.0
            point = prices[(interval.starts_at, interval.ends_at)]
            weighted_price += point.value_eur_per_kwh * seconds
            duration_seconds += seconds
            indexes = tuple(range(start, end + 1))
            selected_indexes = frozenset(indexes)
            storage_energy_wh = storage.current_stored_energy_wh
            storage_without_grid_at_window_end_wh = storage_energy_wh
            pv_storage_wh = 0.0
            for index, projected_interval in enumerate(intervals):
                demand_wh = (
                    projected_interval.household_load_forecast_energy_wh
                    + projected_interval.known_future_demand_energy_wh
                    + projected_interval.conversion_losses_wh
                    + projected_interval.other_planned_household_energy_flows_wh
                )
                surplus_wh = max(
                    0.0,
                    projected_interval.expected_usable_pv_energy_wh - demand_wh,
                )
                deficit_wh = max(
                    0.0,
                    demand_wh - projected_interval.expected_usable_pv_energy_wh,
                )
                if index in selected_indexes:
                    acquired_pv_wh = min(
                        surplus_wh,
                        max(0.0, storage.usable_capacity_wh - storage_energy_wh),
                    )
                    storage_energy_wh += acquired_pv_wh
                    pv_storage_wh += acquired_pv_wh
                    if index == end:
                        storage_without_grid_at_window_end_wh = storage_energy_wh
                else:
                    storage_energy_wh = max(0.0, storage_energy_wh - deficit_wh)
            required_grid_storage_wh = max(
                0.0,
                requirement.required_energy_wh - storage_energy_wh,
            )
            required_grid_input_wh = (
                required_grid_storage_wh / conversion.charge_efficiency
            )
            if (
                required_grid_storage_wh > 0.0
                and capacity_wh + 1e-9 >= required_grid_input_wh
            ):
                projections[indexes] = (
                    required_grid_storage_wh,
                    storage_without_grid_at_window_end_wh,
                    pv_storage_wh,
                )
                feasible.append(
                    (
                        weighted_price / duration_seconds,
                        interval.starts_at,
                        indexes,
                    )
                )
                break
    if not feasible:
        return _not_available(
            snapshot,
            balance,
            requirement,
            "grid_requirement_not_recoverable_before_deadline",
        )
    ranked = sorted(feasible, key=lambda item: (item[0], item[1], item[2]))
    earliest = min(feasible, key=lambda item: (item[1], item[2]))
    selected = tuple(
        dict.fromkeys(
            item[2] for item in (*ranked[:maximum_candidates], earliest)
        )
    )
    candidates: list[Candidate] = []
    paths: list[EnergyPath] = []
    confidence = min(
        storage.confidence,
        capability.confidence,
        requirement.confidence,
        *(interval.confidence for interval in intervals),
        *(prices[(item.starts_at, item.ends_at)].confidence for item in intervals),
    )
    for indexes in selected:
        first = intervals[indexes[0]]
        last = intervals[indexes[-1]]
        (
            required_grid_storage_wh,
            storage_without_grid_at_window_end_wh,
            _,
        ) = projections[indexes]
        segment_id = _stable_id(
            "path-segment",
            f"{snapshot.snapshot_id}|{requirement.requirement_id}|grid-requirement|"
            f"{first.starts_at.isoformat()}|{last.ends_at.isoformat()}",
        )
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    requirement.requirement_id,
                    capability.capability_id,
                    contract.contract_snapshot_id,
                    conversion.model_id,
                    *(
                        evidence_id
                        for index in indexes
                        for evidence_id in intervals[index].evidence_ids
                    ),
                    *(
                        prices[
                            (intervals[index].starts_at, intervals[index].ends_at)
                        ].evidence_id
                        for index in indexes
                    ),
                )
            )
        )
        segment = PathSegment(
            segment_id=segment_id,
            order=1,
            execution_scope_id=storage.execution_scope_id,
            starts_at=first.starts_at,
            ends_at=last.ends_at,
            primitive=ExecutionPrimitive.BALANCE_CHARGE_ONLY,
            capability_id=capability.capability_id,
            purpose="Acquire the named storage requirement with bounded grid energy",
            evidence_ids=evidence_ids,
            requested_power_w=None,
            charge_source_policy=ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT,
        )
        window_end_energy_wh = min(
            storage.usable_capacity_wh,
            storage_without_grid_at_window_end_wh + required_grid_storage_wh,
        )
        states = [
            ProjectedEnergyState(
                at=first.starts_at,
                confidence=confidence,
                storage_energy_wh=first.current_usable_storage_energy_wh,
            ),
            ProjectedEnergyState(
                at=last.ends_at,
                confidence=confidence,
                storage_energy_wh=window_end_energy_wh,
            ),
        ]
        if last.ends_at < requirement.required_by:
            states.append(
                ProjectedEnergyState(
                    at=requirement.required_by,
                    confidence=confidence,
                    storage_energy_wh=requirement.required_energy_wh,
                )
            )
        path_id = _stable_id(
            "energy-path",
            f"{snapshot.snapshot_id}|{requirement.requirement_id}|grid-requirement|"
            f"{first.starts_at.isoformat()}|{last.ends_at.isoformat()}",
        )
        path = EnergyPath(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            path_id=path_id,
            family="grid_requirement",
            segment_ids=(segment.segment_id,),
            segments=(segment,),
            projected_states=tuple(states),
            capability_confidence=capability.confidence,
        )
        paths.append(path)
        candidates.append(
            Candidate(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                candidate_id=_stable_id("candidate", path_id),
                energy_path_id=path_id,
                family=path.family,
                pv_forecast_basis="lower",
            )
        )
    return CandidateSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=_stable_id(
            "candidate-set",
            f"{snapshot.snapshot_id}|{requirement.requirement_id}|grid-requirement",
        ),
        candidates=tuple(candidates),
        energy_paths=tuple(paths),
        projected_balances=(replace(balance, intervals=intervals),),
        storage_requirements=(requirement,),
        derivation_status="constructed",
        derivation_reason=None,
    )
