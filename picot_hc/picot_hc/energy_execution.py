"""Report observed execution of an approved profile, without device details."""

from .energy_model import finite
from .energy_proposals import stamp

ENTITY = "sensor.picot_hc_energy_execution"


def execution_receipt(intent, control, config, now):
    current = intent.current
    unavailable = dict(state="unavailable", attributes={})
    if (
        not current
        or not current.get("command_id")
        or not current.get("selection")
        or not control.connected
        or control.received is None
        or not 0 <= now - control.received <= config["stale_seconds"]
    ):
        return unavailable
    command = next((c for c in control.records() if c["id"] == current["command_id"]), None)
    if (
        not command
        or command["status"] != "confirmed"
        or not finite(command.get("sent"))
        or command["sent"] > now
    ):
        return unavailable
    entity = control.bindings[current.get("source", "beneden")]["entity_id"]
    observed = control.states.get(entity, {})
    temperature = observed.get("attributes", {}).get("temperature")
    if observed.get("state") == "off":
        status = "finished"
    elif (
        observed.get("state") == "heat"
        and finite(temperature)
        and abs(temperature - current["target"]) < 0.05
    ):
        status = "running"
    else:
        return unavailable  # Unknown or changed operation cannot erase accepted demand.
    if now >= current["recipe"]["slots"][-1]["ends_at"]:
        status = "finished"
    selected = current["selection"]
    return dict(
        state=status,
        attributes=dict(
            contract="hc-energy-execution:v1",
            status=status,
            request_id=selected["request_id"],
            request_fingerprint=selected["request_fingerprint"],
            selected_plan_id=selected["selected_plan_id"],
            executed_at=stamp(command["sent"]),
            reported_at=stamp(now),
        ),
    )


RESERVATION_ENTITY = "sensor.picot_hc_energy_reservation"


def reservation_receipt(intent, control, heating, config, now):
    from .delayed_start import idle_context
    from .energy_measurement import measurement

    current = intent.current
    unavailable = dict(state="unavailable", attributes={})
    if (
        not current
        or not current.get("selection")
        or current.get("command_id")
        or not control.connected
        or control.received is None
        or not 0 <= now - control.received <= config["stale_seconds"]
    ):
        return unavailable
    plan, view = heating.view(config, now), heating.schedule.view(now)
    sample = idle_context(
        config, control.states, plan, measurement(config, control.states, now), view, now
    )
    reserved = (
        view["settings"].get("energy_start_enabled") is True
        and plan.get("price") is not None
        and not any(s in heating.data["faults"] for s in ("beneden", "cv"))
        and intent.valid(sample, view, plan, now)
    )
    status = "reserved" if reserved else "cancelled"
    selected = current["selection"]
    # Allow the last heartbeat to bridge command feedback and HEMS polling.
    # The start window itself is still enforced by EnergyStart.
    until = now + 120
    return dict(
        state=status,
        attributes=dict(
            contract="hc-energy-reservation:v1",
            status=status,
            request_id=selected["request_id"],
            request_fingerprint=selected["request_fingerprint"],
            selected_plan_id=selected["selected_plan_id"],
            reported_at=stamp(now),
            valid_until=stamp(until),
        ),
    )
