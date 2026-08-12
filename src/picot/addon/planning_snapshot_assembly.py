"""Assemble one atomic Planner input from already-normalized live observations.

Home Assistant entity IDs remain outside this module. Source-specific adapters
normalize selected authoritative entities first (ADR-040); this assembler then
freezes those domain values into one PlanningInputSnapshot (ADR-017).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.forecast import ForecastSet
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import PlannerStrategy
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.domain.pv_energy_timeline import PVEnergyTimeline


@dataclass(frozen=True, slots=True)
class NormalizedPlanningInputs:
    """Domain values captured for one atomic assembly operation."""

    household_state: HouseholdState
    forecasts: ForecastSet
    current_storage_states: tuple[CurrentStorageState, ...] = ()
    household_load_forecast: HouseholdLoadForecast | None = None
    pv_energy_timeline: PVEnergyTimeline | None = None


def assemble_planning_input_snapshot(
    *,
    snapshot_id: str,
    captured_at: datetime,
    horizon_end: datetime,
    strategy: PlannerStrategy,
    inputs: NormalizedPlanningInputs,
    versions: PlanningInputVersions,
    replan_reasons: tuple[str, ...],
    runtime_state: RuntimePressureState = RuntimePressureState.NORMAL,
) -> PlanningInputSnapshot:
    """Freeze normalized live inputs into the canonical atomic snapshot.

    This function deliberately accepts PicoT domain records only. Reading HA
    entities here would violate ADR-040 and would make the snapshot non-atomic.
    Validation of timestamps, expiry and horizon coverage remains owned by the
    PlanningInputSnapshot domain contract.
    """

    return PlanningInputSnapshot(
        snapshot_id=snapshot_id,
        captured_at=captured_at,
        horizon_end=horizon_end,
        strategy=strategy,
        household_state=inputs.household_state,
        forecasts=inputs.forecasts,
        runtime_state=runtime_state,
        versions=versions,
        replan_reasons=replan_reasons,
        household_load_forecast=inputs.household_load_forecast,
        current_storage_states=inputs.current_storage_states,
        pv_energy_timeline=inputs.pv_energy_timeline,
    )
