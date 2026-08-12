"""Read selected Zendure entities directly through Home Assistant."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from picot.adapters.home_assistant_zendure import zendure_snapshot_from_entities

DEFAULT_ZENDURE_POWER_ENTITY = "sensor.zendure_2400_ac_vermogen_aansturing"
ZENDURE_SOC_ENTITY = "sensor.zendure_2400_ac_laadpercentage"
ZENDURE_ACTUAL_MODE_ENTITY = "sensor.zendure_2400_ac_modus"
ZENDURE_REQUESTED_MODE_ENTITY = "input_select.zendure_2400_ac_modus_selecteren"
ZENDURE_POWER_TO_HOUSE_ENTITY = "sensor.zendure_2400_ac_vermogen_naar_huis"
ZENDURE_POWER_FROM_HOUSE_ENTITY = "sensor.zendure_2400_ac_vermogen_van_huis"
ZENDURE_SOC_LIMIT_ENTITY = "sensor.zendure_2400_ac_soc_limiet_status"
ZENDURE_ERROR_ENTITY = "sensor.zendure_2400_ac_error"
ZENDURE_REPORTED_MIN_SOC_ENTITY = "sensor.zendure_2400_ac_minimale_laadpercentage"
ZENDURE_REPORTED_MAX_SOC_ENTITY = "sensor.zendure_2400_ac_maximale_laadpercentage"
ZENDURE_ALLOWED_MAX_SOC_ENTITY = (
    "input_number.zendure_2400_ac_maximaal_toegestaan_laadpercentage"
)
ZENDURE_ALLOWED_MIN_SOC_ENTITY = (
    "input_number.zendure_2400_ac_minimaal_toegestaan_laadpercentage"
)
ZENDURE_AVAILABLE_ENERGY_ENTITY = "sensor.zendure_2400_ac_indicatie_beschikbare_energie"
ZENDURE_REQUIRED_ENERGY_ENTITY = "sensor.zendure_2400_ac_indicatie_benodigde_energie"
ZENDURE_REMAINING_DISCHARGE_TIME_ENTITY = "sensor.zendure_2400_ac_resterende_ontlaad_tijd"
ZENDURE_REMAINING_CHARGE_TIME_ENTITY = "sensor.zendure_2400_ac_resterende_oplaad_tijd"
ZENDURE_CONFIGURED_DISCHARGE_POWER_ENTITY = "sensor.zendure_2400_ac_ingesteld_ontlaadvermogen"
ZENDURE_CONFIGURED_CHARGE_POWER_ENTITY = "sensor.zendure_2400_ac_ingesteld_oplaadvermogen"

RequestJson = Callable[[str, str], dict[str, Any]]


def zendure_entity_ids(power_entity: str) -> tuple[str, ...]:
    """Return the direct Zendure source entities used for one observation."""

    return (
        ZENDURE_SOC_ENTITY,
        ZENDURE_ACTUAL_MODE_ENTITY,
        ZENDURE_REQUESTED_MODE_ENTITY,
        power_entity,
        ZENDURE_POWER_TO_HOUSE_ENTITY,
        ZENDURE_POWER_FROM_HOUSE_ENTITY,
        ZENDURE_SOC_LIMIT_ENTITY,
        ZENDURE_ERROR_ENTITY,
        ZENDURE_REPORTED_MIN_SOC_ENTITY,
        ZENDURE_REPORTED_MAX_SOC_ENTITY,
        ZENDURE_ALLOWED_MAX_SOC_ENTITY,
        ZENDURE_ALLOWED_MIN_SOC_ENTITY,
        ZENDURE_AVAILABLE_ENERGY_ENTITY,
        ZENDURE_REQUIRED_ENERGY_ENTITY,
        ZENDURE_REMAINING_DISCHARGE_TIME_ENTITY,
        ZENDURE_REMAINING_CHARGE_TIME_ENTITY,
        ZENDURE_CONFIGURED_DISCHARGE_POWER_ENTITY,
        ZENDURE_CONFIGURED_CHARGE_POWER_ENTITY,
    )


def _percentage_state(states: dict[str, dict[str, Any]], entity_id: str) -> float | None:
    value = _numeric_state(states, entity_id)
    if value is None or not 0.0 <= value <= 100.0:
        return None
    return value


def _numeric_state(states: dict[str, dict[str, Any]], entity_id: str) -> float | None:
    payload = states.get(entity_id)
    if not isinstance(payload, dict):
        return None
    raw = payload.get("state")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _raw_state(states: dict[str, dict[str, Any]], entity_id: str) -> object | None:
    payload = states.get(entity_id)
    return payload.get("state") if isinstance(payload, dict) else None


def read_zendure_observation(
    request_json: RequestJson,
    token: str,
    *,
    observed_at: datetime,
    power_entity: str = DEFAULT_ZENDURE_POWER_ENTITY,
) -> dict[str, object]:
    """Return normalized fields read directly from configured HA sources."""

    states: dict[str, dict[str, Any]] = {}
    for entity_id in zendure_entity_ids(power_entity):
        states[entity_id] = request_json(f"/api/states/{entity_id}", token)

    if power_entity != DEFAULT_ZENDURE_POWER_ENTITY:
        states[DEFAULT_ZENDURE_POWER_ENTITY] = states[power_entity]

    snapshot = zendure_snapshot_from_entities(states, observed_at=observed_at)
    return {
        "zendure_status": snapshot.status,
        "zendure_source": snapshot.source,
        "zendure_power_entity": power_entity,
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
        "zendure_allowed_min_soc_percent": _percentage_state(states, ZENDURE_ALLOWED_MIN_SOC_ENTITY),
        "zendure_allowed_max_soc_percent": _percentage_state(states, ZENDURE_ALLOWED_MAX_SOC_ENTITY),
        "zendure_reported_min_soc_percent": _percentage_state(states, ZENDURE_REPORTED_MIN_SOC_ENTITY),
        "zendure_reported_max_soc_percent": _percentage_state(states, ZENDURE_REPORTED_MAX_SOC_ENTITY),
        "zendure_available_energy": _numeric_state(states, ZENDURE_AVAILABLE_ENERGY_ENTITY),
        "zendure_required_energy": _numeric_state(states, ZENDURE_REQUIRED_ENERGY_ENTITY),
        "zendure_remaining_discharge_time": _raw_state(states, ZENDURE_REMAINING_DISCHARGE_TIME_ENTITY),
        "zendure_remaining_charge_time": _raw_state(states, ZENDURE_REMAINING_CHARGE_TIME_ENTITY),
        "zendure_configured_discharge_power_w": _numeric_state(states, ZENDURE_CONFIGURED_DISCHARGE_POWER_ENTITY),
        "zendure_configured_charge_power_w": _numeric_state(states, ZENDURE_CONFIGURED_CHARGE_POWER_ENTITY),
        "zendure_allowed_min_soc_entity": ZENDURE_ALLOWED_MIN_SOC_ENTITY,
        "zendure_allowed_max_soc_entity": ZENDURE_ALLOWED_MAX_SOC_ENTITY,
        "zendure_reported_min_soc_entity": ZENDURE_REPORTED_MIN_SOC_ENTITY,
        "zendure_reported_max_soc_entity": ZENDURE_REPORTED_MAX_SOC_ENTITY,
        "zendure_available_energy_entity": ZENDURE_AVAILABLE_ENERGY_ENTITY,
        "zendure_required_energy_entity": ZENDURE_REQUIRED_ENERGY_ENTITY,
    }


def unavailable_zendure_observation(
    error: Exception,
    *,
    observed_at: datetime,
    power_entity: str = DEFAULT_ZENDURE_POWER_ENTITY,
) -> dict[str, object]:
    """Return an explicit unavailable observation without stopping PicoT."""

    return {
        "zendure_status": "unavailable",
        "zendure_source": "Home Assistant Zendure HA ZenSDK",
        "zendure_power_entity": power_entity,
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
        "zendure_allowed_min_soc_percent": None,
        "zendure_allowed_max_soc_percent": None,
        "zendure_reported_min_soc_percent": None,
        "zendure_reported_max_soc_percent": None,
        "zendure_available_energy": None,
        "zendure_required_energy": None,
        "zendure_remaining_discharge_time": None,
        "zendure_remaining_charge_time": None,
        "zendure_configured_discharge_power_w": None,
        "zendure_configured_charge_power_w": None,
        "zendure_allowed_min_soc_entity": ZENDURE_ALLOWED_MIN_SOC_ENTITY,
        "zendure_allowed_max_soc_entity": ZENDURE_ALLOWED_MAX_SOC_ENTITY,
        "zendure_reported_min_soc_entity": ZENDURE_REPORTED_MIN_SOC_ENTITY,
        "zendure_reported_max_soc_entity": ZENDURE_REPORTED_MAX_SOC_ENTITY,
        "zendure_available_energy_entity": ZENDURE_AVAILABLE_ENERGY_ENTITY,
        "zendure_required_energy_entity": ZENDURE_REQUIRED_ENERGY_ENTITY,
    }
