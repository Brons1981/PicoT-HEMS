"""Measure an HC off-to-heat command from a pre-command meter baseline."""

import copy
import time

from .energy_model import EnergyModel, finite
from .warmup_energy import WarmupEnergy

ISSUES = {
    "startup_baseline_measurement_unavailable": "Geen bruikbare beginmeting vóór de start; controleer de actuele temperatuur-, vermogen- en kWh-metingen en de bronstatus.",
    "startup_baseline_missing": "Geen beginmeting vóór de start vastgelegd; deze start kan niet als volledige start worden geleerd.",
    "startup_baseline_invalid": "Beginmeting past niet meer bij de start: tijdstip, comfortinstelling of meetomstandigheden zijn gewijzigd.",
    "startup_command_or_measurement_context_lost": "Startmeting afgebroken: opdrachtbevestiging of bruikbare meetgegevens ontbreken.",
}


class StartupEnergy:
    def __init__(self, store):
        self.model = WarmupEnergy(store, cold_start=True)
        self.baseline = self.active = None
        self.observed_command = None

    def reset(self):
        if self.model.session is not None:
            self.model.note("rejected", "startup_command_or_measurement_context_lost", time.time())
        self.baseline = self.active = self.model.session = None

    def prepare(self, sample, view, plan, action, now):
        self.baseline = None
        if self.active is not None:
            return
        source = plan.get("sources", {}).get("beneden", {})
        if (sample is None and plan.get("enabled")
                and view["settings"].get("enabled")
                and view["settings"].get("learning_enabled")
                and source.get("state") == "off" and action
                and action[:2] == ("beneden", "heating")
                and plan.get("learning_status", {}).get("phase") in ("preheat", "comfort")):
            self.model.note("waiting", "startup_baseline_measurement_unavailable", now)
        if (
            sample is None
            or not plan.get("enabled")
            or plan.get("learning_status", {}).get("phase") not in ("preheat", "comfort")
            or not view["settings"].get("enabled")
            or not view["settings"].get("learning_enabled")
            or not (view.get("next") if plan.get("preheating") else view.get("current"))
            or source.get("state") != "off"
            or source.get("pending")
            or action != ("beneden", "heating", sample["target"])
        ):
            return
        self.baseline = dict(
            sample=copy.deepcopy(sample),
            view=copy.deepcopy(view),
            plan=copy.deepcopy(plan),
            time=now,
        )

    def observe(self, sample, view, plan, commands, now):
        own = plan.get("owned", {}).get("beneden", {})
        command = next((c for c in commands if c["id"] == own.get("command")), None)
        source = plan.get("sources", {}).get("beneden", {})
        if (
            sample is None
            or not command
            or own.get("released")
            or command.get("origin") != "schedule"
            or command.get("source") != "beneden"
            or command.get("field") != "heating"
            or command.get("before", {}).get("mode") != "off"
            or command.get("status") not in ("awaiting_feedback", "confirmed")
            or not finite(command.get("value"))
            or abs(command["value"] - sample["target"]) > 0.05
            or source.get("state") not in ("off", "heat")
        ):
            self.reset()
            return
        confirmed = (
            command["status"] == "confirmed"
            and source["state"] == "heat"
            and not source.get("pending")
            and finite(source.get("temperature"))
            and abs(source["temperature"] - sample["target"]) < 0.05
        )
        if self.active is None:
            if ((self.observed_command == command['id'] and self.baseline is None) or
                    any(r.get('command_id') == command['id'] for r in self.model.records)):
                return
            self.observed_command = command['id']
            b = self.baseline
            self.baseline = None
            if (
                not b
                or not finite(command.get("sent"))
                or not finite(command.get("created"))
                or not b["time"] <= command["created"] <= command["sent"] <= now
                or now - b["time"] > 90
                or view["revision"] != b["view"]["revision"]
                or not EnergyModel.same(sample, b["sample"])
            ):
                # Keep the earlier, more specific missing-measurement explanation.
                if b or not self.model.events or self.model.events[-1]["reason"] != "startup_baseline_measurement_unavailable":
                    self.model.note("waiting", "startup_baseline_invalid" if b else "startup_baseline_missing", now)
                return
            initial = dict(b["sample"], confirmed_heat=False, command_id=command["id"])
            self.model.observe(initial, b["view"], b["plan"], b["time"])
            if self.model.session is None:
                return
            self.active = command["id"]
        if self.active != command["id"] or (
            self.model.session["confirmed_at"] is not None and not confirmed
        ):
            self.reset()
            return
        if now > self.model.session["last"]:
            self.model.observe(dict(sample, confirmed_heat=confirmed), view, plan, now)
        elif now < self.model.session["last"]:
            self.reset()
        if self.model.session is None:
            self.active = None

    def view(self, sample, now):
        result = self.model.view(sample, now)
        result["method"] = "measured_full_start_upper_margin"
        result["awaiting_confirmation"] = bool(
            self.model.session and self.model.session["confirmed_at"] is None
        )
        last = self.model.events[-1] if self.model.events else {}
        result["last_issue"] = ISSUES.get(last.get("reason"))
        return result
