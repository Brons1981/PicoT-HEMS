from dataclasses import fields
from datetime import UTC, datetime

from picot.v2.contracts import CurrentStorageState


def test_adr038_current_storage_state_does_not_duplicate_capability_limits() -> None:
    contract_fields = {field.name for field in fields(CurrentStorageState)}

    assert contract_fields == {
        "storage_state_id",
        "execution_scope_id",
        "capability_id",
        "current_soc",
        "usable_capacity_wh",
        "measured_at",
        "confidence",
        "evidence_ids",
    }

    state = CurrentStorageState(
        storage_state_id="storage-state-home",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home-battery",
        current_soc=0.25,
        usable_capacity_wh=8160.0,
        measured_at=datetime(2026, 8, 16, 8, 0, tzinfo=UTC),
        confidence=1.0,
        evidence_ids=("zendure-soc",),
    )

    assert not hasattr(state, "maximum_charge_power_w")
