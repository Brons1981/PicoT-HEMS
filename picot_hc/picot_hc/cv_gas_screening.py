"""Detect observed DHW contamination; polling cannot prove heating-only gas."""

from datetime import datetime

from .core import observation


def gas_screening(config, states, now):
    entity = config.get("cv_dhw_active")
    if not entity:
        return dict(status="not_configured")
    # A general thermostat/heat-demand status is not a DHW signal.
    if entity in (config.get("cv"), config.get("cv_status"), config.get("gas")):
        return dict(status="invalid_configuration")
    point = observation(entity, states, now)
    try:
        stamp = datetime.fromisoformat(
            (point["source_reported"] or point["source_updated"]).replace("Z", "+00:00")
        )
        if (
            point["quality"] != "available"
            or point.get("report_error")
            or point["value"] not in ("on", "off")
            or stamp.utcoffset() is None
            or not 0 <= now - stamp.timestamp() <= 60
        ):
            return dict(status="unavailable")
    except (ValueError, TypeError, AttributeError):
        return dict(status="unavailable")
    return dict(status="available", identity=entity, active=point["value"] == "on")


def advance_screening(session, sample):
    first = session["sample"].get("gas_screening", {})
    current = sample.get("gas_screening", {})
    evidence = session.setdefault("gas_screening", dict(dhw_observed=False, complete=True))
    for point in (first, current):
        if point.get("status") == "available" and point.get("active") is True:
            evidence["dhw_observed"] = True
        if point.get("status") != "available":
            evidence["complete"] = False
    if first.get("identity") != current.get("identity"):
        evidence["complete"] = False


def screening_result(session):
    evidence = session["gas_screening"]
    if evidence["dhw_observed"]:
        status = "dhw_observed"
    elif evidence["complete"]:
        status = "no_dhw_observed"
    else:
        status = "incomplete"
    return dict(status=status, polling_complete=evidence["complete"], heating_only_confirmed=False)
