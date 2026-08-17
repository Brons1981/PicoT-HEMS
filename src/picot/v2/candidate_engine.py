"""Candidate Engine derivations for the PicoT v2 canonical pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from picot.v2.contracts import (
    PlanningGap,
    PlanningInputSnapshot,
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
)


def _stable_id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


class CandidateInputError(ValueError):
    """Expected Candidate Engine input insufficiency."""


@dataclass(frozen=True, slots=True)
class StorageRequirementDerivation:
    """Canonical projected balances and matching storage requirements."""

    balances: tuple[ProjectedHouseholdEnergyBalance, ...]
    requirements: tuple[StorageEnergyRequirement, ...]
    planning_gaps: tuple[PlanningGap, ...] = ()


class CandidateEngine:
    """Derive Candidate inputs without selecting or executing a path."""

    def derive_storage_requirements(
        self,
        snapshot: PlanningInputSnapshot,
    ) -> StorageRequirementDerivation:
        """Derive conservative ADR-037 requirements from one snapshot."""
        if snapshot.horizon_end is None:
            raise CandidateInputError("planning horizon is required")
        if snapshot.household_load_forecast is None:
            raise CandidateInputError("household load forecast is required")
        if snapshot.pv_energy_timeline is None:
            raise CandidateInputError("PV energy timeline is required")

        load_intervals = snapshot.household_load_forecast.intervals
        pv_intervals = snapshot.pv_energy_timeline.intervals

        balances: list[ProjectedHouseholdEnergyBalance] = []
        requirements: list[StorageEnergyRequirement] = []
        planning_gaps: tuple[PlanningGap, ...] = ()

        for storage in snapshot.current_storage_states:
            projected_energy_wh = storage.current_stored_energy_wh
            projection_cursor = snapshot.captured_at
            projected_intervals: list[
                ProjectedHouseholdEnergyBalanceInterval
            ] = []
            evidence_ids: list[str] = list(storage.evidence_ids)

            for pv_interval in pv_intervals:
                projection_start = max(
                    pv_interval.starts_at,
                    snapshot.captured_at,
                )
                projection_end = min(
                    pv_interval.ends_at,
                    snapshot.horizon_end,
                )
                if projection_start >= projection_end:
                    continue
                if projection_start != projection_cursor:
                    raise CandidateInputError(
                        "PV and household-load intervals must align"
                    )

                matching_load_intervals = tuple(
                    interval
                    for interval in load_intervals
                    if interval.starts_at < projection_end
                    and interval.ends_at > projection_start
                )
                load_cursor = projection_start
                load_energy_wh = 0.0
                for load_interval in matching_load_intervals:
                    overlap_start = max(
                        load_interval.starts_at,
                        projection_start,
                    )
                    overlap_end = min(
                        load_interval.ends_at,
                        projection_end,
                    )
                    if overlap_start != load_cursor:
                        raise CandidateInputError(
                            "PV and household-load intervals must align"
                        )
                    overlap_seconds = (
                        overlap_end - overlap_start
                    ).total_seconds()
                    interval_seconds = (
                        load_interval.ends_at
                        - load_interval.starts_at
                    ).total_seconds()
                    load_energy_wh += (
                        load_interval.expected_energy_wh
                        * overlap_seconds
                        / interval_seconds
                    )
                    load_cursor = overlap_end

                if (
                    not matching_load_intervals
                    or load_cursor != projection_end
                ):
                    raise CandidateInputError(
                        "PV and household-load intervals must align"
                    )

                pv_overlap_seconds = (
                    projection_end - projection_start
                ).total_seconds()
                pv_interval_seconds = (
                    pv_interval.ends_at - pv_interval.starts_at
                ).total_seconds()
                pv_energy_wh = (
                    pv_interval.pv_energy_wh
                    * pv_overlap_seconds
                    / pv_interval_seconds
                )
                load_confidence = min(
                    interval.confidence
                    for interval in matching_load_intervals
                )
                interval_start_energy_wh = projected_energy_wh
                projected_energy_wh = min(
                    storage.usable_capacity_wh,
                    max(
                        0.0,
                        interval_start_energy_wh
                        + pv_energy_wh
                        - load_energy_wh,
                    ),
                )
                confidence = min(storage.confidence, load_confidence)
                if pv_energy_wh > 1e-9:
                    confidence = min(confidence, pv_interval.confidence)
                interval_evidence = _ordered_unique(
                    storage.evidence_ids
                    + pv_interval.actual_evidence_ids
                    + pv_interval.forecast_evidence_ids
                    + tuple(
                        interval.source_reference
                        for interval in matching_load_intervals
                    )
                )
                evidence_ids.extend(interval_evidence)
                projected_intervals.append(
                    ProjectedHouseholdEnergyBalanceInterval(
                        starts_at=projection_start,
                        ends_at=projection_end,
                        current_usable_storage_energy_wh=(
                            interval_start_energy_wh
                        ),
                        expected_usable_pv_energy_wh=(
                            pv_energy_wh
                        ),
                        planned_grid_energy_wh=0.0,
                        household_load_forecast_energy_wh=(
                            load_energy_wh
                        ),
                        known_future_demand_energy_wh=0.0,
                        conversion_losses_wh=0.0,
                        other_planned_household_energy_flows_wh=0.0,
                        projected_storage_energy_wh=projected_energy_wh,
                        confidence=confidence,
                        evidence_ids=interval_evidence,
                    )
                )
                projection_cursor = projection_end

            if projection_cursor < snapshot.horizon_end:
                gap_start = projection_cursor
                gap_end = snapshot.horizon_end
                gap_load_intervals = tuple(
                    interval
                    for interval in load_intervals
                    if interval.starts_at < gap_end
                    and interval.ends_at > gap_start
                )
                gap_cursor = gap_start
                for load_interval in gap_load_intervals:
                    overlap_start = max(
                        load_interval.starts_at,
                        gap_start,
                    )
                    overlap_end = min(
                        load_interval.ends_at,
                        gap_end,
                    )
                    if overlap_start != gap_cursor:
                        raise CandidateInputError(
                            "PV and household-load intervals must align"
                        )
                    overlap_seconds = (
                        overlap_end - overlap_start
                    ).total_seconds()
                    interval_seconds = (
                        load_interval.ends_at
                        - load_interval.starts_at
                    ).total_seconds()
                    load_energy_wh = (
                        load_interval.expected_energy_wh
                        * overlap_seconds
                        / interval_seconds
                    )
                    interval_start_energy_wh = projected_energy_wh
                    projected_energy_wh = max(
                        0.0,
                        projected_energy_wh - load_energy_wh,
                    )
                    interval_evidence = _ordered_unique(
                        storage.evidence_ids
                        + (load_interval.source_reference,)
                    )
                    evidence_ids.extend(interval_evidence)
                    projected_intervals.append(
                        ProjectedHouseholdEnergyBalanceInterval(
                            starts_at=overlap_start,
                            ends_at=overlap_end,
                            current_usable_storage_energy_wh=(
                                interval_start_energy_wh
                            ),
                            expected_usable_pv_energy_wh=0.0,
                            planned_grid_energy_wh=0.0,
                            household_load_forecast_energy_wh=(
                                load_energy_wh
                            ),
                            known_future_demand_energy_wh=0.0,
                            conversion_losses_wh=0.0,
                            other_planned_household_energy_flows_wh=0.0,
                            projected_storage_energy_wh=(
                                projected_energy_wh
                            ),
                            confidence=0.0,
                            evidence_ids=interval_evidence,
                        )
                    )
                    gap_cursor = overlap_end

                if not gap_load_intervals or gap_cursor != gap_end:
                    raise CandidateInputError(
                        "PV and household-load intervals must align"
                    )
                planning_gaps = (
                    PlanningGap(
                        kind="pv_forecast_gap",
                        starts_at=gap_start,
                        ends_at=gap_end,
                        duration_seconds=(
                            gap_end - gap_start
                        ).total_seconds(),
                        assumption="zero_usable_pv",
                        confidence=0.0,
                    ),
                )
                projection_cursor = gap_end

            if projection_cursor != snapshot.horizon_end:
                raise CandidateInputError(
                    "PV and household-load intervals must align"
                )

            balance_id = _stable_id(
                "projected-balance",
                f"{snapshot.snapshot_id}|{storage.storage_state_id}",
            )
            balance = ProjectedHouseholdEnergyBalance(
                balance_id=balance_id,
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                storage_state_id=storage.storage_state_id,
                intervals=tuple(projected_intervals),
            )
            support_indexes = tuple(
                index
                for index, interval in enumerate(projected_intervals)
                if interval.projected_storage_energy_wh
                < interval.current_usable_storage_energy_wh
            )
            first_battery_support_interval = (
                projected_intervals[support_indexes[0]]
                if support_indexes
                else None
            )
            if (
                first_battery_support_interval is not None
                and first_battery_support_interval.starts_at
                == snapshot.captured_at
            ):
                next_support_phase = next(
                    (
                        projected_intervals[index]
                        for index in support_indexes
                        if index > 0
                        and projected_intervals[
                            index - 1
                        ].projected_storage_energy_wh
                        >= projected_intervals[
                            index - 1
                        ].current_usable_storage_energy_wh
                    ),
                    None,
                )
                if next_support_phase is not None:
                    first_battery_support_interval = next_support_phase
            balances.append(balance)
            if first_battery_support_interval is None:
                continue

            required_energy_wh = storage.usable_capacity_wh
            required_by = first_battery_support_interval.starts_at
            relevant_intervals = tuple(
                interval
                for interval in projected_intervals
                if interval.starts_at <= required_by
            )
            requirement = StorageEnergyRequirement(
                requirement_id=_stable_id(
                    "storage-requirement",
                    f"{balance_id}|{required_by.isoformat()}",
                ),
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                storage_state_id=storage.storage_state_id,
                projected_balance_id=balance_id,
                required_energy_wh=required_energy_wh,
                required_soc=1.0,
                required_by=required_by,
                reason="full_before_first_projected_battery_support",
                confidence=min(
                    (
                        storage.confidence,
                        *(
                            interval.confidence
                            for interval in relevant_intervals
                        ),
                    )
                ),
                evidence_ids=_ordered_unique(tuple(evidence_ids)),
                reserve_contribution_wh=max(
                    0.0,
                    required_energy_wh
                    - first_battery_support_interval.current_usable_storage_energy_wh,
                ),
            )
            requirements.append(requirement)

        return StorageRequirementDerivation(
            balances=tuple(balances),
            requirements=tuple(requirements),
            planning_gaps=planning_gaps,
        )
