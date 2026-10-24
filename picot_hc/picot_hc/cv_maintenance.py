"""Passive, disjoint CV holding periods with delayed DHW screening."""

import copy

from .cv_auxiliary import estimate as auxiliary_estimate
from .cv_energy_model import matching
from .cv_gas_screening import advance_screening, screening_result
from .cv_warmup import CvWarmupEvidence
from .energy_model import finite
from .thermal_weather import comparable


class CvMaintenance:
    def __init__(self, store):
        self.evidence = CvWarmupEvidence(store, table="hc_cv_maintenance")
        self.session = None

    def observe(self, sample, view, plan, commands, now):
        own = plan.get("owned", {}).get("cv", {})
        command = next((c for c in commands if c.get("id") == own.get("command")), {})
        cv = plan.get("sources", {}).get("cv", {})
        window = view.get("current")
        if (
            sample is None
            or not window
            or not plan.get("enabled")
            or not view.get("settings", {}).get("enabled")
            or not view["settings"].get("learning_enabled")
            or not sample.get("auxiliary_assumptions")
            or own.get("released")
            or not own
            or command.get("status") != "confirmed"
            or command.get("origin") != "schedule"
            or command.get("source") != "cv"
            or command.get("field") != "heating"
            or cv.get("state") != "heat"
            or cv.get("pending")
            or not finite(cv.get("temperature"))
            or abs(cv["temperature"] - sample["target"]) > 0.05
            or abs(window["target"] - sample["target"]) > 0.05
            or abs(sample["indoor"] - sample["target"]) > 0.3
            or plan.get("desired", {}).get("cv") != sample["target"]
        ):
            self.session = None
            return
        s = self.session
        if s and (
            not 0 < now - s["last"] <= 90
            or now - s["time"] > 2400
            or view["revision"] != s["revision"]
            or own["command"] != s["command"]
            or sample["identity"] != s["sample"]["identity"]
            or not comparable(sample, s["sample"])
            or sample["auxiliary_assumptions"] != s["sample"]["auxiliary_assumptions"]
            or abs(sample["target"] - s["sample"]["target"]) > 0.05
            or abs(sample["outdoor"] - s["sample"]["outdoor"]) > 1.5
            or max(s["high"], sample["indoor"]) - min(s["low"], sample["indoor"]) > 0.3
            or sample["gas_m3"] < s["previous"]["gas_m3"]
            or sample["gas_reported_at"] < s["previous"]["gas_reported_at"]
            or sample["gas_reported_at"] == s["previous"]["gas_reported_at"]
            and sample["gas_m3"] != s["previous"]["gas_m3"]
        ):
            self.session = None
            return
        if s is None:
            if not 0 <= now - sample["gas_reported_at"] <= 60:
                return
            self.session = s = dict(
                sample=copy.deepcopy(sample),
                previous=copy.deepcopy(sample),
                time=now,
                last=now,
                revision=view["revision"],
                command=own["command"],
                low=sample["indoor"],
                high=sample["indoor"],
            )
        advance_screening(s, sample)
        s.update(
            last=now,
            previous=copy.deepcopy(sample),
            low=min(s["low"], sample["indoor"]),
            high=max(s["high"], sample["indoor"]),
        )
        if now - s["time"] < 1200 or sample["gas_reported_at"] < s["time"] + 1200:
            return
        self.session = None
        used = sample["gas_m3"] - s["sample"]["gas_m3"]
        if not finite(used) or not 0 < used <= 20:
            return  # An unreported/zero delta is not proof of free heat.
        screen = screening_result(s)
        screen.update(
            provisional=True,
            delay_margin_seconds=90,
            review_until=now + 90,
            identity=s["sample"].get("gas_screening", {}).get("identity"),
        )
        record = dict(
            kind="maintenance",
            command_id=str(s["command"]) + ":" + str(s["time"]),
            start=s["time"],
            measured_at=now,
            stable_at=s["time"] + 1200,
            duration_seconds=now - s["time"],
            identity=sample["identity"],
            weather=copy.deepcopy(s["sample"].get("weather")),
            indoor=s["sample"]["indoor"],
            outdoor=s["sample"]["outdoor"],
            target=sample["target"],
            gas_start_reported_at=s["sample"]["gas_reported_at"],
            gas_end_reported_at=sample["gas_reported_at"],
            household_gas_delta_m3=used,
            gas_screening=screen,
            electricity=auxiliary_estimate(sample["auxiliary_assumptions"], now - s["time"]),
        )
        records = [r for r in self.evidence.records if 0 <= now - r["measured_at"] <= 7 * 86400]
        self.evidence.save((records + [record])[-96:], [])

    def estimate(self, sample, now):
        records = (
            []
            if sample is None
            else [
                r
                for r in self.evidence.records
                if r.get("kind") == "maintenance" and matching(r, sample, now)
            ]
        )
        records = list({r["command_id"]: r for r in records}.values())
        ready = len(records) >= 3
        return dict(
            status="estimated" if ready else "collecting",
            samples=len(records),
            gas_m3_per_hour=max(
                r["household_gas_delta_m3"] * 3600 / (r["measured_at"] - r["start"])
                for r in records
            )
            * 1.25
            if ready
            else None,
            power_w=sample["auxiliary_assumptions"]["running_power_w"] * 1.25 if ready else None,
            method="screened_cv_maintenance_upper_margin:v1",
            margin_fraction=0.25,
            heating_only_confirmed=False,
            execution_authorized=False,
        )

    def view(self, sample, now):
        return dict(
            self.estimate(sample, now),
            measuring=self.session is not None,
            completed_sessions=len(self.evidence.records),
            pending_gas_reviews=sum(
                bool(r["gas_screening"].get("provisional")) for r in self.evidence.records
            ),
        )
