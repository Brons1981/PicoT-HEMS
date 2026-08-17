from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from picot.v2.remaining_pv_storage_feasibility import (
    derive_remaining_pv_storage_feasibility,
)


def test_conservative_margin_uses_lower_pv_range_until_storage_deadline() -> None:
    captured_at = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    ends_at = captured_at + timedelta(hours=1)
    storage = SimpleNamespace(
        storage_state_id="storage-1",
        current_stored_energy_wh=5000.0,
    )
    pv_interval = SimpleNamespace(
        starts_at=captured_at,
        ends_at=ends_at,
        forecast_range_status="available",
        forecast_lower_energy_wh=1500.0,
        pv_energy_wh=2200.0,
        confidence=0.40,
        forecast_evidence_ids=("pv-lower-1",),
        actual_evidence_ids=(),
    )
    balance_interval = SimpleNamespace(
        starts_at=captured_at,
        ends_at=ends_at,
        household_load_forecast_energy_wh=500.0,
        evidence_ids=("load-1",),
    )
    balance = SimpleNamespace(
        balance_id="balance-1",
        intervals=(balance_interval,),
    )
    requirement = SimpleNamespace(
        projected_balance_id="balance-1",
        required_energy_wh=8160.0,
        required_by=ends_at,
        evidence_ids=("requirement-1",),
    )
    snapshot = SimpleNamespace(
        captured_at=captured_at,
        current_storage_states=(storage,),
        pv_energy_timeline=SimpleNamespace(intervals=(pv_interval,)),
    )

    result = derive_remaining_pv_storage_feasibility(
        snapshot,
        requirements=(requirement,),
        balances=(balance,),
    )

    assert result.status == "available"
    assert result.remaining_storage_need_wh == 3160.0
    assert result.conservative_remaining_pv_surplus_wh == 1000.0
    assert result.margin_wh == -2160.0
    assert result.evidence_ids == (
        "requirement-1",
        "pv-lower-1",
        "load-1",
    )


def test_missing_requirement_fails_closed_as_unavailable() -> None:
    snapshot = SimpleNamespace(
        pv_energy_timeline=SimpleNamespace(intervals=()),
        current_storage_states=(),
    )

    result = derive_remaining_pv_storage_feasibility(
        snapshot,
        requirements=(),
        balances=(),
    )

    assert result.status == "unavailable"
    assert result.margin_wh is None
