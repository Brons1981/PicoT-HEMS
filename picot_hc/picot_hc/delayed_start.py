"""Bounded advisory start-time choices while downstairs heat sources are off."""

import copy
import math

from .energy_model import EnergyModel, finite, meter_context
from .hourly_weather import planning_models, upper


def idle_context(config, states, plan, meter, view, now):
    window = view.get("next")
    sources = plan.get("sources", {})
    if (
        not window
        or view.get("current")
        or plan.get("preheating")
        or not view["settings"].get("enabled")
        or not view["settings"].get("learning_enabled")
        or any(s in plan.get("desired", {}) for s in ("beneden", "cv"))
        or any(
            sources.get(s, {}).get("state") != "off" or sources[s].get("pending")
            for s in ("beneden", "cv")
        )
    ):
        return None
    return meter_context(config, states, plan, meter, now, target=window["target"])


class StandbyEvidence:
    """A fresh fifteen-minute off-state trace; never assume missing power is zero."""

    def __init__(self):
        self.points = []

    def observe(self, sample, now):
        if sample is None or not 0 <= sample["power_w"] <= 100:
            self.points = []
            return
        if self.points:
            previous = self.points[-1]
            if (
                not 0 < now - previous["time"] <= 90
                or not EnergyModel.same(sample, previous)
                or sample["energy_wh"] < previous["energy_wh"]
            ):
                self.points = []
        self.points.append(dict(copy.deepcopy(sample), time=now))
        while len(self.points) > 1 and now - self.points[1]["time"] >= 900:
            self.points.pop(0)

    def estimate(self, now):
        if not self.points or not 0 <= now - self.points[-1]["time"] <= 90:
            return None
        first, last = self.points[0], self.points[-1]
        elapsed = last["time"] - first["time"]
        if elapsed < 900:
            return None
        used = last["energy_wh"] - first["energy_wh"]
        integrated = sum(
            (a["power_w"] + b["power_w"]) / 2 * (b["time"] - a["time"]) / 3600
            for a, b in zip(self.points, self.points[1:], strict=False)
        )
        if abs(used - integrated) > max(2, used * 0.3):
            return None
        return max(max(p["power_w"] for p in self.points), used * 3600 / elapsed) * 1.25 + 2


def candidates(
    sample,
    view,
    plan,
    startup,
    steady,
    standby_w,
    now,
    start,
    end,
    *,
    fixed_start=None,
    cooling=None,
):
    window = view.get("next")
    learning = plan.get("learning_status", {})
    rate = learning.get("cooling_rate")
    floor = plan.get("zones", {}).get("beneden", {}).get("target")
    sources = plan.get("sources", {})
    if (
        sample is None
        or not window
        or view.get("current")
        or plan.get("preheating")
        or not plan.get("enabled")
        or not view["settings"].get("enabled")
        or not view["settings"].get("learning_enabled")
        or any(s in plan.get("desired", {}) for s in ("beneden", "cv"))
        or any(
            sources.get(s, {}).get("state") != "off"
            or sources[s].get("pending")
            or not sources[s].get("available")
            for s in ("beneden", "cv")
        )
        or not finite(rate)
        or rate < 0
        or learning.get("cooling_samples", 0) < 3
        or not finite(floor)
        or not finite(standby_w)
        or standby_w < 0
        or not now < start < window["starts_at"] < end <= window["ends_at"]
        or end - now > 15 * 3600
    ):
        return []
    source = sources["beneden"]
    low, high, step = (source.get(k) for k in ("minimum", "maximum", "step"))
    target = window["target"]
    if (
        not source.get("temperature_supported")
        or not all(finite(v) for v in (low, high, step))
        or step <= 0
        or not low <= target <= high
        or not math.isclose((target - low) / step, round((target - low) / step), abs_tol=1e-5)
        or abs(sample["target"] - target) > 0.05
        or target - sample["indoor"] < 0.5
    ):
        return []
    forecast = plan.get("hourly_weather")
    if forecast and forecast.get("status") != "unsupported" and cooling is None:
        return []
    bounded = planning_models(plan, [startup, steady], sample, now, now, end, cooling)
    if bounded is None:
        return []
    (startup, steady), future_rate = bounded
    if future_rate is not None:
        rate = max(rate, future_rate)
    holding = steady.estimate(dict(sample, indoor=target), now)
    if holding["power_w"] is None or not 0 < holding["power_w"] <= 20000:
        return []
    result = []
    starts = [fixed_start] if fixed_start is not None else [start + i * 900 for i in range(5)]
    for offset, heat_start in enumerate(starts):
        if not finite(heat_start) or heat_start < start:
            continue
        if heat_start - now > 3600:
            break
        cold = sample["indoor"] - rate * (heat_start - now) / 3600
        if cold < floor:
            continue
        # Require measured support throughout the possible start-temperature interval.
        count = max(1, math.ceil((sample["indoor"] - cold) / 0.25))
        estimates = [
            startup.estimate(dict(sample, indoor=cold + (sample["indoor"] - cold) * i / count), now)
            for i in range(count + 1)
        ]
        if any(e["energy_wh"] is None or e["duration_seconds"] is None for e in estimates):
            continue
        energy = max(e["energy_wh"] for e in estimates)
        duration = max(e["duration_seconds"] for e in estimates)
        reached = heat_start + duration
        if not 0 < energy * 3600 / duration <= 20000 or reached > window["starts_at"]:
            continue
        slots = []
        if heat_start > start:
            slots.append(
                dict(
                    starts_at=start,
                    ends_at=heat_start,
                    energy_wh=standby_w * (heat_start - start) / 3600,
                )
            )
        slots.extend(
            [
                dict(starts_at=heat_start, ends_at=reached, energy_wh=energy),
                dict(
                    starts_at=reached,
                    ends_at=end,
                    energy_wh=holding["power_w"] * (end - reached) / 3600,
                ),
            ]
        )
        result.append(
            dict(
                plan_id="start_" + str(offset),
                hourly_forecast_used=bool(forecast and forecast.get("status") == "ready"),
                target=target,
                heat_starts_at=heat_start,
                reaches_at=reached,
                predicted_start_minimum=cold,
                cooling_rate=rate,
                samples=min(e["samples"] for e in estimates),
                standby_w=standby_w,
                startup_estimate=upper(estimates),
                startup_energy_wh=energy,
                startup_duration_seconds=duration,
                maintenance=holding,
                slots=slots,
            )
        )
    return result
