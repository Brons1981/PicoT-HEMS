"""Durable downstairs electricity outlook, independent of HEMS start permission.

Daily weather is a labelled cold-side scenario, never an invented hourly forecast.
The source assumption is airco heating; an accepted near-term source plan supersedes it.
"""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta

from .energy_model import finite
from .schedule import TZ, occurrences, wall_time

ENTITY = "sensor.picot_hc_day_ahead"
CONTRACT = "hc-day-ahead:v1"


def stamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def conditions(hourly, daily, when, now, current):
    if hourly.get("status") == "ready" and 0 <= now - (hourly.get("received") or 0) <= 3600:
        row = next(
            (r for r in hourly.get("intervals", []) if r["starts_at"] <= when < r["ends_at"]), None
        )
        if row:
            return row["outdoor"], row.get("weather"), "hourly"
    day = datetime.fromtimestamp(when, TZ).date()
    if not daily.get("stale", True) and daily.get("temperature_unit") in ("°C", "°F"):
        row = next(
            (
                r
                for r in daily.get("rows", [])
                if datetime.fromtimestamp(r["time"], TZ).date() == day
            ),
            None,
        )
        if row:
            values = [row.get(k) for k in ("templow", "temperature") if finite(row.get(k))]
            if values:
                value = min(values)
                if daily["temperature_unit"] == "°F":
                    value = (value - 32) / 1.8
                return value, None, "daily_cold_side_scenario"
    return current, None, "current_outdoor_persistence"


def recent(model, sample, now):
    return [
        r
        for r in model.records
        if 0 <= now - r["measured_at"] <= 7 * 86400
        and r["identity"] == sample["identity"]
        and r["source_id"] == sample["source_id"]
    ]


def steady(model, sample, now):
    estimate = model.estimate(sample, now)
    if finite(estimate.get("power_w")):
        return estimate["power_w"], "learned"
    rows = recent(model, sample, now)
    if not rows:
        return None, "no_energy_measurements"
    # A provisional heat-loss scaling, bounded to comparable temperatures.
    rows = [
        r
        for r in rows
        if r["target"] - r["outdoor"] >= 3
        and abs(r["outdoor"] - sample["outdoor"]) <= 5
        and abs(r["target"] - sample["target"]) <= 3
    ]
    if not rows:
        return None, "no_comparable_energy_measurements"
    watts = (
        max(
            r["mean_power_w"]
            * max(0, sample["target"] - sample["outdoor"])
            / (r["target"] - r["outdoor"])
            for r in rows
        )
        * 1.25
    )
    return min(16000, watts), "provisional_recent_heat_loss_scaling"


