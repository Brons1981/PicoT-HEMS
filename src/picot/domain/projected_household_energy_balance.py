"""Projected household energy balance from ADR-037.

Implementation boundary:
- This module is the canonical projected-household-balance engine.
- Future known-demand/commitment inputs and conversion-loss inputs MUST be
  integrated into this same balance calculation when their Core contracts exist.
- They MUST NOT be implemented as a second or parallel household-balance engine.
- Planned grid energy remains outside the no-grid baseline used to determine
  whether grid-supported charging is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.pv_energy_timeline import PVEnergyTimeline


@dataclass(frozen=True, slots=True)
class ProjectedHouseholdEnergyBalancePoint:
    """Projected stored-energy position at one future boundary."""

    at: datetime
    projected_storage_energy_wh: float
    cumulative_pv_energy_wh: float
    cumulative_household_load_wh: float


@dataclass(frozen=True, slots=True)
class ProjectedHouseholdEnergyBalance:
    """Immutable baseline projection without planned grid charging.

    `known_future_demand_applied` and `conversion_losses_applied` deliberately
    remain explicit until those accepted inputs are integrated here. They are
    extension markers for this canonical engine, not permission to create
    parallel calculations elsewhere.
    """

    balance_id: str
    created_at: datetime
    horizon_end: datetime
    execution_scope_id: str
    starting_storage_energy_wh: float
    points: tuple[ProjectedHouseholdEnergyBalancePoint, ...]
    confidence: float
    evidence_ids: tuple[str, ...]
    known_future_demand_applied: bool = False
    conversion_losses_applied: bool = False
    planned_grid_energy_applied: bool = False

    def __post_init__(self) -> None:
        if not self.balance_id.strip():
            raise ValueError("Projected balance ID must not be empty.")
        if not self.execution_scope_id.strip():
            raise ValueError("Execution scope ID must not be empty.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Projected balance creation time must be timezone-aware.")
        if self.horizon_end.tzinfo is None or self.horizon_end.utcoffset() is None:
            raise ValueError("Projected balance horizon end must be timezone-aware.")
        if self.horizon_end <= self.created_at:
            raise ValueError("Projected balance horizon must end after creation time.")
        if self.starting_storage_energy_wh < 0:
            raise ValueError("Starting storage energy must not be negative.")
        if not self.points:
            raise ValueError("Projected balance requires at least one point.")
        if self.points[-1].at != self.horizon_end:
            raise ValueError("Projected balance must end at the declared horizon end.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Projected balance confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids:
            raise ValueError("Projected balance requires evidence IDs.")
        if self.planned_grid_energy_applied:
            raise ValueError("Baseline projected balance must not include planned grid energy.")


@dataclass(frozen=True, slots=True)
class ProjectedHouseholdEnergyBalanceAssembler:
    """Build the v1 no-grid baseline from canonical Planner inputs.

    Future known-demand/commitment and conversion-loss inputs extend this
    assembler. They do not get a separate projected-balance implementation.
    """

    method_version: str = "projected-household-balance-v1"

    def assemble(
        self,
        *,
        balance_id: str,
        captured_at: datetime,
        storage_state: CurrentStorageState,
        pv_timeline: PVEnergyTimeline,
        load_forecast: HouseholdLoadForecast,
    ) -> ProjectedHouseholdEnergyBalance:
        if pv_timeline.horizon_end != load_forecast.horizon_end:
            raise ValueError("PV and household-load horizons must end together.")
        if load_forecast.horizon_start != captured_at:
            raise ValueError("Household load forecast must start at capture time.")
        if not pv_timeline.horizon_start <= captured_at < pv_timeline.horizon_end:
            raise ValueError("PV timeline must contain capture time.")

        future_pv = tuple(
            interval for interval in pv_timeline.intervals if interval.starts_at >= captured_at
        )
        if not future_pv or future_pv[0].starts_at != captured_at:
            raise ValueError("PV timeline must provide future energy from capture time.")

        pv_by_end = {interval.ends_at: interval for interval in future_pv}
        load_by_end = {interval.ends_at: interval for interval in load_forecast.intervals}
        if tuple(pv_by_end) != tuple(load_by_end):
            raise ValueError("PV and household-load interval boundaries must align in v1.")

        cumulative_pv = 0.0
        cumulative_load = 0.0
        points: list[ProjectedHouseholdEnergyBalancePoint] = []
        for ends_at in pv_by_end:
            cumulative_pv += pv_by_end[ends_at].energy_wh
            cumulative_load += load_by_end[ends_at].expected_energy_wh
            points.append(
                ProjectedHouseholdEnergyBalancePoint(
                    at=ends_at,
                    projected_storage_energy_wh=(
                        storage_state.current_stored_energy_wh
                        + cumulative_pv
                        - cumulative_load
                    ),
                    cumulative_pv_energy_wh=cumulative_pv,
                    cumulative_household_load_wh=cumulative_load,
                )
            )

        confidence = min(
            storage_state.confidence,
            load_forecast.confidence,
            *(interval.confidence for interval in future_pv),
        )
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    storage_state.storage_state_id,
                    load_forecast.forecast_id,
                    pv_timeline.timeline_id,
                    *storage_state.evidence_ids,
                    *(evidence_id for interval in future_pv for evidence_id in interval.evidence_ids),
                    self.method_version,
                )
            )
        )

        return ProjectedHouseholdEnergyBalance(
            balance_id=balance_id,
            created_at=captured_at,
            horizon_end=load_forecast.horizon_end,
            execution_scope_id=storage_state.execution_scope_id,
            starting_storage_energy_wh=storage_state.current_stored_energy_wh,
            points=tuple(points),
            confidence=confidence,
            evidence_ids=evidence_ids,
        )
