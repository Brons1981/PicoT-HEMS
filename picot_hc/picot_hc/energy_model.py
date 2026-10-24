"""Empirical electricity for steady downstairs heating; no inferred CV heat."""

import copy
import json
import math
from datetime import datetime

from .thermal_weather import comparable


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def context(config, states, plan, meter, now, *, steady=True):
    sample = meter_context(config, states, plan, meter, now)
    ac = (plan.get("sources") or {}).get("beneden", {})
    own = plan.get("owned", {}).get("beneden", {})
    if (
        sample is None
        or not own
        or own.get("released")
        or ac.get("state") != "heat"
        or ac.get("pending")
        or not finite(ac.get("temperature"))
        or abs(ac["temperature"] - sample["target"]) > 0.05
        or (steady and abs(sample["indoor"] - sample["target"]) > 0.3)
    ):
        return None
    return sample


def meter_context(config, states, plan, meter, now, *, target=None):
    """Fresh thermal and meter observation; does not assert that heat is confirmed."""
    thermal = plan.get("learning_context") or {}
    sources = plan.get("sources") or {}
    ac, cv = sources.get("beneden", {}), sources.get("cv", {})
    if target is None:
        target = plan.get("desired", {}).get("beneden")
    if (
        not plan.get("enabled")
        or not thermal.get("valid")
        or not finite(target)
        or not finite(thermal.get("indoor"))
        or not finite(thermal.get("outdoor"))
        or not ac.get("available")
        or cv.get("state") != "off"
        or not cv.get("available")
        or cv.get("pending")
        or meter.get("status") != "available"
        or not finite(meter.get("power_w"))
        or not 0 <= meter["power_w"] <= 20000
    ):
        return None
    zone = next(z for z in config["zones"] if z["id"] == "beneden")
    counter = states.get(zone.get("energy")) or {}
    try:
        raw = counter.get("state")
        if isinstance(raw, bool):
            return None
        energy = float(raw)
        stamp = counter.get("last_reported") or counter.get("last_updated")
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if (
            not math.isfinite(energy)
            or energy < 0
            or when.utcoffset() is None
            or not 0 <= now - when.timestamp() <= 90
            or (counter.get("attributes") or {}).get("unit_of_measurement") != "kWh"
        ):
            return None
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None
    return dict(
        indoor=thermal["indoor"],
        outdoor=thermal["outdoor"],
        target=target,
        source_id=meter["source_id"],
        identity=thermal["identity"],
        weather=copy.deepcopy(thermal.get("weather")),
        power_w=meter["power_w"],
        energy_wh=energy * 1000,
    )


class EnergyModel:
    def __init__(self, store):
        self.store, self.session = store, None
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS hc_energy_model "
                "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            row = db.execute("SELECT payload FROM hc_energy_model WHERE id=1").fetchone()
        self.records = json.loads(row[0]) if row else []

    @staticmethod
    def same(a, b):
        return (
            a["source_id"] == b["source_id"]
            and a["identity"] == b["identity"]
            and comparable(a, b)
            and abs(a["target"] - b["target"]) < 0.05
        )

    def observe(self, sample, now):
        s = self.session
        if sample is None:
            self.session = None
            return
        if s and (
            not 0 < now - s["last"] <= 90
            or not self.same(s["first"], sample)
            or sample["energy_wh"] < s["previous"]["energy_wh"]
            or abs(sample["outdoor"] - s["first"]["outdoor"]) > 2
            or max(s["high"], sample["indoor"]) - min(s["low"], sample["indoor"]) > 0.3
        ):
            s = self.session = None
        if s is None:
            self.session = dict(
                first=copy.deepcopy(sample),
                previous=copy.deepcopy(sample),
                start=now,
                last=now,
                integrated_wh=0,
                low=sample["indoor"],
                high=sample["indoor"],
            )
            return
        s["integrated_wh"] += (
            (s["previous"]["power_w"] + sample["power_w"]) / 2 * (now - s["last"]) / 3600
        )
        s.update(
            last=now,
            previous=copy.deepcopy(sample),
            low=min(s["low"], sample["indoor"]),
            high=max(s["high"], sample["indoor"]),
        )
        if now - s["start"] < 1200:
            return
        self.session = None  # Disjoint evidence; never bridge a restart or a missing sample.
        used = sample["energy_wh"] - s["first"]["energy_wh"]
        watts = used * 3600 / (now - s["start"])
        if not 50 <= watts <= 16000 or abs(used - s["integrated_wh"]) > max(10, used * 0.3):
            return
        record = dict(
            s["first"],
            measured_at=now,
            duration_seconds=now - s["start"],
            mean_power_w=watts,
            used_wh=used,
        )
        records = [r for r in self.records if 0 <= now - r["measured_at"] <= 7 * 86400]
        records = (records + [record])[-96:]
        with self.store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO hc_energy_model VALUES (1, ?)",
                (json.dumps(records, allow_nan=False),),
            )
        self.records = records

    def estimate(self, sample, now):
        records = (
            []
            if sample is None
            else [
                r
                for r in self.records
                if 0 <= now - r["measured_at"] <= 7 * 86400
                and self.same(r, sample)
                and abs(r["indoor"] - sample["indoor"]) <= 0.3
                and abs(r["outdoor"] - sample["outdoor"]) <= 1.5
            ]
        )
        return dict(
            samples=len(records),
            power_w=max(r["mean_power_w"] for r in records) * 1.25 if len(records) >= 3 else None,
            method="measured_steady_heat_upper_margin",
            margin_fraction=0.25,
        )
