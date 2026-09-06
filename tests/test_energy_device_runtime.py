from datetime import UTC, datetime
from pathlib import Path

import pytest

from picot_energy_devices.home_assistant import HomeAssistantClient
from picot_energy_devices.runtime import poll_once
from picot_energy_devices.store import EnergyDeviceStore


class _Client:
    def __init__(self) -> None:
        self.published: dict[str, object] | None = None

    def state(self, entity_id: str) -> dict[str, object]:
        assert entity_id == "sensor.wasmachine_power"
        return {"state": "0.8", "attributes": {"unit_of_measurement": "kW"}}

    def measurement(self, payload: dict[str, object], *, quantity: str) -> float:
        assert quantity == "power"
        return 800.0

    def publish_catalog(self, entity_id: str, catalog: dict[str, object]) -> None:
        assert entity_id == "sensor.picot_energy_devices_catalog"
        self.published = catalog


def test_poll_reads_measurements_and_publishes_neutral_catalog(tmp_path: Path) -> None:
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3")
    store.add_device(name="Wasmachine", power_entity_id="sensor.wasmachine_power")
    client = _Client()

    poll_once(
        store=store,
        client=client,  # type: ignore[arg-type]
        catalog_entity_id="sensor.picot_energy_devices_catalog",
        observed_at=datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
    )

    assert client.published is not None
    assert client.published["observer_only"] is True
    assert client.published["planning_authority"] is False
    assert client.published["cards"][0]["active"] is True  # type: ignore[index]


def test_energy_devices_runtime_has_no_service_call_path() -> None:
    files = (Path(__file__).parents[1] / "src" / "picot_energy_devices").glob("*.py")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "/api/services/" not in combined


@pytest.mark.parametrize("state", ["nan", "inf", "-inf"])
def test_non_finite_sensor_values_are_rejected(state: str) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        HomeAssistantClient.measurement(
            {"state": state, "attributes": {"unit_of_measurement": "W"}},
            quantity="power",
        )
