"""Observed weather matching; no invented heat-loss or solar-gain coefficients.

Daily forecasts cannot describe the weather at a particular heating start.
Only fresh observations label evidence. Unlabelled legacy evidence remains a
separate population and can never stand in for measured weather conditions.
"""

import math

from .core import timestamp


def observed(config, states, now):
    entity = config.get("weather_entity")
    item = states.get(entity) or {}
    attrs = item.get("attributes") or {}
    try:
        age = now - timestamp(item.get("last_reported") or item.get("last_updated"))
        if not 0 <= age <= 1800 or item.get("state") in (None, "unknown", "unavailable"):
            return None
        wind = attrs.get("wind_speed")
        factor = {"m/s": 1, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444}.get(
            attrs.get("wind_speed_unit")
        )
        if type(wind) not in (int, float) or not math.isfinite(wind) or factor is None:
            return None
        wind *= factor
        if not 0 <= wind <= 75:
            return None
        cloud = attrs.get("cloud_coverage")
        if type(cloud) in (int, float) and math.isfinite(cloud) and 0 <= cloud <= 100:
            sky = "clear" if cloud <= 20 else "overcast" if cloud >= 80 else "mixed"
        else:
            sky = {
                "sunny": "clear",
                "clear-night": "clear",
                "partlycloudy": "mixed",
                "cloudy": "overcast",
                "rainy": "overcast",
                "pouring": "overcast",
                "snowy": "overcast",
                "snowy-rainy": "overcast",
            }.get(item.get("state"))
        if sky is None:
            return None
        # Separate day/night: clear daytime can include solar gain; clear night cannot.
        sun = states.get("sun.sun", {}).get("state")
        if sun not in ("above_horizon", "below_horizon"):
            return None
        return dict(source=entity, wind_m_s=wind, sky=sky, daylight=sun == "above_horizon")
    except (TypeError, ValueError, OverflowError):
        return None


def comparable(left, right):
    a, b = left.get("weather"), right.get("weather")
    if a is None or b is None:
        return a is None and b is None
    try:
        return (
            a["source"] == b["source"]
            and a["sky"] == b["sky"]
            and a["daylight"] == b["daylight"]
            and abs(a["wind_m_s"] - b["wind_m_s"]) <= 2
        )
    except (KeyError, TypeError):
        return False
