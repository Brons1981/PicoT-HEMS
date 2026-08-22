"""Vendor-independent storage capability projection for PicoT v2."""

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.zendure_mode_capabilities import ZendureModeCapabilityEvidence

MAPPING_VERSION = 1
SOURCE_MAPPING_ID = "storage-mode-options:v1"
ADAPTER_CONTRACT_VERSION = "1"

_PRIMITIVE_ORDER = (
    ExecutionPrimitive.STANDBY,
    ExecutionPrimitive.CHARGE_AT_POWER,
    ExecutionPrimitive.DISCHARGE_AT_POWER,
    ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
    ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
    ExecutionPrimitive.BALANCE_CHARGE_ONLY,
)

_CHARGE_PRIMITIVES = frozenset(
    {
        ExecutionPrimitive.CHARGE_AT_POWER,
        ExecutionPrimitive.BALANCE_CHARGE_ONLY,
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
    }
)
_DISCHARGE_PRIMITIVES = frozenset(
    {
        ExecutionPrimitive.DISCHARGE_AT_POWER,
        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
    }
)


def build_storage_capability_snapshot_set(
    evidence: ZendureModeCapabilityEvidence,
    *,
    snapshot_id: str,
    minimum_soc: float | None = None,
) -> CapabilitySnapshotSet:
    """Project adapter-bound evidence into one immutable logical capability."""

    available = evidence.status == "available"
    supported = {
        primitive
        for mapping in evidence.mappings
        for primitive in mapping.primitives
    }
    supported_primitives = (
        tuple(primitive for primitive in _PRIMITIVE_ORDER if primitive in supported)
        if available
        else ()
    )
    flow_directions = tuple(
        direction
        for direction, enabled in (
            (EnergyFlowDirection.CHARGE, bool(supported & _CHARGE_PRIMITIVES)),
            (EnergyFlowDirection.DISCHARGE, bool(supported & _DISCHARGE_PRIMITIVES)),
            (
                EnergyFlowDirection.BIDIRECTIONAL,
                ExecutionPrimitive.BALANCE_BIDIRECTIONAL in supported,
            ),
        )
        if available and enabled
    )
    capability = LogicalCapabilitySnapshot(
        capability_id=evidence.capability_id,
        execution_scope_id=evidence.execution_scope_id,
        supported_primitives=supported_primitives,
        availability=(
            CapabilityAvailability.AVAILABLE
            if available
            else CapabilityAvailability.UNAVAILABLE
        ),
        health=CapabilityHealth.HEALTHY if available else CapabilityHealth.INVALID,
        fresh_at=evidence.captured_at,
        confidence=1.0 if available else 0.0,
        source_mapping_id=SOURCE_MAPPING_ID,
        adapter_contract_version=ADAPTER_CONTRACT_VERSION,
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=flow_directions,
        minimum_soc=minimum_soc,
    )
    return CapabilitySnapshotSet(
        snapshot_id=snapshot_id,
        mapping_version=MAPPING_VERSION,
        captured_at=evidence.captured_at,
        capabilities=(capability,),
    )
