"""Measured downstairs airco warmup trajectories, without control or extrapolation."""

import copy
import json

from .energy_model import EnergyModel


class WarmupEnergy:
    def __init__(self, store, *, cold_start=False):
        self.store, self.session = store, None
        self.table = "hc_startup_energy" if cold_start else "hc_warmup_energy"
        with store.connect() as db:
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} "
                "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            row = db.execute(f"SELECT payload FROM {self.table} WHERE id=1").fetchone()
        data = json.loads(row[0]) if row else dict(records=[], attempted=[])
        self.records, self.attempted = data["records"], data["attempted"]

    def save(self, records, attempted):
        with self.store.connect() as db:
            db.execute(
                f"INSERT OR REPLACE INTO {self.table} VALUES (1, ?)",
                (json.dumps(dict(records=records, attempted=attempted), allow_nan=False),),
            )
        self.records, self.attempted = records, attempted

    def observe(self, sample, view, plan, now):
        window = view.get("next") if plan.get("preheating") else view.get("current")
        valid = (
            sample is not None
            and plan.get("enabled")
            and window
            and view["settings"].get("enabled")
            and view["settings"].get("learning_enabled")
            and plan.get("learning_status", {}).get("phase") in ("preheat", "comfort")
            and abs(sample["target"] - window["target"]) < 0.05
        )
        if not valid:
            self.session = None
            return
        s = self.session
        key = window["starts_at"]
        if s and (
            key != s["key"]
            or view["revision"] != s["revision"]
            or not 0 < now - s["last"] <= 90
            or now - s["start"] > 10800
            or not EnergyModel.same(s["first"], sample)
            or sample["energy_wh"] < s["previous"]["energy_wh"]
            or abs(sample["outdoor"] - s["first"]["outdoor"]) > 1.5
            or sample["indoor"] < s["high"] - 0.3
        ):
            self.session = None
            return
        if s is None:
            if (
                not plan.get("preheating")
                or key in self.attempted
                or sample["target"] - sample["indoor"] < 0.5
            ):
                return
            # Persist the attempt before sampling: never resume a partial trajectory after restart.
            self.save(self.records, (self.attempted + [key])[-32:])
            self.session = dict(
                key=key,
                revision=view["revision"],
                first=copy.deepcopy(sample),
                previous=copy.deepcopy(sample),
                start=now,
                last=now,
                high=sample["indoor"],
                integrated_wh=0,
                reached=None,
                confirmed_at=now if sample.get("confirmed_heat", True) else None,
            )
            return
        s["integrated_wh"] += (
            (s["previous"]["power_w"] + sample["power_w"]) / 2 * (now - s["last"]) / 3600
        )
        s.update(previous=copy.deepcopy(sample), last=now, high=max(s["high"], sample["indoor"]))
        if sample.get("confirmed_heat", True) and s["confirmed_at"] is None:
            s["confirmed_at"] = now
        if sample.get("confirmed_heat", True) and sample["indoor"] >= sample["target"]:
            if s["reached"] is None:
                s["reached"] = now
        else:
            s["reached"] = None
        if s["reached"] is None or now - s["reached"] < 120:
            return
        self.session = None
        duration = now - s["start"]
        used = sample["energy_wh"] - s["first"]["energy_wh"]
        if (
            duration < 300
            or not 50 <= used * 3600 / duration <= 16000
            or abs(used - s["integrated_wh"]) > max(10, used * 0.3)
        ):
            return
        record = dict(
            s["first"],
            measured_at=now,
            duration_seconds=duration,
            used_wh=used,
            end_indoor=sample["indoor"],
            confirmation_delay_seconds=s["confirmed_at"] - s["start"],
        )
        records = [r for r in self.records if 0 <= now - r["measured_at"] <= 7 * 86400]
        self.save((records + [record])[-96:], self.attempted)

    def estimate(self, sample, now):
        records = (
            []
            if sample is None
            else [
                r
                for r in self.records
                if 0 <= now - r["measured_at"] <= 7 * 86400
                and EnergyModel.same(r, sample)
                and abs(r["indoor"] - sample["indoor"]) <= 0.25
                and abs(r["outdoor"] - sample["outdoor"]) <= 1.5
            ]
        )
        ready = len(records) >= 3
        return dict(
            samples=len(records),
            energy_wh=max(r["used_wh"] for r in records) * 1.25 if ready else None,
            duration_seconds=max(r["duration_seconds"] for r in records) * 1.25 if ready else None,
            margin_fraction=0.25,
            method="measured_warmup_upper_margin",
        )

    def view(self, sample, now):
        estimate = self.estimate(sample, now)
        return dict(
            estimate,
            status="ready" if estimate["energy_wh"] is not None else "learning",
            measuring=self.session is not None,
            completed_sessions=sum(0 <= now - r["measured_at"] <= 7 * 86400 for r in self.records),
            execution_authorized=False,
        )
