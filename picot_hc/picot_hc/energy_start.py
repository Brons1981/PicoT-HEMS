"""Execute a permitted downstairs start through the existing guarded controller."""

import copy
import math
from datetime import datetime
from types import SimpleNamespace

from .energy_measurement import measurement
from .energy_model import finite, meter_context
from .energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY, read_assessment
from .hourly_weather import planning_models, upper

PERMIT_ENTITY = "sensor.picot_hems_hc_start_permit"


def permitted(states, intent, now):
    message = intent.get("selection")
    entity = states.get(PERMIT_ENTITY, {})
    if not message or entity.get("state") != "permitted":
        return False
    expected = dict(message, contract="hc-energy-start-permit:v1", execution_authorized=True)
    if (
        entity.get("attributes") != expected
        or entity["attributes"].get("execution_authorized") is not True
    ):
        return False
    try:
        generated = datetime.fromisoformat(message["generated_at"])
        expires = datetime.fromisoformat(message["valid_until"])
        if (
            generated.utcoffset() is None
            or expires.utcoffset() is None
            or not generated.timestamp() <= now < expires.timestamp() <= generated.timestamp() + 120
        ):
            return False
    except (TypeError, ValueError, KeyError):
        return False
    answer = read_assessment(states, now)
    return (
        answer["status"] == "selected"
        and states[RESPONSE_ENTITY]["attributes"]["request_fingerprint"]
        == message["request_fingerprint"]
        and answer["selected_plan_id"] == message["selected_plan_id"]
        and states[REQUEST_ENTITY]["attributes"]["request_id"] == intent["request_id"]
    )


