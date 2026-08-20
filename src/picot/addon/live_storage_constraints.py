"""Canonical live storage constraints from explicit PicoT configuration.

Hardware limits are never inferred from current telemetry. Missing commissioned
power limits keep the capability absent so ADR-037 remains fail-closed.
"""

from __future__ import annotations

from datetime import datetime

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.execution_primitive import ExecutionPrimitive


def build_live_storage_capabilities(
    *,
    captured_at: datetime,
    snapshot_id: str,
    maximum_charge_power_w: float | None,
    power_step_w: float | None,
    maximum_soc: float,
    minimum_soc: float | None = None,
) -> CapabilitySnapshotSet:
    """Build a commissioned storage capability, or an empty fail-closed set."""

    capabilities: tuple[LogicalCapabilitySnapshot, ...] = ()
    if maximum_charge_power_w is not None and maximum_charge_power_w > 0:
        capabilities = (
            LogicalCapabilitySnapshot(
                capability_id="storage-primary-energy",
                execution_scope_id="storage-primary",
                supported_primitives=(
                    ExecutionPrimitive.CHARGE_AT_POWER,
                    ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                    ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
                ),
                availability=CapabilityAvailability.AVAILABLE,
                health=CapabilityHealth.HEALTHY,
                fresh_at=captured_at,
                confidence=1.0,
                source_mapping_id="configured-storage-primary",
                adapter_contract_version="live-storage-config-v3",
                role=CapabilityRole.ENERGY_STORAGE,
                flow_directions=(
                    EnergyFlowDirection.CHARGE,
                    EnergyFlowDirection.DISCHARGE,
                    EnergyFlowDirection.BIDIRECTIONAL,
                ),
                minimum_power_w=0.0,
                maximum_power_w=maximum_charge_power_w,
                maximum_soc=maximum_soc,
                minimum_soc=minimum_soc,
                power_step_w=(power_step_w if power_step_w and power_step_w > 0 else None),
            ),
        )
    return CapabilitySnapshotSet(
        snapshot_id=snapshot_id,
        mapping_version=1,
        captured_at=captured_at,
        capabilities=capabilities,
    )


def build_effective_storage_limit(
    *, storage_state: CurrentStorageState, maximum_soc: float, sequence: int
) -> EffectiveStorageLimit:
    """Build the canonical planner target ceiling from explicit configuration."""

    limit = EffectiveStorageLimit(
        limit_id=f"live-storage-limit-{sequence}",
        execution_scope_id=storage_state.execution_scope_id,
        max_soc=maximum_soc,
        usable_capacity_wh=storage_state.usable_capacity_wh,
        confidence=1.0,
        evidence_ids=("config:storage_max_soc_percent", "config:storage_usable_capacity_wh"),
        method_version="configured-effective-storage-limit-v1",
    )
    limit.validate_against(storage_state)
    return limit
