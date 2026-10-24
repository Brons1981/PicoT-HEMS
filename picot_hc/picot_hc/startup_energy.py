"""Measure an HC off-to-heat command from a pre-command meter baseline."""

import copy

from .energy_model import EnergyModel, finite
from .warmup_energy import WarmupEnergy


class StartupEnergy:
    def __init__(self, store):
        self.model = WarmupEnergy(store, cold_start=True)
        self.baseline = self.active = None

    def reset(self):
        self.baseline = self.active = self.model.session = None

    def prepare(self, sample, view, plan, action, now):
        self.baseline = None
        if self.active is not None:
            return
        source = plan.get("sources", {}).get("beneden", {})
        if (
            sample is None
            or not plan.get("enabled")
            or not plan.get("preheating")
            or not view["settings"].get("enabled")
            or not view["settings"].get("learning_enabled")
            or not view.get("next")
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
        return result