class EnergyStart:
    def __init__(self, heating, intent, startup, steady):
        self.heating, self.intent, self.startup, self.steady = heating, intent, startup, steady
        self.cv_warmup = self.cv_maintenance = None

    def idle_preheat(self, plan, view, direct_desired):
        """Remove only future-window preheat, retaining the actual setback floor."""
        if plan["learning_status"]["phase"] != "preheat" or view.get("current"):
            return None
        request = view["comfort"]["zones"]["beneden"]["request"] or {}
        floor = request.get("target")
        if not finite(floor):
            return None
        if view["settings"].get("adaptive_setback_enabled"):
            depth = plan["learning_status"]["setback_depth"]
            if not finite(plan["learning_status"]["cooling_rate"]):
                depth = min(1, depth)
            floor = max(
                floor, view["settings"]["setback_temperature"], view["next"]["target"] - depth
            )
        result = copy.deepcopy(plan)
        result["desired"].pop("beneden", None)
        result["desired"].pop("cv", None)
        if "boven" in direct_desired:
            result["desired"]["boven"] = direct_desired["boven"]
        result["zones"]["beneden"].update(
            target=floor, demand=False, reason="Wachten op gekozen HEMS-start; ondergrens bewaakt."
        )
        result["demand"]["beneden"] = False
        result["preheating"] = False
        result["strategy"] = "hems_waiting_start"
        result["learning_status"].update(phase="hems_waiting_start", preheating=False, target=floor)
        return result

    def apply(self, plan, config, now, direct_desired):
        """Pure decision: ownership and one-shot dispatch are persisted by Heating.guard."""
        heat = self.heating
        view = heat.schedule.view(now)
        chosen_source = (self.intent.current or {}).get("source", "beneden")
        if chosen_source not in ("beneden", "cv"):
            return plan
        other_source = "cv" if chosen_source == "beneden" else "beneden"
        own = heat.data["owned"].get(chosen_source, {})
        active = own.get("energy_start")
        current = active or self.intent.current
        if not current:
            return plan
        target, window = current["target"], current["window"]
        source = plan["sources"][chosen_source]
        full_window = (
            current.get("full_comfort_window", False)
            if active
            else (
                current.get("recipe", {}).get("slots", [{}])[-1].get("ends_at", 0)
                >= window["ends_at"]
            )
        )
        if (
            not plan["enabled"]
            or not view["settings"]["enabled"]
            or not view["settings"].get("energy_start_enabled")
            or not view["settings"].get("learning_enabled")
            or not plan["learning_context"]["valid"]
            or plan["price"] is None
            or view["revision"] != current["schedule_revision"]
            or heat.data["revision"] != current["heating_revision"]
            or not (
                view.get("next") == window
                or active
                and full_window
                and view.get("current") == window
            )
            or now >= window["ends_at" if active and full_window else "starts_at"]
            or any(s in heat.data["faults"] for s in ("beneden", "cv"))
            or not source["available"]
            or not source["temperature_supported"]
            or "heat" not in source["modes"]
            or "off" not in source["modes"]
            or not source["minimum"] <= target <= source["maximum"]
            or not math.isclose(
                (target - source["minimum"]) / source["step"],
                round((target - source["minimum"]) / source["step"]),
                abs_tol=1e-5,
            )
            or plan["sources"][other_source]["state"] != "off"
            or plan["sources"][other_source]["pending"]
        ):
            return plan
        if active:
            # A permit only gates initiation. Expiry must never stop an incumbent.
            if own.get("released"):
                return plan
        else:
            if (
                heat.data["owned"].get("beneden")
                or heat.data["owned"].get("cv")
                or now >= current["heat_starts_at"] + 30
                or now < current["heat_starts_at"]
                and not plan["preheating"]
                or not permitted(heat.control.states, current, now)
            ):
                return plan
            sample = meter_context(
                config,
                heat.control.states,
                plan,
                measurement(config, heat.control.states, now),
                now,
                target=target,
            )
            checked = (
                self.idle_preheat(plan, view, direct_desired)
                if plan["preheating"]
                else copy.deepcopy(plan)
            )
            if checked is None:
                return plan
            checked["revision"] = heat.data["revision"]
            if not self.intent.valid(
                sample, view, checked, now, starting=now >= current["heat_starts_at"]
            ):
                return plan
            recipe = current["recipe"]
            if recipe.get("hourly_forecast_used") and (
                plan.get("hourly_weather", {}).get("status") != "ready"
            ):
                return plan
            bounded = planning_models(
                plan,
                [self.startup.model, self.steady],
                sample,
                now,
                now,
                window["ends_at"],
                heat.learning.cooling,
            )
            if bounded is None:
                return plan
            (startup_model, steady_model), future_rate = bounded
            waiting = now < current["heat_starts_at"]
            projected = dict(sample)
            if waiting:
                projected["indoor"] -= (
                    max(checked["learning_status"]["cooling_rate"], future_rate or 0)
                    * (current["heat_starts_at"] - now)
                    / 3600
                )
            if projected["indoor"] < checked["zones"]["beneden"]["target"]:
                return plan
            estimate = upper(
                [
                    startup_model.estimate(projected, now),
                    self.startup.model.estimate(projected, now),
                ]
            )
            holding = upper(
                [
                    steady_model.estimate(dict(sample, indoor=target), now),
                    self.steady.estimate(dict(sample, indoor=target), now),
                ]
            )
            recipe = current["recipe"]
            if chosen_source == "cv":
                from .cv_energy_model import estimate as cv_estimate
                from .cv_warmup import cv_sample

                if not finite(plan.get("costs", {}).get("cv")):
                    return plan

                query = cv_sample(config, heat.control, plan, now, target=target)
                if query is None or self.cv_warmup is None or self.cv_maintenance is None:
                    return plan
                if (
                    query.get("gas_screening", {}).get("status") != "available"
                    or query["gas_screening"].get("active") is not False
                ):
                    return plan
                query.update(indoor=projected["indoor"], outdoor=projected["outdoor"])
                models = planning_models(
                    plan,
                    [
                        SimpleNamespace(
                            estimate=lambda point, moment: cv_estimate(
                                self.cv_warmup.records, point, moment
                            )
                        ),
                        self.cv_maintenance,
                    ],
                    query,
                    now,
                    now,
                    window["ends_at"],
                )
                if models is None:
                    return plan
                (cv_model, cv_holding), _ = models
                cv = upper(
                    [cv_model.estimate(query, now), cv_estimate(self.cv_warmup.records, query, now)]
                )
                holding = upper(
                    [
                        cv_holding.estimate(dict(query, indoor=target), now),
                        self.cv_maintenance.estimate(dict(query, indoor=target), now),
                    ]
                )
                if (
                    cv["electricity"] is None
                    or holding["power_w"] is None
                    or config.get("gas_price") != recipe.get("gas_price")
                    or cv["gas_m3"] > recipe["startup_gas_m3"] + 1e-6
                    or holding["gas_m3_per_hour"] > recipe["maintenance"]["gas_m3_per_hour"] + 1e-6
                ):
                    return plan
                estimate = dict(
                    cv,
                    energy_wh=cv["electricity"]["energy_wh"]
                    + recipe["standby_w"] * cv["duration_seconds"] / 3600,
                )
                holding = dict(holding, power_w=holding["power_w"] + recipe["standby_w"])
            if (
                not finite(estimate["energy_wh"])
                or not finite(estimate["duration_seconds"])
                or not finite(holding["power_w"])
                or estimate["energy_wh"] > recipe["startup_energy_wh"] + 1e-6
                or estimate["duration_seconds"] > recipe["startup_duration_seconds"]
                or max(now, current["heat_starts_at"])
                + estimate["duration_seconds"]
                + (max(30, config.get("poll_seconds", 30)) if plan["preheating"] else 0)
                > window["starts_at"]
                or waiting
                and current["heat_starts_at"] < heat.data["changed"].get(chosen_source, -1e20) + 180
                or holding["power_w"] > recipe["maintenance"]["power_w"] + 1e-6
            ):
                return plan
            if waiting:
                return checked
        # Use the existing action, minimum-off time, fresh-read guard and command feedback.
        result = copy.deepcopy(plan)
        if "cv" in result["desired"] and "boven" in direct_desired:
            result["desired"]["boven"] = direct_desired["boven"]
        result["desired"].pop(other_source, None)
        if active and full_window and plan["learning_status"].get("phase") == "coast":
            target = min(target, plan["zones"]["beneden"]["target"])
        result["desired"][chosen_source] = target
        result["zones"]["beneden"].update(
            target=target,
            demand=True,
            reason="HEMS-start uitvoeren." if not active else "HEMS-start: temperatuur handhaven.",
        )
        result["demand"]["beneden"] = True
        in_comfort = active and full_window and now >= window["starts_at"]
        result["preheating"] = not in_comfort
        result["strategy"] = "hems_permitted_start"
        phase = (
            ("coast" if plan["learning_status"].get("phase") == "coast" else "comfort")
            if in_comfort
            else "preheat"
        )
        result["learning_status"].update(phase=phase, preheating=not in_comfort, target=target)
        result["energy_start"] = {
            k: copy.deepcopy(current[k])
            for k in (
                "created_at",
                "request_id",
                "heat_starts_at",
                "target",
                "window",
                "schedule_revision",
                "heating_revision",
            )
        }
        result["energy_start"].update(source=chosen_source, full_comfort_window=full_window)
        return result
