"""Persist a downstairs start preference, never an execution permission."""

import copy
import json

from .energy_model import EnergyModel, finite


class StartIntent:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS hc_start_intent "
                "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            row = db.execute("SELECT payload FROM hc_start_intent WHERE id=1").fetchone()
        self.current = json.loads(row[0]) if row else None
        self.cancel("Herstart; startvoornemen wordt niet automatisch hervat.")

    def save(self):
        with self.store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO hc_start_intent VALUES (1, ?)",
                (json.dumps(self.current, allow_nan=False),),
            )

    def cancel(self, reason):
        if self.current and self.current["status"] != "cancelled":
            self.current = dict(self.current, status="cancelled", reason=reason)
            self.save()

    def check(self, sample, view, plan, now):
        if self.current and self.current["status"] == "started":
            return None
        if not self.valid(sample, view, plan, now):
            self.cancel("Startvoornemen vervallen: omstandigheden gewijzigd of starttijd bereikt.")
            return None
        return self.current["heat_starts_at"]

    def valid(self, sample, view, plan, now, *, starting=False):
        current = self.current
        if not current or current["status"] != "planned":
            return False
        window = view.get("next")
        sources = plan.get("sources", {})
        rate = plan.get("learning_status", {}).get("cooling_rate")
        floor = plan.get("zones", {}).get("beneden", {}).get("target")
        forecast_plan = current.get("recipe", {}).get("hourly_forecast_used") is True
        a, b = sample, current["sample"]
        if forecast_plan and sample is not None:
            # Forecast-aware execution rechecks actual + future empirical bounds before
            # dispatch. Expected weather changes are not a sensor-identity change.
            a, b = dict(sample, weather=None), dict(b, weather=None)
        return not (
            sample is None
            or not plan.get("enabled")
            or not view.get("settings", {}).get("enabled")
            or not view.get("settings", {}).get("learning_enabled")
            or view.get("revision") != current["schedule_revision"]
            or plan.get("revision") != current["heating_revision"]
            or window != current["window"]
            or view.get("current")
            or plan.get("preheating")
            or any(s in plan.get("desired", {}) for s in ("beneden", "cv"))
            or any(
                sources.get(s, {}).get("state") != "off"
                or not sources[s].get("available")
                or sources[s].get("pending")
                for s in ("beneden", "cv")
            )
            or not current["created_at"]
            <= now
            < current["heat_starts_at"] + (30 if starting else 0)
            or not EnergyModel.same(a, b)
            or forecast_plan
            and plan.get("hourly_weather", {}).get("status") != "ready"
            or not forecast_plan
            and abs(sample["outdoor"] - current["sample"]["outdoor"]) > 1.5
            or not finite(rate)
            or rate < 0
            or not finite(floor)
            or not finite(sample["indoor"])
            or sample["indoor"] - rate * max(0, current["heat_starts_at"] - now) / 3600 < floor
        )

    def started(self, command_id):
        if self.current and self.current["status"] == "planned":
            self.current = dict(
                self.current,
                status="started",
                command_id=command_id,
                reason="Startopdracht vastgelegd; temperatuur handhaven.",
            )
            self.save()

    def capture(self, selection, proposals, sample, view, plan, now):
        chosen, local = selection.current, proposals.local
        if (
            not chosen
            or not local
            or local.get("action") != "scheduled_start"
            or not proposals.pending
            or sample is None
            or local.get("schedule_revision") != view["revision"]
            or chosen["request_id"] != proposals.pending["request_id"]
            or now >= chosen["valid_until"]
            or chosen.get("execution_authorized") is not False
        ):
            return
        recipe, window = chosen["recipe"], view.get("next")
        if not window or recipe.get("heat_starts_at", 0) <= now:
            return
        old = self.current
        if (
            old
            and old["schedule_revision"] != view["revision"]
            and old["request_id"] == chosen["request_id"]
        ):
            return
        if (
            old
            and old["window"]["starts_at"] == window["starts_at"]
            and old["schedule_revision"] == view["revision"]
        ):
            # Never slide or silently recreate a cancelled start for the same comfort window.
            if (
                self.check(sample, view, plan, now) != recipe["heat_starts_at"]
                or recipe["target"] != old["target"]
                or recipe.get("source", "beneden") != old.get("source", "beneden")
            ):
                return
            if old["request_id"] == chosen["request_id"]:
                return
            self.current = dict(
                old,
                request_id=chosen["request_id"],
                assessment_valid_until=chosen["valid_until"],
                selection=copy.deepcopy(chosen.get("message")),
                recipe=copy.deepcopy(recipe),
            )
        else:
            self.current = dict(
                status="planned",
                source=recipe.get("source", "beneden"),
                reason="Vaste starttijd; starten vereist actuele HEMS-starttoestemming.",
                window=copy.deepcopy(window),
                schedule_revision=view["revision"],
                heating_revision=plan.get("revision"),
                sample=copy.deepcopy(sample),
                target=recipe["target"],
                heat_starts_at=recipe["heat_starts_at"],
                created_at=now,
                request_id=chosen["request_id"],
                assessment_valid_until=chosen["valid_until"],
                execution_authorized=False,
                selection=copy.deepcopy(chosen.get("message")),
                recipe=copy.deepcopy(recipe),
            )
            self.check(sample, view, plan, now)
        self.save()

    def view(self, now):
        if not self.current:
            return dict(status="waiting", execution_authorized=False)
        result = {
            k: copy.deepcopy(v)
            for k, v in self.current.items()
            if k
            not in (
                "sample",
                "window",
                "schedule_revision",
                "heating_revision",
                "selection",
                "recipe",
            )
        }
        if result["status"] not in ("cancelled", "started"):
            if now >= result["heat_starts_at"] or now < result["created_at"]:
                result.update(status="cancelled", reason="Starttijd niet meer geldig.")
            elif now >= result["assessment_valid_until"]:
                result.update(
                    status="needs_assessment", reason="Vaste starttijd wacht op nieuw HEMS-advies."
                )
        return result
