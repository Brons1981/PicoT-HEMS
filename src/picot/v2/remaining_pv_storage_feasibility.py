"""Conservative remaining-PV feasibility for one storage target."""

from __future__ import annotations

from dataclasses import dataclass

from picot.v2.contracts import (
    PlanningInputSnapshot,
    ProjectedHouseholdEnergyBalance,
    StorageEnergyRequirement,
)


@dataclass(frozen=True, slots=True)
class RemainingPVStorageFeasibility:
    """Facts used to protect a storage target from shrinking PV opportunity."""

    status: str
    remaining_storage_need_wh: float | None
    conservative_remaining_pv_surplus_wh: float | None
    margin_wh: float | None
    required_by: str | None
    evidence_ids: tuple[str, ...]


def derive_remaining_pv_storage_feasibility(
    snapshot: PlanningInputSnapshot,
    *,
    requirements: tuple[StorageEnergyRequirement, ...],
    balances: tuple[ProjectedHouseholdEnergyBalance, ...],
) -> RemainingPVStorageFeasibility:
    """Compare storage need with lower-bound PV surplus until its deadline."""

    if (
        snapshot.pv_energy_timeline is None
        or len(requirements) != 1
        or len(snapshot.current_storage_states) != 1
    ):
        return RemainingPVStorageFeasibility(
            status="unavailable",
            remaining_storage_need_wh=None,
            conservative_remaining_pv_surplus_wh=None,
            margin_wh=None,
            required_by=None,
            evidence_ids=(),
        )

    requirement = requirements[0]
    matching_balances = tuple(
        item
        for item in balances
        if item.balance_id == requirement.projected_balance_id
    )
    storage = snapshot.current_storage_states[0]
    if len(matching_balances) != 1:
        return RemainingPVStorageFeasibility(
            status="unavailable",
            remaining_storage_need_wh=None,
            conservative_remaining_pv_surplus_wh=None,
            margin_wh=None,
            required_by=requirement.required_by.isoformat(),
            evidence_ids=requirement.evidence_ids,
        )

    balance = matching_balances[0]
    conservative_surplus_wh = 0.0
    evidence_ids: list[str] = list(requirement.evidence_ids)
    for interval in balance.intervals:
        if (
            interval.ends_at <= snapshot.captured_at
            or interval.starts_at >= requirement.required_by
        ):
            continue
        overlap_start = max(interval.starts_at, snapshot.captured_at)
        overlap_end = min(interval.ends_at, requirement.required_by)
        if overlap_end <= overlap_start:
            continue
        interval_seconds = (interval.ends_at - interval.starts_at).total_seconds()
        overlap_ratio = (overlap_end - overlap_start).total_seconds() / interval_seconds
        pv_matches = tuple(
            item
            for item in snapshot.pv_energy_timeline.intervals
            if item.starts_at < overlap_end and item.ends_at > overlap_start
        )
        conservative_pv_wh = 0.0
        for pv_interval in pv_matches:
            pv_overlap_start = max(pv_interval.starts_at, overlap_start)
            pv_overlap_end = min(pv_interval.ends_at, overlap_end)
            pv_seconds = (pv_interval.ends_at - pv_interval.starts_at).total_seconds()
            pv_ratio = (pv_overlap_end - pv_overlap_start).total_seconds() / pv_seconds
            if (
                pv_interval.forecast_range_status == "available"
                and pv_interval.forecast_lower_energy_wh is not None
            ):
                conservative_pv_wh += (
                    pv_interval.forecast_lower_energy_wh * pv_ratio
                )
            else:
                conservative_pv_wh += (
                    pv_interval.pv_energy_wh
                    * pv_interval.confidence
                    * pv_ratio
                )
            evidence_ids.extend(pv_interval.forecast_evidence_ids)
            evidence_ids.extend(pv_interval.actual_evidence_ids)
        load_wh = interval.household_load_forecast_energy_wh * overlap_ratio
        conservative_surplus_wh += max(0.0, conservative_pv_wh - load_wh)
        evidence_ids.extend(interval.evidence_ids)

    remaining_need_wh = max(
        0.0,
        requirement.required_energy_wh - storage.current_stored_energy_wh,
    )
    margin_wh = conservative_surplus_wh - remaining_need_wh
    return RemainingPVStorageFeasibility(
        status="available",
        remaining_storage_need_wh=remaining_need_wh,
        conservative_remaining_pv_surplus_wh=conservative_surplus_wh,
        margin_wh=margin_wh,
        required_by=requirement.required_by.isoformat(),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
    )
