"""Neutral, consumer-independent energy-device card contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

CATALOG_SCHEMA_VERSION = 1
PROFILE_METHOD_VERSION = "manual-device-recordings:v2"


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DeviceDefinition:
    device_id: str
    name: str
    power_entity_id: str
    energy_entity_id: str | None
    active_threshold_w: float
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for value, label in (
            (self.device_id, "device ID"),
            (self.name, "device name"),
            (self.power_entity_id, "power entity ID"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if not self.power_entity_id.startswith("sensor."):
            raise ValueError("power entity ID must be a sensor")
        if self.energy_entity_id is not None and not self.energy_entity_id.startswith("sensor."):
            raise ValueError("energy entity ID must be a sensor")
        if self.active_threshold_w < 0.0:
            raise ValueError("active threshold must not be negative")
        _aware(self.created_at, "creation time")
        _aware(self.updated_at, "update time")


@dataclass(frozen=True, slots=True)
class DeviceObservation:
    observed_at: datetime
    power_w: float
    energy_meter_wh: float | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observation time")
        if not isfinite(self.power_w) or self.power_w < 0.0:
            raise ValueError("device power must be finite and non-negative")
        if self.energy_meter_wh is not None and (
            not isfinite(self.energy_meter_wh) or self.energy_meter_wh < 0.0
        ):
            raise ValueError("energy meter must be finite and non-negative")
