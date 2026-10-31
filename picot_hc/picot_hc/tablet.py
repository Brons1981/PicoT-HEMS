"""Tablet projection and read-only energy observer; no device control authority."""

import base64
import copy
import secrets
import threading
import time

from .core import fetch_states, observation, timestamp

ENERGY_ENTITIES = {
    "grid": "sensor.ct_shelly_pro_3em_api",
    "pv": "sensor.inverter_54200dsn211r0265_vermogen",
    "charge": "sensor.zendure_2400_ac_vermogen_van_huis",
    "discharge": "sensor.zendure_2400_ac_vermogen_naar_huis",
    "soc": "sensor.zendure_2400_ac_laadpercentage",
    "mode": "input_select.zendure_2400_ac_modus_selecteren",
}


def entities(config):
    return {
        key: config.get("tablet_" + key + "_entity", default)
        for key, default in ENERGY_ENTITIES.items()
    }


def authorized(header, password):
    """Only a separate local tablet password; never the HA credential."""
    if not isinstance(password, str) or len(password) < 12:
        return False
    try:
        scheme, value = header.split(" ", 1)
        supplied = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return False
    return scheme.lower() == "basic" and secrets.compare_digest(
        supplied, ("tablet:" + password).encode("utf-8")
    )


def numeric_sample(entity, states, now, unit, max_age):
    point = observation(entity, states, now, True, unit)
    if point["quality"] != "available" or point.get("report_error"):
        return None
    try:
        age = now - timestamp(point.get("source_reported") or point.get("source_updated"))
    except (ValueError, TypeError, OverflowError):
        return None
    return point["value"] if 0 <= age <= max_age else None


def energy_view(config, states, now):
    mapping = entities(config)
    values = {
        key: numeric_sample(
            entity, states, now, "%" if key == "soc" else "W", 300 if key == "soc" else 30
        )
        for key, entity in mapping.items()
        if key != "mode"
    }
    grid, pv, charge, discharge, soc = (
        values[k] for k in ("grid", "pv", "charge", "discharge", "soc")
    )
    pv = pv if pv is not None and pv >= 0 else None
    if charge is None or discharge is None or min(charge, discharge) < 0:
        battery = None
    elif charge > 10 and discharge > 10:
        battery = None  # Contradictory channels are not a measured net direction.
    else:
        battery = discharge - charge
    home = grid + pv + battery if all(v is not None for v in (grid, pv, battery)) else None
    home = max(0, home) if home is not None and home >= -10 else None
    # Source colours express possible concurrent supplies, not measured electron attribution.
    grid_source = None
    if grid is not None and grid < 0 and pv is not None and battery is not None:
        grid_source = (
            "mixed"
            if pv > 0 and battery > 0
            else "battery"
            if battery > 0
            else "pv"
            if pv > 0
            else None
        )
    battery_source = None
    if battery is not None and battery < 0 and grid is not None and pv is not None:
        battery_source = (
            "mixed" if grid > 0 and pv > 0 else "grid" if grid > 0 else "pv" if pv > 0 else None
        )
    mode = observation(mapping["mode"], states, now)
    return dict(
        grid_w=grid,
        pv_w=pv,
        battery_w=battery,
        home_w=home,
        soc=soc if soc is not None and 0 <= soc <= 100 else None,
        mode=mode["value"] if mode["quality"] == "available" else None,
        grid_source=grid_source,
        battery_source=battery_source,
        stale=any(v is None for v in (grid, pv, battery)),
    )


class EnergyReader:
    """A bounded independent reader; tablet polling never invokes the planner."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.Lock()
        self.states = {}
        self.received = None

    def run(self):
        while not self.runtime.stop.is_set():
            try:
                mapping = entities(self.runtime.config)
                states = fetch_states(
                    self.runtime.url,
                    self.runtime.token,
                    [v for k, v in mapping.items() if k != "mode"],
                )
                with self.lock:
                    self.states, self.received = states, time.time()
            except Exception:
                with self.lock:
                    self.states, self.received = {}, None
            self.runtime.stop.wait(5)

    def view(self, now):
        with self.lock:
            fresh = self.received is not None and 0 <= now - self.received <= 20
            states = copy.deepcopy(self.states) if fresh else {}
        return energy_view(self.runtime.config, states, now)


def tablet_view(runtime, now=None):
    now = time.time() if now is None else now
    with runtime.control.lock:
        schedule = runtime.schedule.view(now)
        heating = runtime.heating.view(runtime.config, now)
        fresh = (
            runtime.control.connected
            and runtime.control.received is not None
            and 0 <= now - runtime.control.received <= runtime.config["stale_seconds"]
        )
        states = runtime.control.states if fresh else {}
        zone = next(z for z in runtime.config["zones"] if z["id"] == "beneden")
        inside = numeric_sample(
            zone["temperature"],
            states,
            now,
            "\u00b0C",
            schedule["settings"]["sensor_max_age_seconds"],
        )
        outside = numeric_sample(
            runtime.config["outdoor"],
            states,
            now,
            "\u00b0C",
            schedule["settings"]["sensor_max_age_seconds"],
        )
        weather = observation(runtime.config.get("weather_entity", ""), states, now)
        holds = [v for v in schedule["overrides"] if v["active"] and "beneden" in v["zones"]]
        request = schedule["comfort"]["zones"]["beneden"]["request"] or {}
        temporary = schedule.get("temporary_temperature")
        enabled = heating["enabled"]
        error = (
            "HC niet bereikbaar of metingen verouderd."
            if not fresh or inside is None
            else "Automatische verwarming staat uit in HC."
            if not enabled
            else "Handmatige bronbediening actief; hervat eerst in HC."
            if holds
            else None
        )
        result = dict(
            csrf_token=runtime.csrf_token,
            revision=schedule["revision"],
            inside=inside,
            outside=outside,
            target=request.get("target"),
            manual=bool(temporary or holds or not schedule["settings"]["enabled"]),
            scheduled=schedule["settings"]["enabled"],
            heat=bool(fresh and enabled and heating["zones"].get("beneden", {}).get("demand")),
            weather=weather["value"] if weather["quality"] == "available" else None,
            stale=not fresh or inside is None,
            controllable=error is None,
            error=error,
        )
    result["energy"] = runtime.tablet_energy.view(now)
    return result
