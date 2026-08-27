from datetime import UTC, datetime

import pytest

from picot.domain.storage_energy_inventory import (
    StorageEnergyInventory,
    StorageEnergyLot,
)

NOW = datetime(2026, 8, 27, 18, tzinfo=UTC)


def test_inventory_values_the_cheapest_known_energy_before_unknown_energy() -> None:
    inventory = StorageEnergyInventory(
        execution_scope_id="battery",
        captured_at=NOW,
        measured_stored_energy_wh=5000.0,
        lots=(
            StorageEnergyLot("unknown", 2000.0, None, NOW, ("soc",)),
            StorageEnergyLot("grid", 1000.0, 0.10, NOW, ("grid-charge",)),
            StorageEnergyLot("pv", 2000.0, 0.02, NOW, ("pv-charge",)),
        ),
    )

    allocation = inventory.cheapest_known_allocation(
        maximum_deliverable_energy_wh=1788.0,
        discharge_efficiency=0.894,
    )

    assert allocation.stored_energy_wh == pytest.approx(2000.0)
    assert allocation.deliverable_energy_wh == pytest.approx(1788.0)
    assert allocation.acquisition_cost_eur == pytest.approx(0.02)
    assert allocation.sources == ("pv",)


def test_inventory_never_assigns_an_invented_cost_to_unknown_energy() -> None:
    inventory = StorageEnergyInventory(
        execution_scope_id="battery",
        captured_at=NOW,
        measured_stored_energy_wh=3000.0,
        lots=(
            StorageEnergyLot("unknown", 2000.0, None, NOW, ("soc",)),
            StorageEnergyLot("grid", 1000.0, 0.15, NOW, ("grid-charge",)),
        ),
    )

    allocation = inventory.cheapest_known_allocation(
        maximum_deliverable_energy_wh=2500.0,
        discharge_efficiency=1.0,
    )

    assert allocation.stored_energy_wh == pytest.approx(1000.0)
    assert allocation.acquisition_cost_eur == pytest.approx(0.15)
