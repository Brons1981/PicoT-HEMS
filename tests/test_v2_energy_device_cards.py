from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picot.v2.energy_device_cards import (
    EnergyDeviceCard,
    EnergyDevicePlacementStore,
    HomeAssistantEnergyDeviceCatalogReader,
)


def _card() -> dict[str, object]:
    return {
        "card_id": "energy-device-card:dryer",
        "device_id": "dryer",
        "name": "Droger",
        "availability": "available",
        "active": False,
        "current_power_w": 0.0,
        "expected_power_w": 900.0,
        "expected_duration_seconds": 3600.0,
        "expected_energy_wh": 900.0,
        "confidence": 0.65,
        "completed_session_count": 4,
        "profile_status": "ready",
        "profile_revision": 4,
        "last_observed_at": "2026-09-06T10:00:00+00:00",
        "method_version": "observed-device-sessions:v1",
    }


class _Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_catalog_reader_accepts_only_neutral_observer_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "state": "ready",
        "attributes": {
            "schema_version": 1,
            "producer": "picot-energy-devices",
            "revision": 3,
            "generated_at": "2026-09-06T10:00:00+00:00",
            "observer_only": True,
            "planning_authority": False,
            "cards": [_card()],
        },
    }
    monkeypatch.setattr(
        "picot.v2.energy_device_cards.urlopen",
        lambda request, timeout: _Response(payload),
    )

    catalog = HomeAssistantEnergyDeviceCatalogReader(
        "token", "sensor.picot_energy_devices_catalog"
    ).read()

    assert catalog.status == "available"
    assert catalog.cards[0].name == "Droger"
    assert catalog.as_public_dict()["planning_authority"] is False


def test_bad_catalog_is_optional_and_yields_no_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "picot.v2.energy_device_cards.urlopen",
        lambda request, timeout: _Response(
            {"state": "ready", "attributes": {"schema_version": 99}}
        ),
    )
    catalog = HomeAssistantEnergyDeviceCatalogReader(
        "token", "sensor.picot_energy_devices_catalog"
    ).read()

    assert catalog.status == "unavailable"
    assert catalog.cards == ()
    assert catalog.error is not None


def test_user_placement_is_persistent_and_observer_only(tmp_path: Path) -> None:
    path = tmp_path / "placements.json"
    store = EnergyDevicePlacementStore(path)
    card = EnergyDeviceCard.from_payload(_card())
    start = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

    result = store.update(
        {
            "action": "add",
            "card_id": card.card_id,
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
        },
        available_cards=(card,),
        now=datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
    )

    assert result["observer_only"] is True
    assert result["planning_authority"] is False
    assert len(EnergyDevicePlacementStore(path).public_view()["placements"]) == 1  # type: ignore[arg-type]


def test_unknown_card_cannot_be_placed(tmp_path: Path) -> None:
    store = EnergyDevicePlacementStore(tmp_path / "placements.json")
    with pytest.raises(ValueError, match="currently available"):
        store.update(
            {
                "action": "add",
                "card_id": "unknown",
                "starts_at": "2026-09-07T12:00:00+00:00",
                "ends_at": "2026-09-07T13:00:00+00:00",
            },
            available_cards=(),
        )
