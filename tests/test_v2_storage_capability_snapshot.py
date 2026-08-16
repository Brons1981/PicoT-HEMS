from datetime import UTC, datetime
from importlib import import_module

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    EnergyFlowDirection,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.zendure_mode_capabilities import (
    derive_zendure_mode_capability_evidence,
)

CAPTURED_AT = datetime(2026, 8, 16, 13, 0, tzinfo=UTC)
SNAPSHOT_ID = "snapshot-storage-capability-test"
MODE_ENTITY = "input_select.zendure_2400_ac_modus_selecteren"


def _evidence(*, available: bool) -> object:
    payload: dict[str, object] = (
        {
            "state": "Nul op de meter",
            "attributes": {
                "options": [
                    "Standby",
                    "Handmatig",
                    "Nul op de meter",
                    "Alleen slim ontladen",
                    "Alleen slim opladen",
                    "Snel opladen",
                    "Snel ontladen",
                    "Dynamisch NOM",
                ]
            },
        }
        if available
        else {"state": "Nul op de meter", "attributes": {}}
    )
    return derive_zendure_mode_capability_evidence(
        payload,
        captured_at=CAPTURED_AT,
        source_entity_id=MODE_ENTITY,
        capability_id="storage-capability-home-battery",
        execution_scope_id="home-battery",
    )


def _build(evidence: object) -> object:
    module = import_module("picot.v2.storage_capability_snapshot")
    return module.build_storage_capability_snapshot_set(
        evidence,
        snapshot_id=SNAPSHOT_ID,
    )


def test_available_mode_evidence_becomes_vendor_independent_capability() -> None:
    snapshot_set = _build(_evidence(available=True))

    assert snapshot_set.snapshot_id == SNAPSHOT_ID
    assert snapshot_set.captured_at == CAPTURED_AT
    assert snapshot_set.mapping_version == 1
    assert len(snapshot_set.capabilities) == 1
    capability = snapshot_set.capabilities[0]
    assert capability.capability_id == "storage-capability-home-battery"
    assert capability.execution_scope_id == "home-battery"
    assert capability.availability is CapabilityAvailability.AVAILABLE
    assert capability.health is CapabilityHealth.HEALTHY
    assert capability.role is CapabilityRole.ENERGY_STORAGE
    assert capability.confidence == 1.0
    assert capability.supported_primitives == (
        ExecutionPrimitive.STANDBY,
        ExecutionPrimitive.CHARGE_AT_POWER,
        ExecutionPrimitive.DISCHARGE_AT_POWER,
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
        ExecutionPrimitive.BALANCE_CHARGE_ONLY,
    )
    assert capability.flow_directions == (
        EnergyFlowDirection.CHARGE,
        EnergyFlowDirection.DISCHARGE,
        EnergyFlowDirection.BIDIRECTIONAL,
    )
    assert "Zendure" not in repr(capability)
    assert "Nul op de meter" not in repr(capability)


def test_unavailable_mode_evidence_becomes_explicit_unavailable_capability() -> None:
    snapshot_set = _build(_evidence(available=False))

    capability = snapshot_set.capabilities[0]
    assert capability.availability is CapabilityAvailability.UNAVAILABLE
    assert capability.health is CapabilityHealth.INVALID
    assert capability.confidence == 0.0
    assert capability.supported_primitives == ()
    assert capability.flow_directions == ()


def test_planning_input_contract_accepts_atomic_capability_snapshot_set() -> None:
    contracts = import_module("picot.v2.contracts")
    snapshot_set = _build(_evidence(available=True))

    planning_input = contracts.PlanningInputSnapshot(
        run_id="run-storage-capability-test",
        snapshot_id=SNAPSHOT_ID,
        captured_at=CAPTURED_AT,
        picot_version="test",
        architecture_baseline_commit="test",
        pipeline_contract_version=1,
        strategy_id="strategy:no-objectives:v1",
        capability_snapshot_set=snapshot_set,
    )

    assert planning_input.capability_snapshot_set is snapshot_set
