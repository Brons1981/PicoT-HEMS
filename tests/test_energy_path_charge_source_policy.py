from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _segment(**overrides: object) -> PathSegment:
    values: dict[str, object] = {
        "segment_id": "segment-1",
        "order": 1,
        "execution_scope_id": "battery-1",
        "starts_at": NOW,
        "ends_at": NOW + timedelta(hours=1),
        "primitive": ExecutionPrimitive.CHARGE_AT_POWER,
        "capability_id": "storage-1",
        "purpose": "Charge storage.",
        "evidence_ids": ("requirement-1",),
        "requested_power_w": 2000.0,
        "charge_source_policy": ChargeSourcePolicy.PV_ONLY,
    }
    values.update(overrides)
    return PathSegment(**values)  # type: ignore[arg-type]


def test_charging_segment_carries_explicit_pv_only_policy() -> None:
    segment = _segment()

    assert segment.charge_source_policy is ChargeSourcePolicy.PV_ONLY
    assert segment.charge_source_policy.permits_grid_import is False


def test_charging_segment_can_explicitly_allow_grid_supplementation() -> None:
    segment = _segment(
        charge_source_policy=ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED,
    )

    assert segment.charge_source_policy is ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED
    assert segment.charge_source_policy.permits_grid_import is True


def test_charging_segment_rejects_implicit_source_permission() -> None:
    with pytest.raises(ValueError, match="explicit charge source policy"):
        _segment(charge_source_policy=None)


def test_non_charging_segment_rejects_charge_source_policy() -> None:
    with pytest.raises(ValueError, match="only valid for charging"):
        _segment(
            primitive=ExecutionPrimitive.DISCHARGE_AT_POWER,
            charge_source_policy=ChargeSourcePolicy.PV_ONLY,
        )
