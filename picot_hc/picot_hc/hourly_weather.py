"""Optional, strictly hourly HA forecast; separate from observed learning samples."""

import copy
import json
import math
import time
from typing import Literal, TypedDict
from urllib.request import Request, build_opener

from .core import NoRedirect, timestamp

Status = Literal["ready", "unsupported", "unavailable", "stale"]


class Forecast(TypedDict):
    type: Literal["hourly"]
    status: Status
    entity_id: str
    received: float | None
    intervals: list[dict]


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def parse(rows, entity, attrs):
    if not isinstance(rows, list) or not 2 <= len(rows) <= 192:
        raise ValueError("invalid_hourly_rows")
    factor = {"m/s": 1, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444}.get(
        attrs.get("wind_speed_unit")
    )
    unit = attrs.get("temperature_unit")
    if factor is None or unit not in ("°C", "°F"):
        raise ValueError("unknown_forecast_units")
    points = []
    for row in rows:
        at = timestamp(row["datetime"])
        temperature, wind = row.get("temperature"), row.get("wind_speed")
        if not numeric(temperature) or not numeric(wind):
            raise ValueError("missing_forecast_measurement")
        outdoor = (temperature - 32) / 1.8 if unit == "°F" else temperature
        wind *= factor
        if not -60 <= outdoor <= 60 or not 0 <= wind <= 75:
            raise ValueError("invalid_forecast_measurement")
        cloud = row.get("cloud_coverage")
        condition = row.get("condition")
        if numeric(cloud) and 0 <= cloud <= 100:
            sky = "clear" if cloud <= 20 else "overcast" if cloud >= 80 else "mixed"
        else:
            sky = {
                "sunny": "clear",
                "clear-night": "clear",
                "cloudy": "overcast",
                "partlycloudy": "mixed",
                "rainy": "overcast",
                "pouring": "overcast",
                "snowy": "overcast",
                "snowy-rainy": "overcast",
            }.get(condition)
        if sky is None:
            raise ValueError("missing_forecast_cloud")
        day = row.get("is_daytime")
        if type(day) is not bool:
            # Cloudy hourly forecasts normally omit day/night. Require both evidence
            # populations later; never copy the current sun state into a future hour.
            day = True if condition == "sunny" else False if condition == "clear-night" else None
        points.append(
            dict(
                time=at,
                outdoor=outdoor,
                weather=dict(source=entity, wind_m_s=wind, sky=sky, daylight=day),
            )
        )
    if any(b["time"] - a["time"] != 3600 for a, b in zip(points, points[1:], strict=False)):
        raise ValueError("forecast_not_contiguous_hourly")
    # Last point has no following boundary and cannot prove a final interval.
    return [
        dict(starts_at=a["time"], ends_at=b["time"], outdoor=a["outdoor"], weather=a["weather"])
        for a, b in zip(points, points[1:], strict=False)
    ]


def fetch(url, token, entity, attrs):
    if not token:
        raise ValueError("HA token missing")
    request = Request(
        url.rstrip("/") + "/services/weather/get_forecasts?return_response",
        data=json.dumps(dict(entity_id=entity, type="hourly")).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with build_opener(NoRedirect).open(request, timeout=10) as response:
        rows = json.load(response)["service_response"][entity]["forecast"]
    return parse(rows, entity, attrs)


class HourlyWeather:
    def __init__(self, entity):
        self.entity, self.next_attempt = entity, 0
        self.data = Forecast(
            type="hourly", status="unsupported", entity_id=entity, received=None, intervals=[]
        )

    def collect(self, states, now, url, token):
        item = states.get(self.entity) or {}
        attrs = item.get("attributes") or {}
        supported = attrs.get("supported_features")
        if type(supported) is not int or supported < 0 or not supported & 2:
            self.data = dict(self.data, status="unsupported", received=None, intervals=[])
            self.next_attempt = 0
            return self.view(now)
        if item.get("state") in (None, "unknown", "unavailable"):
            self.data = dict(self.data, status="unavailable", intervals=[])
            self.next_attempt = 0
            return self.view(now)
        if time.monotonic() >= self.next_attempt:
            self.next_attempt = time.monotonic() + 300
            try:
                intervals = fetch(url, token, self.entity, attrs)
                self.data = Forecast(
                    type="hourly",
                    status="ready",
                    entity_id=self.entity,
                    received=now,
                    intervals=intervals,
                )
                self.next_attempt = time.monotonic() + 1800
            except Exception:
                self.data = dict(self.data, status="unavailable", intervals=[])
        return self.view(now)

    def view(self, now):
        result = copy.deepcopy(self.data)
        if result["status"] == "ready" and (
            not numeric(result["received"]) or not 0 <= now - result["received"] <= 3600
        ):
            result["status"] = "stale"
            result["intervals"] = []
        return result


def contexts(forecast, start, end, now):
    """Return complete future conditions, or None; never bridge a forecast gap."""
    if (
        not isinstance(forecast, dict)
        or forecast.get("type") != "hourly"
        or forecast.get("status") != "ready"
        or not numeric(forecast.get("received"))
        or not 0 <= now - forecast["received"] <= 3600
        or not now <= start < end
    ):
        return None
    cursor, result = start, []
    for row in forecast.get("intervals", []):
        if row["ends_at"] <= cursor:
            continue
        if row["starts_at"] > cursor:
            return None
        point = dict(outdoor=row["outdoor"], weather=copy.deepcopy(row["weather"]))
        if point["weather"]["daylight"] is None:
            for day in (False, True):
                result.append(dict(point, weather=dict(point["weather"], daylight=day)))
        else:
            result.append(point)
        cursor = min(end, row["ends_at"])
        if cursor == end:
            return result
    return None


def upper(values):
    """Conservative envelope; a missing estimate in any condition stays missing."""
    first = values[0]
    if any(v is None for v in values):
        return None
    if isinstance(first, dict):
        return {
            key: (
                min(v[key] for v in values)
                if key in ("samples", "cooling_samples")
                else upper([v[key] for v in values])
            )
            for key in first
        }
    if all(numeric(v) for v in values):
        return max(values)
    return copy.deepcopy(first)


class BoundedModel:
    def __init__(self, model, points):
        self.model, self.points = model, points

    def estimate(self, sample, now):
        return upper([self.model.estimate(dict(sample, **point), now) for point in self.points])


def planning_models(plan, models, sample, now, start, end, cooling=None):
    forecast = plan.get("hourly_weather")
    if forecast is None or forecast.get("status") == "unsupported":
        return models, None
    points = contexts(forecast, start, end, now)
    if not points:
        return None
    rate = None
    if cooling is not None:
        thermal = dict(plan.get("learning_context") or {}, indoor=sample["indoor"])
        values = [cooling.estimate(dict(thermal, **point), now) for point in points]
        if any(v.get("cooling_rate") is None for v in values):
            return None
        rate = max(v["cooling_rate"] for v in values)
    return [BoundedModel(model, points) for model in models], rate
