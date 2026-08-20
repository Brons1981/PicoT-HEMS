from __future__ import annotations

from datetime import UTC, datetime

from picot.addon.live_storage_constraints import (
    build_effective_storage_limit,
    build_live_storage_capabilities,
)
from picot.domain.current_storage_state import CurrentStorageState

BASE = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _state() -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id="storage-live",
        execution_scope_id="storage-primary",
        capability_id="storage-primary-energy",
        current_soc=0.5,
        usable_capacity_wh=8000.0,
        measured_at=BASE,
        confidence=1.0,
        evidence_ids=("zendure",),
    )


def test_missing_max_power_keeps_storage_capability_fail_closed() -> None:
    capabilities = build_live_storage_capabilities(
        captured_at=BASE,
        snapshot_id="live-1",
        maximum_charge_power_w=None,
        power_step_w=None,
        maximum_soc=0.95,
    )

    assert capabilities.capabilities == ()


def test_explicit_storage_config_builds_capability_without_telemetry_inference() -> None:
    capabilities = build_live_storage_capabilities(
        captured_at=BASE,
        snapshot_id="live-2",
        maximum_charge_power_w=3200.0,
        power_step_w=100.0,
        maximum_soc=0.95,
        minimum_soc=0.10,
    )

    capability = capabilities.capabilities[0]
    assert capability.maximum_power_w == 3200.0
    assert capability.power_step_w == 100.0
    assert capability.maximum_soc == 0.95
    assert capability.minimum_soc == 0.10
    assert capability.source_mapping_id == "configured-storage-primary"


def test_effective_limit_uses_canonical_storage_capacity_and_configured_soc() -> None:
    limit = build_effective_storage_limit(
        storage_state=_state(),
        maximum_soc=0.95,
        sequence=7,
    )

    assert limit.usable_capacity_wh == 8000.0
    assert limit.max_soc == 0.95
    assert limit.max_energy_wh == 7600.0