def build(settings, enabled, context, source_id, model, warmup, cooling, hourly, daily, now):
    today = datetime.fromtimestamp(now, TZ).date()
    tomorrow = today + timedelta(days=1)
    # Cover remaining today too: tomorrow's forecast stays useful after midnight.
    end = wall_time(tomorrow + timedelta(days=1), 0)
    result = dict(
        contract=CONTRACT,
        scope="beneden",
        source_id=source_id,
        generated_at=stamp(now),
        valid_until=stamp(now + 7200),
        delivery_date=tomorrow.isoformat(),
        timezone="Europe/Amsterdam",
        execution_authorized=False,
        source_assumption="airco",
        status="disabled",
        reasons=[],
        slots=[],
    )
    if not enabled or not settings["enabled"]:
        return result
    if not source_id or not context or not context.get("valid"):
        return dict(result, status="unavailable", reasons=["fresh_thermal_context_required"])
    windows = occurrences(settings, now)
    indoor = context["indoor"]
    slots, reasons = [], set()
    start = now
    job = None
    while start < end:
        finish = min(end, (int(start) // 900 + 1) * 900)
        outdoor, weather, weather_method = conditions(hourly, daily, start, now, context["outdoor"])
        if weather_method != "hourly":
            reasons.add(weather_method)
        window = next((w for w in windows if w["starts_at"] <= start < w["ends_at"]), None)
        target = window["target"] if window else settings["setback_temperature"]
        phase = "maintain" if window else "setback"
        following = next((w for w in windows if w["starts_at"] > start), None)
        lead = settings["initial_preheat_minutes"] * 60
        if settings["learning_enabled"] and following:
            query = dict(
                context,
                source_id=source_id,
                indoor=indoor,
                target=following["target"],
                outdoor=outdoor,
                weather=weather,
            )
            estimate = warmup.estimate(query, now)
            if finite(estimate.get("duration_seconds")):
                lead = min(settings["max_preheat_minutes"] * 60, estimate["duration_seconds"])
            else:
                rows = [
                    r
                    for r in recent(warmup, query, now)
                    if r["target"] - r["indoor"] >= 0.5 and abs(r["outdoor"] - outdoor) <= 5
                ]
                if rows:
                    deficit = max(0, following["target"] - settings["setback_temperature"])
                    lead = min(
                        settings["max_preheat_minutes"] * 60,
                        max(
                            lead,
                            max(
                                r["duration_seconds"] * deficit / (r["target"] - r["indoor"])
                                for r in rows
                            )
                            * 1.25,
                        ),
                    )
            if following["starts_at"] - lead <= start and following["target"] > target:
                target, phase = following["target"], "warmup"
            if start < following["starts_at"] - lead < finish:
                finish = following["starts_at"] - lead
        boundaries = [
            w[k] for w in windows for k in ("starts_at", "ends_at") if start < w[k] < finish
        ]
        if boundaries:
            finish = min(boundaries)
        query = dict(
            context,
            valid=True,
            source_id=source_id,
            indoor=target,
            target=target,
            outdoor=outdoor,
            weather=weather,
        )
        power, method = steady(model, query, now)
        if power is None:
            return dict(result, status="unavailable", reasons=sorted(reasons | {method}))
        if method != "learned":
            reasons.add(method)
        duration = finish - start
        energy = power * duration / 3600
        cooling_estimate = cooling.estimate(dict(query, indoor=indoor), now)
        rate = cooling_estimate.get("cooling_rate")
        if indoor > target + 0.1 and finite(rate):
            cooling_seconds = min(duration, (indoor - target) / max(0.01, rate) * 3600)
            indoor -= rate * cooling_seconds / 3600
            energy *= 1 - cooling_seconds / duration
        elif indoor > target + 0.1:
            # Do not project today's warm room unchanged into tomorrow.
            reasons.add("cooling_unknown_assume_setpoint")
            indoor = target
        if indoor < target - 0.1:
            if job is None or job["target"] != target:
                estimate = warmup.estimate(dict(query, indoor=indoor), now)
                wh, seconds = estimate.get("energy_wh"), estimate.get("duration_seconds")
                if not finite(wh) or not finite(seconds):
                    rows = [
                        r
                        for r in recent(warmup, query, now)
                        if r["target"] - r["indoor"] >= 0.5 and abs(r["outdoor"] - outdoor) <= 5
                    ]
                    if not rows:
                        return dict(
                            result,
                            status="unavailable",
                            reasons=sorted(reasons | {"no_warmup_measurements"}),
                        )
                    wh = (
                        max(r["used_wh"] / (r["target"] - r["indoor"]) for r in rows)
                        * 1.25
                        * (target - indoor)
                    )
                    seconds = (
                        max(r["duration_seconds"] / (r["target"] - r["indoor"]) for r in rows)
                        * 1.25
                        * (target - indoor)
                    )
                    reasons.add("provisional_recent_warmup")
                job = dict(target=target, wh=wh, seconds=max(1, seconds))
            used_seconds = min(duration, job["seconds"])
            fraction = used_seconds / job["seconds"]
            energy = job["wh"] * fraction + power * (duration - used_seconds) / 3600
            indoor += (target - indoor) * fraction
            job["seconds"] -= used_seconds
            job["wh"] *= 1 - fraction
            if job["seconds"] <= 0:
                job = None
            phase = "warmup"
        else:
            job = None
            indoor = max(indoor, target)
        if energy * 3600 / duration > 20000:
            return dict(result, status="unavailable", reasons=["forecast_power_out_of_range"])
        slots.append(
            dict(
                starts_at=stamp(start),
                ends_at=stamp(finish),
                energy_wh=round(energy, 3),
                phase=phase,
                target=target,
                weather_method=weather_method,
                method=method,
            )
        )
        start = finish
    return dict(
        result, status="provisional" if reasons else "ready", reasons=sorted(reasons), slots=slots
    )


class DayAhead:
    def __init__(self, store, publisher):
        self.store, self.publisher = store, publisher
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS hc_day_ahead "
                "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            row = db.execute("SELECT payload FROM hc_day_ahead WHERE id=1").fetchone()
        self.current = json.loads(row[0]) if row else None
        self.last_key, self.last_run = None, 0

    def tick(
        self, settings, enabled, context, source_id, model, warmup, cooling, hourly, daily, now
    ):
        # Regenerate at least every half hour and on noon/date/settings changes.
        local = datetime.fromtimestamp(now, TZ)
        thermal_key = {
            k: (context or {}).get(k) for k in ("valid", "indoor", "outdoor", "identity", "weather")
        }
        if isinstance(thermal_key["weather"], dict):
            thermal_key["weather"] = dict(thermal_key["weather"])
            wind = thermal_key["weather"].get("wind_m_s")
            if finite(wind):
                thermal_key["weather"]["wind_m_s"] = round(wind / 2) * 2
        for name in ("indoor", "outdoor"):
            if finite(thermal_key.get(name)):
                thermal_key[name] = round(thermal_key[name] * 2) / 2
        key = digest(
            [
                settings,
                enabled,
                source_id,
                local.date().isoformat(),
                local.hour >= 12,
                thermal_key,
                hourly.get("received"),
                daily.get("received"),
                model.records,
                warmup.records,
                cooling.samples,
            ]
        )
        if key != self.last_key or now - self.last_run >= 1800:
            value = build(
                settings, enabled, context, source_id, model, warmup, cooling, hourly, daily, now
            )
            value["input_fingerprint"] = key
            value["revision"] = digest(value)
            with self.store.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO hc_day_ahead VALUES (1, ?)",
                    (json.dumps(value, allow_nan=False),),
                )
            self.current, self.last_key, self.last_run = value, key, now
        self.publisher.submit(dict(state=self.current["status"], attributes=self.current))

    def view(self):
        return copy.deepcopy(self.current)

    def failed(self, now):
        self.current = dict(
            contract=CONTRACT,
            status="unavailable",
            slots=[],
            generated_at=stamp(now),
            reasons=["forecast_generation_failed"],
            execution_authorized=False,
        )
        self.last_key = None
        self.publisher.submit(dict(state="unavailable", attributes=self.current))
