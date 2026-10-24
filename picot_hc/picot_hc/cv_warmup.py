"""Passive CV warmup evidence; never treat the airco meter as a CV meter."""

import copy
import json
from datetime import datetime

from .core import observation
from .cv_auxiliary import assumptions, estimate
from .cv_electricity import advance, cv_electricity, result
from .cv_energy_model import estimate as energy_estimate
from .cv_gas_screening import advance_screening, gas_screening, screening_result
from .energy_model import finite
from .thermal_weather import comparable


def cv_sample(config, control, plan, now, *, target=None):
    thermal = plan.get("learning_context") or {}
    sources = plan.get("sources") or {}
    cv, ac = sources.get("cv", {}), sources.get("beneden", {})
    if target is None:
        target = plan.get("desired", {}).get("cv", cv.get("temperature"))
    if (
        not control.connected
        or control.received is None
        or not 0 <= now - control.received <= config["stale_seconds"]
        or not thermal.get("valid")
        or not cv.get("available")
        or not ac.get("available")
        or ac.get("state") != "off"
        or ac.get("pending")
        or not all(finite(v) for v in (thermal.get("indoor"), thermal.get("outdoor"), target))
    ):
        return None
    gas = observation(config.get("gas"), control.states, now, True, "m³")
    try:
        reported = datetime.fromisoformat(
            (gas["source_reported"] or gas["source_updated"]).replace("Z", "+00:00")
        )
        if (
            gas["quality"] != "available"
            or gas.get("report_error")
            or gas["value"] < 0
            or reported.utcoffset() is None
            or not 0 <= now - reported.timestamp() <= 600
        ):
            return None
    except (ValueError, TypeError, AttributeError):
        return None
    down = next(z for z in config["zones"] if z["id"] == "beneden")
    identity = json.dumps([config["cv"], config["gas"], down["temperature"], config["outdoor"]])
    return dict(
        indoor=thermal["indoor"],
        outdoor=thermal["outdoor"],
        target=target,
        gas_m3=gas["value"],
        gas_reported_at=reported.timestamp(),
        identity=identity,
        weather=copy.deepcopy(thermal.get("weather")),
        electricity=cv_electricity(config, control.states, now),
        auxiliary_assumptions=assumptions(config),
        gas_screening=gas_screening(config, control.states, now),
    )


