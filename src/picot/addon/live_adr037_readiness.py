"""Observer-only ADR-037 runtime readiness bridge."""

from __future__ import annotations

from picot.domain.capability_snapshot import CapabilitySnapshotSet
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceAssembler,
)


def assemble_live_projected_balance(
    snapshot: PlanningInputSnapshot,
) -> ProjectedHouseholdEnergyBalance | None:
    """Assemble the canonical no-grid baseline when the live energy set is complete."""

    if (
        not snapshot.current_storage_states
        or snapshot.pv_energy_timeline is None
        or snapshot.household_load_forecast is None
    ):
        return None
    storage_state = snapshot.current_storage_states[0]
    return ProjectedHouseholdEnergyBalanceAssembler().assemble(
        balance_id=f"live-balance-{snapshot.snapshot_id}",
        captured_at=snapshot.captured_at,
        storage_state=storage_state,
        pv_timeline=snapshot.pv_energy_timeline,
        load_forecast=snapshot.household_load_forecast,
    )


def adr037_readiness_log_event(
    snapshot: PlanningInputSnapshot,
    *,
    capabilities: CapabilitySnapshotSet | None = None,
    effective_limit: EffectiveStorageLimit | None = None,
) -> dict[str, object]:
    """Expose exactly how far the real ADR-037 live path can safely proceed."""

    balance = assemble_live_projected_balance(snapshot)
    blockers: list[str] = []
    if balance is None:
        blockers.append("incomplete_energy_input_set")

    storage_capability = None
    if capabilities is not None:
        storage_capability = next(
            (
                item
                for item in capabilities.capabilities
                if item.execution_scope_id == "storage-primary"
            ),
            None,
        )
    if storage_capability is None:
        blockers.append("live_storage_capability_snapshot_unavailable")

    if effective_limit is None:
        blockers.append("live_effective_storage_limit_unwired")

    blockers.extend(
        (
            "live_evidence_confidence_assessment_unwired",
            "canonical_price_opportunity_set_unwired_to_live_snapshot",
        )
    )
    return {
        "event": "picot_live_adr037_readiness",
        "layer": "planner",
        "snapshot_id": snapshot.snapshot_id,
        "captured_at": snapshot.captured_at.isoformat(),
        "projected_balance_available": balance is not None,
        "projected_balance_id": balance.balance_id if balance is not None else None,
        "projected_balance_confidence": balance.confidence if balance is not None else None,
        "projected_balance_end_energy_wh": (
            balance.points[-1].projected_storage_energy_wh if balance is not None else None
        ),
        "projected_balance_cumulative_pv_wh": (
            balance.points[-1].cumulative_pv_energy_wh if balance is not None else None
        ),
        "projected_balance_cumulative_household_load_wh": (
            balance.points[-1].cumulative_household_load_wh if balance is not None else None
        ),
        "storage_capability_available": storage_capability is not None,
        "storage_max_charge_power_w": (
            storage_capability.maximum_power_w if storage_capability is not None else None
        ),
        "effective_storage_limit_available": effective_limit is not None,
        "effective_storage_max_soc": effective_limit.max_soc if effective_limit else None,
        "effective_storage_max_energy_wh": (
            effective_limit.max_energy_wh if effective_limit else None
        ),
        "adr037_pipeline_stage_reached": (
            "projected_household_energy_balance" if balance is not None else "planning_input"
        ),
        "adr037_live_ready": not blockers,
        "adr037_live_blockers": blockers,
        "control_change_allowed": False,
        "observer_only": True,
    }
