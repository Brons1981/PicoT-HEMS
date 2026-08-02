"""Read selected Zendure entities through Home Assistant without influencing planning."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from picot.adapters.home_assistant_zendure import zendure_snapshot_from_entities

ZENDURE_ENTITY_IDS = (
    "sensor.zendure_2400_ac_laadpercentage",
    "sensor.zendure_2400_ac_modus",
    "input_select.zendure_2400_ac_modus_selecteren",
    "sensor.zendure_2400_ac_vermogen_aansturing",
    "sensor.zendure_2400_ac_vermogen_naar_huis",
    "sensor.zendure_2400_ac_vermogen_van_huis",
    "sensor.zendure_2400_ac_soc_limiet_status",
    "sensor.zendure_2400_ac_error",
)

RequestJson = Callable[[str, str], dict[str, Any]]


def read_zendure_observation(
    request_json: RequestJson,
    token: str,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Return normalized dashboard fields from one atomic Zendure snapshot."""

    states: dict[str, dict[str, Any]] = {}
    for entity_id in ZENDURE_ENTITY_IDS:
        states[entity_id] = request_json(f"/api/states/{entity_id}", token)

    snapshot = zendure_snapshot_from_entities(states, observed_at=observed_at)
    return {
        "zendure_status": snapshot.status,
        "zendure_source": snapshot.source,
        "zendure_error": None,
        "zendure_observed_at": snapshot.observed_at.isoformat(),
        "zendure_soc_percent": snapshot.soc_percent,
        "zendure_actual_mode": snapshot.actual_mode,
        "zendure_requested_mode": snapshot.requested_mode,
        "zendure_signed_power_w": snapshot.signed_power_w,
        "zendure_charge_power_w": snapshot.charge_power_w,
        "zendure_discharge_power_w": snapshot.discharge_power_w,
        "zendure_power_to_house_w": snapshot.power_to_house_w,
        "zendure_power_from_house_w": snapshot.power_from_house_w,
        "zendure_soc_limit_status": snapshot.soc_limit_status,
        "zendure_error_status": snapshot.error_status,
        "zendure_power_consistent": snapshot.power_consistent,
    }


def unavailable_zendure_observation(
    error: Exception,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Return an explicit unavailable observation without stopping PicoT."""

    return {
        "zendure_status": "unavailable",
        "zendure_source": "Home Assistant Zendure HA ZenSDK",
        "zendure_error": str(error) or error.__class__.__name__,
        "zendure_observed_at": observed_at.isoformat(),
        "zendure_soc_percent": None,
        "zendure_actual_mode": None,
        "zendure_requested_mode": None,
        "zendure_signed_power_w": None,
        "zendure_charge_power_w": None,
        "zendure_discharge_power_w": None,
        "zendure_power_to_house_w": None,
        "zendure_power_from_house_w": None,
        "zendure_soc_limit_status": None,
        "zendure_error_status": None,
        "zendure_power_consistent": None,
    }
