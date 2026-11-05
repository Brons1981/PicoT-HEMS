"""A thermostat in heat mode can be satisfied without a current heat request."""

import math


def passive_idle(source):
    """Only release competing heat with fresh, explicit and satisfied feedback."""
    target, current = source.get("temperature"), source.get("current_temperature")
    return bool(
        source.get("available")
        and not source.get("pending")
        and source.get("state") in ("heat", "auto")
        and source.get("action") == "idle"
        and type(target) in (int, float)
        and math.isfinite(target)
        and type(current) in (int, float)
        and math.isfinite(current)
        and target <= current - 0.3
    )
