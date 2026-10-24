"""Optional dedicated CV meter; no estimated or substituted electricity."""

import json
from datetime import datetime

from .core import observation
from .energy_model import finite


def cv_electricity(config, states, now):
    power, energy = config.get("cv_power"), config.get("cv_energy")
    if not power and not energy:
        return dict(status="not_configured")
    if not power or not energy or config.get("cv_meter_scope_confirmed") is not True:
        return dict(status="unconfirmed_configuration")
    zone_meters = {z.get(k) for z in config["zones"] for k in ("power", "energy")}
    if power == energy or power in zone_meters or energy in zone_meters:
        return dict(status="shared_meter")
    values, times = [], []
    for entity, unit in ((power, "W"), (energy, "kWh")):
        value = observation(entity, states, now, True, unit)
        try:
            stamp = datetime.fromisoformat(
                (value["source_reported"] or value["source_updated"]).replace("Z", "+00:00")
            )
            if (
                value["quality"] != "available"
                or value.get("report_error")
                or value["value"] < 0
                or stamp.utcoffset() is None
                or not 0 <= now - stamp.timestamp() <= 60
            ):
                return dict(status="unavailable")
        except (ValueError, TypeError, AttributeError):
            return dict(status="unavailable")
        values.append(value["value"])
        times.append(stamp.timestamp())
    return dict(
        status="available",
        identity=json.dumps([power, energy]),
        power_w=values[0],
        energy_kwh=values[1],
        reported_at=times[1],
    )


def advance(session, sample):
    """An interrupted trace stays invalid for this entire warmup attempt."""
    current = sample.get("electricity", {})
    previous = session["previous"].get("electricity", {})
    if (
        current.get("status") != "available"
        or previous.get("status") != "available"
        or current.get("identity") != previous.get("identity")
        or current.get("energy_kwh", -1) < previous.get("energy_kwh", 0)
        or current.get("reported_at", 0) < previous.get("reported_at", 0)
        or current.get("reported_at") == previous.get("reported_at")
        and current.get("energy_kwh") != previous.get("energy_kwh")
    ):
        session["electricity_valid"] = False


def result(session, sample):
    if not session["electricity_valid"]:
        return dict(status="incomplete_or_unavailable")
    first, last = session["sample"]["electricity"], sample["electricity"]
    energy_wh = (last["energy_kwh"] - first["energy_kwh"]) * 1000
    if not finite(energy_wh) or last["reported_at"] < session["reached"] + 120:
        return dict(status="incomplete_or_unavailable")
    return dict(
        status="measured",
        identity=first["identity"],
        energy_wh=energy_wh,
        start_reported_at=first["reported_at"],
        end_reported_at=last["reported_at"],
    )
