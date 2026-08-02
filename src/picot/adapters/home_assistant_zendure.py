"""Normalize selected Home Assistant Zendure entities into a PicoT snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ZendureSnapshot:
    """Read-only Zendure observation for validation and dashboarding."""

    status: str
    source: str
    observed_at: datetime
    soc_percent: float
    actual_mode: str
    requested_mode: str
    signed_power_w: float
    charge_power_w: float
    discharge_power_w: float
    power_to_house_w: float
    power_from_house_w: float
    soc_limit_status: str
    error_status: str
    power_consistent: bool


class ZendureSnapshotError(ValueError):
    """Raised when required Zendure state cannot be normalized."""


def _entity(states: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any]:
    state = states.get(entity_id)
    if state is None:
        raise ZendureSnapshotError(f"Missing Zendure entity: {entity_id}.")
    if state.get("state") in {None, "unknown", "unavailable"}:
        raise ZendureSnapshotError(f"Zendure entity is unavailable: {entity_id}.")
    return state


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ZendureSnapshotError(f"{field} is not numeric.")
    try:
        return float(value)
    except ValueError as exc:
        raise ZendureSnapshotError(f"{field} is not numeric.") from exc


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ZendureSnapshotError(f"{field} is not text.")
    return value.strip()


def zendure_snapshot_from_entities(
    states: dict[str, dict[str, Any]],
    *,
    observed_at: datetime,
    consistency_tolerance_w: float = 25.0,
) -> ZendureSnapshot:
    """Build one atomic read-only Zendure snapshot from validated entities."""

    if observed_at.tzinfo is None:
        raise ZendureSnapshotError("observed_at must be timezone-aware.")
    if consistency_tolerance_w < 0:
        raise ZendureSnapshotError("consistency_tolerance_w must be non-negative.")

    soc = _number(
        _entity(states, "sensor.zendure_2400_ac_laadpercentage").get("state"),
        "soc_percent",
    )
    if not 0.0 <= soc <= 100.0:
        raise ZendureSnapshotError("soc_percent must be between 0 and 100.")

    actual_mode = _text(
        _entity(states, "sensor.zendure_2400_ac_modus").get("state"),
        "actual_mode",
    )
    requested_mode = _text(
        _entity(states, "input_select.zendure_2400_ac_modus_selecteren").get("state"),
        "requested_mode",
    )
    signed_power_w = _number(
        _entity(states, "sensor.zendure_2400_ac_vermogen_aansturing").get("state"),
        "signed_power_w",
    )
    power_to_house_w = _number(
        _entity(states, "sensor.zendure_2400_ac_vermogen_naar_huis").get("state"),
        "power_to_house_w",
    )
    power_from_house_w = _number(
        _entity(states, "sensor.zendure_2400_ac_vermogen_van_huis").get("state"),
        "power_from_house_w",
    )
    soc_limit_status = _text(
        _entity(states, "sensor.zendure_2400_ac_soc_limiet_status").get("state"),
        "soc_limit_status",
    )
    error_status = _text(
        _entity(states, "sensor.zendure_2400_ac_error").get("state"),
        "error_status",
    )

    charge_power_w = max(0.0, signed_power_w)
    discharge_power_w = max(0.0, -signed_power_w)
    power_consistent = (
        abs(discharge_power_w - power_to_house_w) <= consistency_tolerance_w
        and abs(charge_power_w - power_from_house_w) <= consistency_tolerance_w
    )

    return ZendureSnapshot(
        status="available",
        source="Home Assistant Zendure HA ZenSDK",
        observed_at=observed_at,
        soc_percent=soc,
        actual_mode=actual_mode,
        requested_mode=requested_mode,
        signed_power_w=signed_power_w,
        charge_power_w=charge_power_w,
        discharge_power_w=discharge_power_w,
        power_to_house_w=power_to_house_w,
        power_from_house_w=power_from_house_w,
        soc_limit_status=soc_limit_status,
        error_status=error_status,
        power_consistent=power_consistent,
    )
