from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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
from picot.domain.storage_energy_requirement import (
    StorageEnergyRequirement,
    StorageRequirementReason,
)
from picot.domain.storage_technical_recoverability import (
    StorageTechnicalRecoverabilityEvaluator,
)


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _state() -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id="state-1",
        execution_scope_id="battery-1",
        capability_id="storage-capability-1",
        current_soc=0.5,
        usable_capacity_wh=8000.0,
        measured_at=NOW,
        confidence=0.95,
        evidence_ids=("sensor:soc",),
    )


def _limit() -> EffectiveStorageLimit:
    return EffectiveStorageLimit(
        limit_id="limit-1",
        execution_scope_id="battery-1",
        max_soc=1.0,
        usable_capacity_wh=8000.0,
        confidence=1.0,
        evidence_ids=("config:max-soc",),
        method_version="effective-storage-limit-v1",
    )


def _requirement(*, required_energy_wh: float = 7000.0, hours: float = 2.0) -> StorageEnergyRequirement:
    return StorageEnergyRequirement(
        requirement_id="requirement-1",
        required_by=NOW + timedelta(hours=hours),
        required_energy_wh=required_energy_wh,
        required_soc_percent=None,
        reason=StorageRequirementReason.HOUSEHOLD_DEMAND,
        confidence=0.9,
        evidence_ids=("balance-1",),
    )


def _capability(*, max_power_w: float = 2000.0) -> LogicalCapabilitySnapshot:
    return LogicalCapabilitySnapshot(
        capability_id="storage-capability-1",
        execution_scope_id="battery-1",
        supported_primitives=(ExecutionPrimitive.CHARGE_AT_POWER,),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=NOW,
        confidence=0.98,
        source_mapping_id="mapping-1",
        adapter_contract_version="v1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
        maximum_power_w=max_power_w,
    )


def test_recoverable_when_power_and_time_can_supply_required_extra_energy() -> None:
    result = StorageTechnicalRecoverabilityEvaluator().evaluate(
        evaluated_at=NOW,
        requirement=_requirement(),
        storage_state=_state(),
        storage_limit=_limit(),
        capability=_capability(),
    )

    assert result.extra_energy_required_wh == pytest.approx(3000.0)
    assert result.maximum_charge_energy_before_deadline_wh == pytest.approx(4000.0)
    assert result.technically_recoverable is True


def test_not_recoverable_when_charge_power_is_too_low_before_deadline() -> None:
    result = StorageTechnicalRecoverabilityEvaluator().evaluate(
        evaluated_at=NOW,
        requirement=_requirement(),
        storage_state=_state(),
        storage_limit=_limit(),
        capability=_capability(max_power_w=1000.0),
    )

    assert result.maximum_charge_energy_before_deadline_wh == pytest.approx(2000.0)
    assert result.technically_recoverable is False


def test_effective_storage_limit_caps_physical_charge_headroom() -> None:
    limit = EffectiveStorageLimit(
        limit_id="limit-95",
        execution_scope_id="battery-1",
        max_soc=0.75,
        usable_capacity_wh=8000.0,
        confidence=1.0,
        evidence_ids=("config:max-soc",),
        method_version="effective-storage-limit-v1",
    )
    result = StorageTechnicalRecoverabilityEvaluator().evaluate(
        evaluated_at=NOW,
        requirement=_requirement(required_energy_wh=7000.0, hours=4.0),
        storage_state=_state(),
        storage_limit=limit,
        capability=_capability(max_power_w=4000.0),
    )

    assert result.extra_energy_required_wh == pytest.approx(2000.0)
    assert result.maximum_charge_energy_before_deadline_wh == pytest.approx(2000.0)
    assert result.technically_recoverable is True


def test_source_is_not_part_of_technical_recoverability_result() -> None:
    result = StorageTechnicalRecoverabilityEvaluator().evaluate(
        evaluated_at=NOW,
        requirement=_requirement(),
        storage_state=_state(),
        storage_limit=_limit(),
        capability=_capability(),
    )

    assert not hasattr(result, "charge_source_policy")
    assert not hasattr(result, "grid_allowed")


def test_unavailable_storage_capability_is_rejected() -> None:
    capability = LogicalCapabilitySnapshot(
        capability_id="storage-capability-1",
        execution_scope_id="battery-1",
        supported_primitives=(ExecutionPrimitive.CHARGE_AT_POWER,),
        availability=CapabilityAvailability.UNAVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=NOW,
        confidence=0.98,
        source_mapping_id="mapping-1",
        adapter_contract_version="v1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
        maximum_power_w=2000.0,
    )

    with pytest.raises(ValueError, match="must be available"):
        StorageTechnicalRecoverabilityEvaluator().evaluate(
            evaluated_at=NOW,
            requirement=_requirement(),
            storage_state=_state(),
            storage_limit=_limit(),
            capability=capability,
        )


def test_missing_maximum_charge_power_is_rejected() -> None:
    capability = LogicalCapabilitySnapshot(
        capability_id="storage-capability-1",
        execution_scope_id="battery-1",
        supported_primitives=(ExecutionPrimitive.CHARGE_AT_POWER,),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=NOW,
        confidence=0.98,
        source_mapping_id="mapping-1",
        adapter_contract_version="v1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
    )

    with pytest.raises(ValueError, match="maximum charge power"):
        StorageTechnicalRecoverabilityEvaluator().evaluate(
            evaluated_at=NOW,
            requirement=_requirement(),
            storage_state=_state(),
            storage_limit=_limit(),
            capability=capability,
        )
