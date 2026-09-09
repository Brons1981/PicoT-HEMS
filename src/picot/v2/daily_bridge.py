"""Reserve evidence for supplemental household support (ADR-037.9)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from picot.domain.daily_reference_intent import DailyReferenceIntentSchedule, DailyStorageIntent
from picot.domain.daily_reference_simulation import DailyPlanningProjection
from picot.v2.daily_charge_assignment import DailyChargeAssignment, DailyChargeRevisionReason


@dataclass(frozen=True, slots=True)
class BridgeEnergyInterval:
    starts_at: datetime
    ends_at: datetime
    deficit_wh: float

    def __post_init__(self) -> None:
        if self.starts_at.utcoffset() is None or self.ends_at.utcoffset() is None:
            raise ValueError("bridge evidence requires aware boundaries")
        if self.ends_at <= self.starts_at or not isfinite(self.deficit_wh) or self.deficit_wh < 0:
            raise ValueError("bridge evidence requires finite non-negative energy")


@dataclass(frozen=True, slots=True)
class DailyBridgeState:
    assignment_id: str
    plan_id: str
    next_starts_at: datetime
    accepted_deficits: tuple[BridgeEnergyInterval, ...]

    def __post_init__(self) -> None:
        if not self.assignment_id or not self.plan_id or self.next_starts_at.utcoffset() is None:
            raise ValueError("bridge state requires explicit lineage")
        if not self.accepted_deficits or self.accepted_deficits[-1].ends_at != self.next_starts_at:
            raise ValueError("bridge state must cover its declared endpoint")
        if any(
            a.ends_at != b.starts_at
            for a, b in zip(
                self.accepted_deficits,
                self.accepted_deficits[1:],
                strict=False,
            )
        ):
            raise ValueError("bridge state must be contiguous and non-overlapping")


@dataclass(frozen=True, slots=True)
class DailyBridgeTrigger:
    assignment_id: str
    route_plan_id: str
    revision: int
    active_plan_id: str
    snapshot_id: str
    assessed_at: datetime
    target_wh: float
    completed_assignment_id: str
    next_starts_at: datetime
    deficits: tuple[BridgeEnergyInterval, ...]
    supplemental_shortfall_id: str | None = None
    historical_completion_id: str | None = None

    @property
    def revision_reason(self) -> DailyChargeRevisionReason:
        return DailyChargeRevisionReason.RESERVE

    def validate(self, owner: DailyChargeAssignment, snapshot_id: str, at: datetime) -> None:
        if (owner.assignment_id, owner.route_plan_id, owner.revision) != (
            self.assignment_id,
            self.route_plan_id,
            self.revision,
        ) or (snapshot_id, at) != (self.snapshot_id, self.assessed_at):
            raise ValueError("bridge trigger must match current ownership and input")
        if owner.completed_at is not None or self.next_starts_at <= at:
            raise ValueError("bridge requires a future open main session")
        if not isfinite(self.target_wh) or self.target_wh <= 0 or not self.deficits:
            raise ValueError("bridge requires an explicit target and energy deficit")
        if (not self.supplemental_shortfall_id and not self.historical_completion_id) and not any(
            i.deficit_wh > 1e-6 for i in self.deficits
        ):
            raise ValueError("bridge requires positive energy shortage")


@dataclass(frozen=True, slots=True)
class DailyBridgeAssessment:
    status: str
    next_assignment_id: str | None = None
    next_starts_at: datetime | None = None
    deficits: tuple[BridgeEnergyInterval, ...] = ()
    trigger: DailyBridgeTrigger | None = None


def energy_deficits(
    projection: DailyPlanningProjection,
    schedule: DailyReferenceIntentSchedule,
    *,
    until: datetime,
    maximum_discharge_output_power_w: float,
) -> tuple[BridgeEnergyInterval, ...]:
    """Separate energy scarcity from power-limited or intentional grid use.

    The physical trajectory already respects minimum SOC. Only household demand
    within the output-power limit that storage cannot supply is energy shortage.
    Charging and standby intentionally delegate household supply to the grid.
    """
    result = []
    for interval, intent in zip(projection.intervals, schedule.intervals, strict=True):
        if interval.starts_at >= until:
            break
        if interval.ends_at > until:
            raise ValueError("bridge endpoint must align with the physical schedule")
        hours = (interval.ends_at - interval.starts_at).total_seconds() / 3600
        deficit = 0.0
        if intent.intent in {DailyStorageIntent.NOM, DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY}:
            demand = max(0.0, interval.household_demand_wh - interval.pv_to_household_wh)
            deficit = max(
                0.0,
                min(demand, maximum_discharge_output_power_w * hours)
                - interval.storage_to_household_output_wh,
            )
        result.append(BridgeEnergyInterval(interval.starts_at, interval.ends_at, deficit))
    return tuple(result)


def needs_bridge_review(
    deficits: tuple[BridgeEnergyInterval, ...],
    state: DailyBridgeState | None,
    *,
    plan_id: str,
    next_starts_at: datetime,
) -> bool:
    if state is None or (state.plan_id, state.next_starts_at) != (plan_id, next_starts_at):
        return any(i.deficit_wh > 1e-6 for i in deficits)
    for interval in deficits:
        allowance = sum(
            old.deficit_wh
            * max(
                0.0,
                (
                    min(old.ends_at, interval.ends_at) - max(old.starts_at, interval.starts_at)
                ).total_seconds(),
            )
            / (old.ends_at - old.starts_at).total_seconds()
            for old in state.accepted_deficits
        )
        if interval.deficit_wh > allowance + 1e-6:
            return True
    return False
