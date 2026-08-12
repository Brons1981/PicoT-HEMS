from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalanceAssembler,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)


CAPTURED = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
END = CAPTURED + timedelta(minutes=30)


def _storage() -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id="storage-state-1",
        execution_scope_id="battery-1",
        capability_id="storage-capability-1",
        current_soc=0.5,
        usable_capacity_wh=8000.0,
        measured_at=CAPTURED,
        confidence=0.95,
        evidence_ids=("sensor:soc",),
    )


def _pv() -> PVEnergyTimeline:
    before = CAPTURED - timedelta(minutes=15)
    return PVEnergyTimeline(
        timeline_id="pv-1",
        created_at=CAPTURED,
        horizon_start=before,
        horizon_end=END,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=before,
                ends_at=CAPTURED,
                energy_wh=500.0,
                evidence_type=PVEnergyEvidenceType.ACTUAL,
                confidence=1.0,
                evidence_ids=("pv:actual",),
            ),
            PVEnergyTimelineInterval(
                starts_at=CAPTURED,
                ends_at=CAPTURED + timedelta(minutes=15),
                energy_wh=300.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.9,
                evidence_ids=("pv:forecast:1",),
            ),
            PVEnergyTimelineInterval(
                starts_at=CAPTURED + timedelta(minutes=15),
                ends_at=END,
                energy_wh=200.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("pv:forecast:2",),
            ),
        ),
    )


def _load() -> HouseholdLoadForecast:
    return HouseholdLoadForecast(
        forecast_id="load-1",
        created_at=CAPTURED,
        horizon_start=CAPTURED,
        horizon_end=END,
        intervals=(
            HouseholdLoadForecastInterval(
                starts_at=CAPTURED,
                ends_at=CAPTURED + timedelta(minutes=15),
                expected_energy_wh=100.0,
                confidence=0.85,
            ),
            HouseholdLoadForecastInterval(
                starts_at=CAPTURED + timedelta(minutes=15),
                ends_at=END,
                expected_energy_wh=400.0,
                confidence=0.75,
            ),
        ),
        historical_source_reference="history:comparable-days",
        method_version="load-v1",
    )


def test_balance_uses_current_storage_and_future_pv_minus_future_load() -> None:
    balance = ProjectedHouseholdEnergyBalanceAssembler().assemble(
        balance_id="balance-1",
        captured_at=CAPTURED,
        storage_state=_storage(),
        pv_timeline=_pv(),
        load_forecast=_load(),
    )

    assert balance.starting_storage_energy_wh == 4000.0
    assert balance.points[0].projected_storage_energy_wh == 4200.0
    assert balance.points[1].projected_storage_energy_wh == 4000.0


def test_elapsed_actual_pv_is_not_counted_again() -> None:
    balance = ProjectedHouseholdEnergyBalanceAssembler().assemble(
        balance_id="balance-1",
        captured_at=CAPTURED,
        storage_state=_storage(),
        pv_timeline=_pv(),
        load_forecast=_load(),
    )

    assert balance.points[-1].cumulative_pv_energy_wh == 500.0
    assert balance.points[-1].projected_storage_energy_wh == 4000.0


def test_v1_explicitly_excludes_grid_commitments_and_losses() -> None:
    balance = ProjectedHouseholdEnergyBalanceAssembler().assemble(
        balance_id="balance-1",
        captured_at=CAPTURED,
        storage_state=_storage(),
        pv_timeline=_pv(),
        load_forecast=_load(),
    )

    assert balance.planned_grid_energy_applied is False
    assert balance.known_future_demand_applied is False
    assert balance.conversion_losses_applied is False


def test_balance_confidence_is_conservative_minimum_of_inputs() -> None:
    balance = ProjectedHouseholdEnergyBalanceAssembler().assemble(
        balance_id="balance-1",
        captured_at=CAPTURED,
        storage_state=_storage(),
        pv_timeline=_pv(),
        load_forecast=_load(),
    )

    assert balance.confidence == pytest.approx(0.75)


def test_v1_requires_aligned_future_interval_boundaries() -> None:
    load = HouseholdLoadForecast(
        forecast_id="load-misaligned",
        created_at=CAPTURED,
        horizon_start=CAPTURED,
        horizon_end=END,
        intervals=(
            HouseholdLoadForecastInterval(
                starts_at=CAPTURED,
                ends_at=END,
                expected_energy_wh=500.0,
                confidence=0.8,
            ),
        ),
        historical_source_reference="history:fallback",
        method_version="load-v1",
    )

    with pytest.raises(ValueError, match="boundaries must align"):
        ProjectedHouseholdEnergyBalanceAssembler().assemble(
            balance_id="balance-1",
            captured_at=CAPTURED,
            storage_state=_storage(),
            pv_timeline=_pv(),
            load_forecast=load,
        )