class CvWarmupEvidence:
    def __init__(self, store, *, table="hc_cv_warmup"):
        if table not in ("hc_cv_warmup", "hc_cv_maintenance"):
            raise ValueError("invalid CV evidence table")
        self.table = table
        self.store = store
        self.baseline = self.session = None
        with store.connect() as db:
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} "
                "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            row = db.execute(f"SELECT payload FROM {self.table} WHERE id=1").fetchone()
        data = json.loads(row[0]) if row else dict(records=[], attempted=[])
        self.records, self.attempted = data["records"], data["attempted"]
        self.screening_last = None

    def save(self, records, attempted):
        with self.store.connect() as db:
            db.execute(
                f"INSERT OR REPLACE INTO {self.table} VALUES (1, ?)",
                (json.dumps(dict(records=records, attempted=attempted), allow_nan=False),),
            )
        self.records, self.attempted = records, attempted

    def screen(self, point, now):
        # Independent of heat demand: a late DHW report still affects a finished run.
        records = copy.deepcopy(self.records)
        changed = False
        for record in records:
            screening = record.get("gas_screening", {})
            if not screening.get("provisional"):
                continue
            changed = True
            end = record["measured_at"]
            complete = screening["polling_complete"]
            if (
                self.screening_last is None
                or not 0 <= now - self.screening_last <= 60
                or point.get("status") != "available"
                or point.get("identity") != screening.get("identity")
            ):
                complete = False
            if (
                0 <= now - end <= 90
                and point.get("status") == "available"
                and point.get("active") is True
            ):
                screening["status"] = "dhw_observed"
            if not complete and screening["status"] != "dhw_observed":
                screening["status"] = "incomplete"
            screening["polling_complete"] = complete
            if now >= end + 90:
                screening["provisional"] = False
                screening["checked_at"] = now
        if changed:
            self.save(records, self.attempted)
        self.screening_last = now

    def reset(self):
        self.baseline = self.session = None

    def prepare(self, sample, view, plan, action, now):
        self.baseline = None
        if self.session is not None:
            return
        window = view.get("next")
        if (
            sample is None
            or not plan.get("enabled")
            or not plan.get("preheating")
            or not view["settings"].get("enabled")
            or not view["settings"].get("learning_enabled")
            or not window
            or abs(window["target"] - sample["target"]) > 0.05
            or sample["target"] - sample["indoor"] < 0.5
            or plan["sources"]["cv"]["state"] != "off"
            or action != ("cv", "heating", sample["target"])
        ):
            return
        self.baseline = dict(sample=copy.deepcopy(sample), revision=view["revision"], time=now)

    def observe(self, sample, view, plan, commands, now):
        if sample is not None:
            self.screen(sample.get("gas_screening", {}), now)
        own = plan.get("owned", {}).get("cv", {})
        command = next((c for c in commands if c["id"] == own.get("command")), None)
        cv = plan.get("sources", {}).get("cv", {})
        if (
            sample is None
            or not plan.get("enabled")
            or not view["settings"].get("enabled")
            or not view["settings"].get("learning_enabled")
            or own.get("released")
            or not command
            or command.get("origin") != "schedule"
            or command.get("source") != "cv"
            or command.get("field") != "heating"
            or command.get("before", {}).get("mode") != "off"
            or command.get("status") not in ("awaiting_feedback", "confirmed")
            or not finite(command.get("value"))
            or abs(command["value"] - sample["target"]) > 0.05
            or cv.get("state") not in ("off", "heat")
            or plan.get("desired", {}).get("cv") != sample["target"]
        ):
            self.reset()
            return
        if self.session is None:
            baseline = self.baseline
            self.baseline = None
            if (
                not baseline
                or command["id"] in self.attempted
                or not finite(command.get("sent"))
                or not finite(command.get("created"))
                or not baseline["time"] <= command["created"] <= command["sent"] <= now
                or now - baseline["time"] > 90
                or view["revision"] != baseline["revision"]
            ):
                return
            self.save(self.records, (self.attempted + [command["id"]])[-96:])
            self.session = dict(
                baseline,
                command_id=command["id"],
                last=baseline["time"],
                previous=baseline["sample"],
                high=baseline["sample"]["indoor"],
                reached=None,
                confirmed_at=None,
                electricity_valid=True,
                auxiliary_valid=True,
            )
        s = self.session
        if (
            command["id"] != s["command_id"]
            or view["revision"] != s["revision"]
            or not 0 <= now - s["last"] <= 90
            or now - s["time"] > 10800
            or sample["identity"] != s["sample"]["identity"]
            or not comparable(sample, s["sample"])
            or abs(sample["target"] - s["sample"]["target"]) > 0.05
            or sample["gas_m3"] < s["previous"]["gas_m3"]
            or sample["gas_reported_at"] < s["previous"]["gas_reported_at"]
            or sample["gas_reported_at"] == s["previous"]["gas_reported_at"]
            and sample["gas_m3"] != s["previous"]["gas_m3"]
            or abs(sample["outdoor"] - s["sample"]["outdoor"]) > 1.5
            or sample["indoor"] < s["high"] - 0.3
        ):
            self.reset()
            return
        confirmed = (
            command["status"] == "confirmed"
            and cv["state"] == "heat"
            and finite(cv.get("temperature"))
            and abs(cv["temperature"] - sample["target"]) < 0.05
        )
        if s["confirmed_at"] is not None and not confirmed:
            self.reset()
            return
        if confirmed and s["confirmed_at"] is None:
            s["confirmed_at"] = now
        if sample.get("auxiliary_assumptions") != s["sample"].get("auxiliary_assumptions"):
            s["auxiliary_valid"] = False
        advance(s, sample)
        advance_screening(s, sample)
        s.update(last=now, previous=copy.deepcopy(sample), high=max(s["high"], sample["indoor"]))
        if confirmed and sample["indoor"] >= sample["target"]:
            if s["reached"] is None:
                s["reached"] = now
        else:
            s["reached"] = None
        if s["reached"] is None or now - s["reached"] < 120:
            return
        # Wait for a counter report covering the stability period. Do not infer
        # unreported gas as zero; keep its distinct observation interval explicit.
        if sample["gas_reported_at"] < s["reached"] + 120:
            return
        duration = s["reached"] - s["time"]
        used = sample["gas_m3"] - s["sample"]["gas_m3"]
        self.reset()
        if duration < 300 or not 0 < used <= 20:
            return
        electricity = result(s, sample)
        if electricity["status"] != "measured" and s["auxiliary_valid"]:
            estimated = estimate(s["sample"].get("auxiliary_assumptions"), now - s["time"])
            if estimated["status"] == "estimated":
                electricity = estimated
        record = dict(
            command_id=s["command_id"],
            measured_at=now,
            start=s["time"],
            indoor=s["sample"]["indoor"],
            outdoor=s["sample"]["outdoor"],
            target=sample["target"],
            identity=sample["identity"],
            weather=copy.deepcopy(s["sample"].get("weather")),
            duration_seconds=duration,
            stable_at=s["reached"] + 120,
            confirmation_delay_seconds=s["confirmed_at"] - s["time"],
            household_gas_delta_m3=used,
            gas_start_reported_at=s["sample"]["gas_reported_at"],
            gas_end_reported_at=sample["gas_reported_at"],
            gas_attribution="household_total_may_include_other_use",
            gas_screening=screening_result(s),
            electricity_measured=electricity["status"] == "measured",
            electricity=electricity,
            comparison_eligible=False,
        )
        record["gas_screening"].update(
            provisional=True,
            delay_margin_seconds=90,
            review_until=now + 90,
            identity=s["sample"].get("gas_screening", {}).get("identity"),
        )
        recent = [r for r in self.records if 0 <= now - r["measured_at"] <= 30 * 86400]
        self.save((recent + [record])[-96:], self.attempted)

    def view(self, now, sample=None, *, gas_price=None):
        records = [r for r in self.records if 0 <= now - r["measured_at"] <= 30 * 86400]
        prediction = energy_estimate(records, sample, now, gas_price=gas_price)
        return dict(
            status="observations_available" if records else "collecting",
            measuring=self.session is not None,
            completed_sessions=len(records),
            pending_gas_reviews=sum(
                bool(r.get("gas_screening", {}).get("provisional")) for r in records
            ),
            latest=copy.deepcopy(records[-1]) if records else None,
            energy_estimate=prediction,
            comparison_eligible=False,
            execution_authorized=False,
            reason=prediction["reason"],
        )
