from pathlib import Path

from picot_energy_devices import __version__


def test_energy_devices_addon_version_and_ingress_are_aligned() -> None:
    root = Path(__file__).parents[1]
    config = (root / "picot_energy_devices" / "config.yaml").read_text(encoding="utf-8")

    assert f'version: "{__version__}"' in config
    assert "ingress: true" in config
    assert "ingress_port: 8100" in config
    assert "homeassistant_api: true" in config
    assert 'catalog_entity_id: "sensor.picot_energy_devices_catalog"' in config


def test_picot_catalog_binding_is_optional_configuration() -> None:
    root = Path(__file__).parents[1]
    config = (root / "picot_hems" / "config.yaml").read_text(encoding="utf-8")

    assert 'energy_device_catalog_entity: "sensor.picot_energy_devices_catalog"' in config
    assert "energy_device_catalog_entity: str" in config
