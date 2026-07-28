"""PicoT capability schema.

Capability IDs describe stable semantics. Integrations and entity names are only
candidate evidence and must never become part of these IDs.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    id: str
    category: str
    kind: str
    description: str


CAPABILITIES = (
    # Canonical logical battery-system observations used by planning.
    Capability("battery.system.observation.soc", "battery", "observation", "Logical battery-system state of charge"),
    Capability("battery.system.observation.power", "battery", "observation", "Logical battery-system instantaneous power"),
    Capability("battery.system.observation.energy", "battery", "observation", "Logical battery-system measured energy"),
    Capability("battery.system.observation.capacity.total", "battery", "observation", "Logical battery-system total capacity"),
    Capability("battery.system.observation.capacity.usable", "battery", "observation", "Logical battery-system usable capacity"),
    Capability("battery.system.observation.module_count", "battery", "observation", "Number of installed battery modules"),

    # Externally managed battery configuration. PicoT observes these values and
    # respects them in planning; ownership/write access is resolved separately.
    Capability("battery.system.configuration.soc_min", "battery", "configuration", "Configured minimum battery-system state of charge"),
    Capability("battery.system.configuration.soc_max", "battery", "configuration", "Configured maximum battery-system state of charge"),

    # Per-module observations are diagnostic and may not substitute system data.
    Capability("battery.module.observation.soc", "battery", "observation", "Individual battery-module state of charge"),
    Capability("battery.module.observation.temperature", "battery", "observation", "Individual battery-module temperature"),
    Capability("battery.module.observation.health", "battery", "observation", "Individual battery-module health"),
    Capability("battery.module.observation.balance_status", "battery", "observation", "Individual battery-module balance status"),

    # Existing control semantics remain stable during the observation migration.
    Capability("battery.control.charge", "battery", "control", "Charge battery"),
    Capability("battery.control.discharge", "battery", "control", "Discharge battery"),
    Capability("battery.control.standby", "battery", "control", "Standby battery"),

    Capability("pv.observation.power", "pv", "observation", "PV power"),
    Capability("pv.observation.energy", "pv", "observation", "PV energy"),
    Capability("grid.observation.import_power", "grid", "observation", "Grid import power"),
    Capability("grid.observation.export_power", "grid", "observation", "Grid export power"),
    Capability("grid.observation.import_energy", "grid", "observation", "Grid import energy"),
    Capability("grid.observation.export_energy", "grid", "observation", "Grid export energy"),
    Capability("market.price.current", "market", "observation", "Current energy price"),
    Capability("market.price.forecast", "market", "observation", "Forecast energy prices"),
    Capability("weather.forecast", "weather", "observation", "Weather forecast"),
    Capability("device.switch", "device", "control", "Switch control"),
    Capability("device.number", "device", "control", "Numeric control"),
    Capability("device.select", "device", "control", "Select control"),
    Capability("device.button", "device", "control", "Button control"),
)


def get_capabilities() -> tuple[Capability, ...]:
    return CAPABILITIES
