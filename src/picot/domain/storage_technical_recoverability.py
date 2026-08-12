"""Technical storage recoverability for ADR-037.

This evaluator answers only whether a storage capability can physically absorb
required extra energy before a StorageEnergyRequirement deadline. It does not
choose or permit an energy source; PV/grid source policy remains separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.storage_energy_requirement import StorageEnergyRequirement


@dataclass(frozen=True, slots=True)
class StorageTechnicalRecoverability:
    """Evidence whether the required extra storage energy is physically reachable."""

    evaluated_at: datetime
    requirement_id: str
    capability_id: str
    required_by: datetime
    extra_energy_required_wh: float
    maximum_charge_energy_before_deadline_wh: float
    technically_recoverable: bool
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("Technical recoverability evaluation time must be timezone-aware.")
        if self.required_by.tzinfo is None or self.required_by.utcoffset() is None:
            raise ValueError("Technical recoverability deadline must be timezone-aware.")
        if self.required_by < self.evaluated_at:
            raise ValueError("Technical recoverability deadline must not be in the past.")
        if self.extra_energy_required_wh < 0:
            raise ValueError("Extra required storage energy must not be negative.")
        if self.maximum_charge_energy_before_deadline_wh < 0:
            raise ValueError("Maximum charge energy must not be negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Technical recoverability confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids:
            raise ValueError("Technical recoverability requires evidence IDs.")


@dataclass(frozen=True, slots=True)
class StorageTechnicalRecoverabilityEvaluator:
    """Evaluate physical charge recoverability without energy-source assumptions."""

    method_version: str = "storage-technical-recoverability-v1"

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
        requirement: StorageEnergyRequirement,
        storage_state: CurrentStorageState,
        storage_limit: EffectiveStorageLimit,
        capability: LogicalCapabilitySnapshot,
    ) -> StorageTechnicalRecoverability:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("Evaluation time must be timezone-aware.")
        if requirement.required_by < evaluated_at:
            raise ValueError("Storage requirement deadline must not be in the past.")

        storage_limit.validate_against(storage_state)
        self._validate_capability(storage_state=storage_state, capability=capability)

        target_energy_wh = min(requirement.required_energy_wh, storage_limit.max_energy_wh)
        extra_required_wh = max(0.0, target_energy_wh - storage_state.current_stored_energy_wh)
        headroom_wh = max(
            0.0,
            storage_limit.max_energy_wh - storage_state.current_stored_energy_wh,
        )
        available_hours = (requirement.required_by - evaluated_at).total_seconds() / 3600.0
        power_limited_energy_wh = capability.maximum_power_w * available_hours
        maximum_charge_energy_wh = min(headroom_wh, power_limited_energy_wh)

        evidence_ids = tuple(
            dict.fromkeys(
                (
                    requirement.requirement_id,
                    storage_state.storage_state_id,
                    storage_limit.limit_id,
                    capability.capability_id,
                    capability.source_mapping_id,
                    self.method_version,
                )
            )
        )

        return StorageTechnicalRecoverability(
            evaluated_at=evaluated_at,
            requirement_id=requirement.requirement_id,
            capability_id=capability.capability_id,
            required_by=requirement.required_by,
            extra_energy_required_wh=extra_required_wh,
            maximum_charge_energy_before_deadline_wh=maximum_charge_energy_wh,
            technically_recoverable=maximum_charge_energy_wh >= extra_required_wh,
            confidence=min(
                requirement.confidence,
                storage_state.confidence,
                storage_limit.confidence,
                capability.confidence,
            ),
            evidence_ids=evidence_ids,
        )

    @staticmethod
    def _validate_capability(
        *,
        storage_state: CurrentStorageState,
        capability: LogicalCapabilitySnapshot,
    ) -> None:
        if capability.execution_scope_id != storage_state.execution_scope_id:
            raise ValueError("Storage capability and current state must share a scope.")
        if capability.capability_id != storage_state.capability_id:
            raise ValueError("Storage capability must match the canonical storage capability ID.")
        if capability.role is not CapabilityRole.ENERGY_STORAGE:
            raise ValueError("Technical recoverability requires an energy-storage capability.")
        if EnergyFlowDirection.CHARGE not in capability.flow_directions and (
            EnergyFlowDirection.BIDIRECTIONAL not in capability.flow_directions
        ):
            raise ValueError("Storage capability must support charging.")
        if ExecutionPrimitive.CHARGE_AT_POWER not in capability.supported_primitives:
            raise ValueError("Storage capability must support CHARGE_AT_POWER.")
        if capability.availability is not CapabilityAvailability.AVAILABLE:
            raise ValueError("Storage capability must be available.")
        if capability.health is not CapabilityHealth.HEALTHY:
            raise ValueError("Storage capability must be healthy.")
        if capability.maximum_power_w is None:
            raise ValueError("Storage capability requires a maximum charge power.")
