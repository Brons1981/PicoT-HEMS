"""Technical storage recoverability for ADR-037 and ADR-043.

This evaluator answers only whether additional storage energy can physically be
acquired before the protected interval starts. It does not choose or permit an
energy source; PV/grid source policy remains separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

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
    """Evidence whether additional required storage energy is physically reachable."""

    evaluated_at: datetime
    requirement_id: str
    capability_id: str
    protection_starts_at: datetime
    protected_through: datetime
    extra_energy_required_wh: float
    additional_acquisition_required: bool
    maximum_charge_energy_before_protection_wh: float
    latest_full_power_charge_start: datetime | None
    technically_recoverable: bool
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("evaluation time", self.evaluated_at),
            ("protection start", self.protection_starts_at),
            ("protected-through time", self.protected_through),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    f"Technical recoverability {name} must be timezone-aware."
                )
        if self.protected_through < self.protection_starts_at:
            raise ValueError(
                "Protected-through time must not precede protection start."
            )
        if self.latest_full_power_charge_start is not None:
            if (
                self.latest_full_power_charge_start.tzinfo is None
                or self.latest_full_power_charge_start.utcoffset() is None
            ):
                raise ValueError(
                    "Latest full-power charge start must be timezone-aware."
                )
            if self.latest_full_power_charge_start > self.protection_starts_at:
                raise ValueError(
                    "Latest full-power charge start must not be after protection starts."
                )
        if self.extra_energy_required_wh < 0:
            raise ValueError("Extra required storage energy must not be negative.")
        if self.maximum_charge_energy_before_protection_wh < 0:
            raise ValueError("Maximum charge energy must not be negative.")
        if self.additional_acquisition_required != (
            self.extra_energy_required_wh > 0.0
        ):
            raise ValueError(
                "Additional-acquisition flag must match extra required energy."
            )
        if (
            not self.additional_acquisition_required
            and self.latest_full_power_charge_start is not None
        ):
            raise ValueError(
                "No latest charge start exists when no additional energy is required."
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "Technical recoverability confidence must be between 0.0 and 1.0."
            )
        if not self.evidence_ids:
            raise ValueError("Technical recoverability requires evidence IDs.")


@dataclass(frozen=True, slots=True)
class StorageTechnicalRecoverabilityEvaluator:
    """Evaluate physical charge recoverability without energy-source assumptions."""

    method_version: str = "storage-technical-recoverability-v3"

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

        storage_limit.validate_against(storage_state)
        self._validate_capability(
            storage_state=storage_state,
            capability=capability,
        )
        maximum_power_w = capability.maximum_power_w
        if maximum_power_w is None:
            raise ValueError("Storage capability requires a maximum charge power.")

        target_energy_wh = min(
            requirement.required_energy_wh,
            storage_limit.max_energy_wh,
        )
        extra_required_wh = max(
            0.0,
            target_energy_wh - storage_state.current_stored_energy_wh,
        )
        acquisition_required = extra_required_wh > 0.0
        headroom_wh = max(
            0.0,
            storage_limit.max_energy_wh - storage_state.current_stored_energy_wh,
        )
        available_seconds = max(
            0.0,
            (requirement.protection_starts_at - evaluated_at).total_seconds(),
        )
        power_limited_energy_wh = maximum_power_w * available_seconds / 3600.0
        maximum_charge_energy_wh = min(headroom_wh, power_limited_energy_wh)
        latest_full_power_charge_start = None
        if acquisition_required:
            required_charge_hours = extra_required_wh / maximum_power_w
            latest_full_power_charge_start = (
                requirement.protection_starts_at
                - timedelta(hours=required_charge_hours)
            )

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
            protection_starts_at=requirement.protection_starts_at,
            protected_through=requirement.protected_through,
            extra_energy_required_wh=extra_required_wh,
            additional_acquisition_required=acquisition_required,
            maximum_charge_energy_before_protection_wh=maximum_charge_energy_wh,
            latest_full_power_charge_start=latest_full_power_charge_start,
            technically_recoverable=(
                True
                if not acquisition_required
                else maximum_charge_energy_wh >= extra_required_wh
            ),
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
            raise ValueError(
                "Storage capability and current state must share a scope."
            )
        if capability.capability_id != storage_state.capability_id:
            raise ValueError(
                "Storage capability must match the canonical storage capability ID."
            )
        if capability.role is not CapabilityRole.ENERGY_STORAGE:
            raise ValueError(
                "Technical recoverability requires an energy-storage capability."
            )
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
