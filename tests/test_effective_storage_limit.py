from __future__ import annotations

from datetime import UTC, datetime

import pytest

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.effective_storage_limit import EffectiveStorageLimit


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _state(*, scope: str = "battery-1", capacity_wh: float = 8000.0) -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id="state-1",
        execution_scope_id=scope,
        capability_id="storage-capability-1",
        current_soc=0.5,
        usable_capacity_wh=capacity_wh,
        measured_at=NOW,
        confidence=0.95,
        evidence_ids=("sensor:soc",),
    )


def _limit(*, scope: str = "battery-1", capacity_wh: float = 8000.0) -> EffectiveStorageLimit:
    return EffectiveStorageLimit(
        limit_id="limit-1",
        execution_scope_id=scope,
        max_soc=0.95,
        usable_capacity_wh=capacity_wh,
        confidence=1.0,
        evidence_ids=("config:max-soc",),
        method_version="effective-storage-limit-v1",
    )


def test_effective_limit_derives_maximum_plannable_energy() -> None:
    limit = _limit()

    assert limit.max_energy_wh == pytest.approx(7600.0)


def test_effective_limit_is_validated_against_same_storage_scope() -> None:
    limit = _limit()

    limit.validate_against(_state())


def test_effective_limit_rejects_different_storage_scope() -> None:
    with pytest.raises(ValueError, match="share a scope"):
        _limit().validate_against(_state(scope="battery-2"))


def test_effective_limit_rejects_noncanonical_capacity() -> None:
    with pytest.raises(ValueError, match="canonical usable storage capacity"):
        _limit(capacity_wh=7000.0).validate_against(_state())


def test_effective_limit_rejects_soc_above_one() -> None:
    with pytest.raises(ValueError, match="Effective maximum SoC"):
        EffectiveStorageLimit(
            limit_id="limit-invalid",
            execution_scope_id="battery-1",
            max_soc=1.01,
            usable_capacity_wh=8000.0,
            confidence=1.0,
            evidence_ids=("config:max-soc",),
            method_version="effective-storage-limit-v1",
        )
