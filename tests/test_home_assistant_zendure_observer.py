from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from picot.addon.zendure_observer import (
    DEFAULT_ZENDURE_POWER_ENTITY,
    read_zendure_observation,
    unavailable_zendure_observation,
    zendure_entity_ids,
)

OBSERVED_AT = datetime(2026, 8, 2, 18, 0, tzinfo=UTC)


def _states() -> dict[str, dict[str, Any]]:
    return {
        "sensor.zendure_2400_ac_laadpercentage": {"state": "82"},
        "sensor.zendure_2400_ac_modus": {"state": "Ontladen"},
        "input_select.zendure_2400_ac_modus_selecteren": {
            "state": "Alleen slim ontladen"
        },
        DEFAULT_ZENDURE_POWER_ENTITY: {"state": "-86"},
        "sensor.zendure_2400_ac_vermogen_naar_huis": {"state": "86"},
        "sensor.zendure_2400_ac_vermogen_van_huis": {"state": "0"},
        "sensor.zendure_2400_ac_soc_limiet_status": {"state": "Binnen limiet"},
        "sensor.zendure_2400_ac_error": {"state": "Geen fout"},
    }


def test_read_zendure_observation_normalizes_all_selected_entities() -> None:
    states = _states()
    requested_paths: list[str] = []

    def request_json(path: str, token: str) -> dict[str, Any]:
        assert token == "token"
        requested_paths.append(path)
        return states[path.removeprefix("/api/states/")]

    event = read_zendure_observation(
        request_json,
        "token",
        observed_at=OBSERVED_AT,
        power_entity=DEFAULT_ZENDURE_POWER_ENTITY,
    )

    assert requested_paths == [
        f"/api/states/{entity_id}"
        for entity_id in zendure_entity_ids(DEFAULT_ZENDURE_POWER_ENTITY)
    ]
    assert event["zendure_status"] == "available"
    assert event["zendure_power_entity"] == DEFAULT_ZENDURE_POWER_ENTITY
    assert event["zendure_soc_percent"] == 82.0
    assert event["zendure_actual_mode"] == "Ontladen"
    assert event["zendure_requested_mode"] == "Alleen slim ontladen"
    assert event["zendure_signed_power_w"] == -86.0
    assert event["zendure_charge_power_w"] == 0.0
    assert event["zendure_discharge_power_w"] == 86.0
    assert event["zendure_power_consistent"] is True
    assert event["zendure_observed_at"] == OBSERVED_AT.isoformat()


def test_unavailable_zendure_observation_is_explicit() -> None:
    event = unavailable_zendure_observation(
        RuntimeError("Zendure unavailable"),
        observed_at=OBSERVED_AT,
    )

    assert event["zendure_status"] == "unavailable"
    assert event["zendure_error"] == "Zendure unavailable"
    assert event["zendure_soc_percent"] is None
    assert event["zendure_power_consistent"] is None
