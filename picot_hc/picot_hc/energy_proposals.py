"""Automatic advice for measured downstairs warmup and steady heating."""

import copy
import json
from datetime import UTC, datetime
from threading import Lock, Thread
from uuid import uuid4

from .control import ha_request
from .cv_plans import candidates as cv_candidates
from .cv_plans import tail_allowance
from .delayed_start import StandbyEvidence
from .delayed_start import candidates as delayed_candidates
from .energy_model import EnergyModel
from .energy_portfolio import REQUEST_ENTITY
from .hourly_weather import planning_models
from .proposal_feedback import ProposalFeedback
from .warmup_plans import candidates


def stamp(now):
    return datetime.fromtimestamp(now, UTC).isoformat()


class ProposalPublisher:
    """One worker, one latest value; withdrawal supersedes queued proposals."""

    def __init__(self, url, token, entity=REQUEST_ENTITY):
        self.url, self.token = url, token
        self.entity = entity
        self.lock = Lock()
        self.running, self.latest, self.delivered = False, None, None

    def submit(self, value):
        with self.lock:
            self.latest = copy.deepcopy(value)
            if self.running or self.latest == self.delivered:
                return
            self.running = True

        def work():
            while True:
                with self.lock:
                    current = self.latest
                try:
                    ha_request(self.url, self.token, "/states/" + self.entity, current)
                    success = True
                except Exception:
                    success = False
                with self.lock:
                    if success:
                        self.delivered = current
                    if self.latest == current:
                        self.running = False
                        return

        try:
            Thread(target=work, name="hc-energy-proposals", daemon=True).start()
        except Exception:
            with self.lock:
                self.running = False


class Proposals:
    def __init__(self, store, publisher):
        self.store, self.publisher = store, publisher
        self.model = EnergyModel(store)
        self.standby = StandbyEvidence()
        self.pending, self.local, self.attempted = None, None, []
        self.fixed_start = None
        self.fixed_source = None
        self.cv_context = None
        self.cooling = None
        self.weather_basis = None
        self.feedback = ProposalFeedback()
        self.status = dict(
            status="waiting", reason="Nog geen verbruiksmetingen voor een voorstel.", samples=0
        )
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS hc_energy_proposals "
                "(id TEXT PRIMARY KEY, time REAL, payload TEXT NOT NULL)"
            )

    def withdraw(self, reason, samples=0):
        self.pending = self.local = None
        self.status = dict(status="waiting", reason=reason, samples=samples)
        self.publisher.submit(dict(state="withdrawn", attributes=dict(reason=reason)))

    def tick(
        self,
        sample,
        view,
        plan,
        outlook,
        now,
        *,
        warmup=None,
        warmup_sample=None,
        startup=None,
        idle_sample=None,
        states=None,
        cv_context=None,
    ):
        weather_basis = json.dumps(plan.get("hourly_weather"), sort_keys=True)
        if weather_basis != self.weather_basis:
            self.pending = self.local = None
            self.attempted = []
            self.weather_basis = weather_basis
        self.cv_context = cv_context
        if cv_context is not None:
            cv_context["joint_basis"] = False
        modeled_id = (outlook.get("replacement_basis") or {}).get("modeled_source_id")
        if modeled_id:
            if not cv_context or cv_context.get("modeled_source_id") != modeled_id:
                self.withdraw("Gezamenlijke verbruiksbasis wacht op actuele CV-aannames.")
                return
            cv_context["joint_basis"] = True
            if cv_context.get("unsettled_space_load"):
                self.withdraw("CV-bedrijf nog actief; wachten op een afgebakende startbasis.")
                return
        self.model.observe(sample, now)
        self.standby.observe(idle_sample, now)
        changed = self.feedback.receive(states or {}, self.pending, outlook, now)
        if changed:
            self.pending = self.local = None
            if not self.feedback.blocked:
                self.attempted = [k for k in self.attempted if k != self.feedback.basis]
        if self.feedback.blocked or (
            self.feedback.until is not None and now >= self.feedback.until
        ):
            self.withdraw(self.feedback.reason or "Wachten op een nieuwe HEMS-basis.")
            return
        estimate = self.model.estimate(sample, now)
        window = view.get("current")
        if (
            not plan.get("enabled")
            or not view["settings"]["enabled"]
            or not view["settings"].get("learning_enabled")
        ):
            self.withdraw(
                "Automatische voorstellen vereisen een actief comfortschema en ingeschakeld leren."
            )
            return
        if idle_sample is not None and startup is not None:
            self.delayed_tick(idle_sample, view, plan, outlook, now, startup)
            return
        if plan.get("preheating") and warmup is not None:
            self.warmup_tick(warmup_sample, view, plan, outlook, now, warmup)
            return
        if (
            sample is None
            or not window
            or plan.get("preheating")
            or plan.get("learning_status", {}).get("phase") != "comfort"
            or abs(sample["target"] - window["target"]) > 0.05
            or not window["minimum"] <= sample["indoor"] <= window["maximum"]
        ):
            self.withdraw("Wachten op stabiel temperatuur handhaven met alleen de airco beneden.")
            return
        if estimate["power_w"] is None:
            self.withdraw(
                "Minimaal drie passende meetperioden van twintig minuten nodig.",
                estimate["samples"],
            )
            return
        # A pending proposal keeps its original validity and cannot outlive its conditions.
        if self.pending and self.local:
            valid = (
                self.local.get("action") == "maintain_temperature"
                and now < self.local["expires"]
                and view["revision"] == self.local["schedule_revision"]
                and self.model.same(sample, self.local["sample"])
                and abs(sample["outdoor"] - self.local["sample"]["outdoor"]) <= 1.5
                and abs(sample["indoor"] - self.local["sample"]["indoor"]) <= 0.3
            )
            if valid and outlook.get("status") == "ready":
                self.publisher.submit(dict(state="requested", attributes=self.pending))
                return
            self.pending = self.local = None
        basis = outlook.get("replacement_basis") or {}
        if (
            outlook.get("status") != "ready"
            or basis.get("source_id") != sample["source_id"]
            or outlook.get("valid_until", 0) <= now
        ):
            self.withdraw(
                "HEMS heeft nog geen actuele, passende vervangingsbasis.", estimate["samples"]
            )
            return
        key = (outlook["snapshot_id"], basis["basis_id"])
        expires = min(outlook["valid_until"], outlook["generated_at"] + 120, now + 120)
        expires = min(expires, self.feedback.until) if self.feedback.until is not None else expires
        start = max(now + 120, basis["starts_at"])
        end = min(
            window["ends_at"],
            basis["ends_at"],
            outlook.get("horizon_end", basis["ends_at"]),
        )
        end = self.feedback.limit(end)
        if key in self.attempted or expires - now < 60 or end - start < 600:
            self.withdraw(
                "Wachten op een nieuwe HEMS-basis of een voldoende lang comfortvenster.",
                estimate["samples"],
            )
            return
        bounded = planning_models(plan, [self.model], sample, now, start, end)
        if bounded is None:
            self.withdraw("Uurverwachting ontbreekt of dekt het comfortvenster niet.")
            return
        (future_model,), _ = bounded
        estimate = future_model.estimate(sample, now)
        if estimate["power_w"] is None:
            self.withdraw("Nog geen handhaafbewijs voor alle verwachte weersomstandigheden.")
            return
        value = dict(
            contract="hc-energy-proposals:v2",
            request_id=str(uuid4()),
            revision=1,
            basis_snapshot_id=outlook["snapshot_id"],
            replacement_basis_id=basis["basis_id"],
            generated_at=stamp(now),
            valid_until=stamp(expires),
            demand_basis="replace_controlled_load",
            comfort_equivalent=True,
            plans=[
                dict(
                    plan_id="maintain",
                    non_electric_cost_eur=0,
                    slots=[
                        dict(
                            starts_at=stamp(start),
                            ends_at=stamp(end),
                            energy_wh=round(
                                estimate["power_w"] * (end - start) / 3600
                                + tail_allowance(cv_context, start),
                                3,
                            ),
                        )
                    ],
                )
            ],
        )
        local = dict(
            source="beneden",
            target=sample["target"],
            sample=copy.deepcopy(sample),
            schedule_revision=view["revision"],
            expires=expires,
            estimate=estimate,
            starts_at=start,
            ends_at=end,
            action="maintain_temperature",
        )
        if modeled_id:
            value["modeled_source_id"] = modeled_id
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO hc_energy_proposals VALUES (?, ?, ?)",
                (
                    value["request_id"],
                    now,
                    json.dumps(dict(request=value, local=local), allow_nan=False),
                ),
            )
            db.execute(
                "DELETE FROM hc_energy_proposals WHERE id NOT IN "
                "(SELECT id FROM hc_energy_proposals ORDER BY time DESC LIMIT 96)"
            )
        self.pending, self.local = value, local
        self.attempted = (self.attempted + [key])[-16:]
        self.status = dict(
            status="proposed",
            reason="Voorstel voor temperatuur handhaven aangeboden aan HEMS.",
            samples=estimate["samples"],
            target=sample["target"],
            power_w=estimate["power_w"],
            starts_at=start,
            ends_at=end,
            valid_until=expires,
            request_id=value["request_id"],
            energy_wh=value["plans"][0]["slots"][0]["energy_wh"],
        )
        self.publisher.submit(dict(state="requested", attributes=value))

    def warmup_tick(self, sample, view, plan, outlook, now, warmup):
        basis = outlook.get("replacement_basis") or {}
        window = view.get("next")
        if (
            sample is None
            or not window
            or outlook.get("status") != "ready"
            or basis.get("source_id") != sample["source_id"]
            or outlook.get("valid_until", 0) <= now
        ):
            self.withdraw("Opwarmvoorstel wacht op geldige metingen en een passende HEMS-basis.")
            return
        if self.pending and self.local and self.local.get("action") == "continue_warmup":
            if (
                now < self.local["expires"]
                and view["revision"] == self.local["schedule_revision"]
                and self.model.same(sample, self.local["sample"])
                and abs(sample["indoor"] - self.local["sample"]["indoor"]) <= 0.25
                and abs(sample["outdoor"] - self.local["sample"]["outdoor"]) <= 1.5
            ):
                self.publisher.submit(dict(state="requested", attributes=self.pending))
                return
        key = (outlook["snapshot_id"], basis["basis_id"])
        expires = min(outlook["valid_until"], outlook["generated_at"] + 120, now + 120)
        expires = min(expires, self.feedback.until) if self.feedback.until is not None else expires
        start = max(now + 120, basis["starts_at"])
        end = min(
            window["ends_at"],
            basis["ends_at"],
            outlook.get("horizon_end", basis["ends_at"]),
        )
        end = self.feedback.limit(end)
        options = candidates(sample, view, plan, warmup, self.model, now, start, end)
        if self.cv_context and self.cv_context.get("joint_basis"):
            for option in options:
                option["slots"][0]["energy_wh"] += tail_allowance(self.cv_context, start)
        if not options or key in self.attempted or expires - now < 60:
            self.withdraw("Nog geen passend opwarm- en handhaafbewijs binnen de comfortdeadline.")
            return
        self.offer_options(
            sample, view, outlook, now, options, start, end, expires, "warmup", "continue_warmup"
        )

    def delayed_tick(self, sample, view, plan, outlook, now, startup):
        basis = outlook.get("replacement_basis") or {}
        window = view.get("next")
        if (
            not window
            or outlook.get("status") != "ready"
            or basis.get("source_id") != sample["source_id"]
            or outlook.get("valid_until", 0) <= now
        ):
            self.withdraw("Starttijdvoorstellen wachten op een passende actuele HEMS-basis.")
            return
        start = max(now + (30 if self.fixed_start is not None else 120), basis["starts_at"])
        end = min(
            window["ends_at"],
            basis["ends_at"],
            outlook.get("horizon_end", basis["ends_at"]),
        )
        end = self.feedback.limit(end)
        standby = self.standby.estimate(now)
        options = self.delayed_options(
            sample,
            view,
            plan,
            startup.model,
            self.model,
            standby,
            now,
            start,
            end,
            fixed_start=self.fixed_start,
        )
        if not options:
            self.withdraw(
                "Nog onvoldoende passend afkoel-, standby-, start- of handhaafbewijs "
                "voor een starttijd binnen de comfortgrenzen."
            )
            return
        if self.pending and self.local and self.local.get("action") == "scheduled_start":
            old = self.local["sample"]
            previous = self.local["candidates"]
            checked = self.delayed_options(
                sample,
                view,
                plan,
                startup.model,
                self.model,
                standby,
                now,
                self.local["starts_at"],
                self.local["ends_at"],
                fixed_start=previous[0]["heat_starts_at"] if len(previous) == 1 else None,
            )
            by_start = {(p.get("source", "beneden"), p["heat_starts_at"]): p for p in checked}

            def key_for(p):
                return p.get("source", "beneden"), p["heat_starts_at"]

            supported = all(
                key_for(p) in by_start
                and by_start[key_for(p)].get("non_electric_cost_eur", 0)
                <= p.get("non_electric_cost_eur", 0) + 1e-6
                and by_start[key_for(p)]["startup_energy_wh"] <= p["startup_energy_wh"] + 1e-6
                and by_start[key_for(p)]["startup_duration_seconds"]
                <= p["startup_duration_seconds"]
                and by_start[key_for(p)]["maintenance"]["power_w"]
                <= p["maintenance"]["power_w"] + 1e-6
                for p in previous
            )
            if (
                now < self.local["expires"]
                and supported
                and view["revision"] == self.local["schedule_revision"]
                and self.model.same(sample, old)
                and sample["indoor"] == old["indoor"]
                and sample["outdoor"] == old["outdoor"]
                and standby <= min(p["standby_w"] for p in previous) + 1e-6
                and plan["learning_status"]["cooling_rate"]
                <= min(p["cooling_rate"] for p in previous)
            ):
                self.publisher.submit(dict(state="requested", attributes=self.pending))
                return
        expires = min(outlook["valid_until"], outlook["generated_at"] + 120, now + 120)
        expires = min(expires, self.feedback.until) if self.feedback.until is not None else expires
        key = (outlook["snapshot_id"], basis["basis_id"])
        if key in self.attempted or expires - now < 60:
            self.withdraw("Wachten op een nieuwe HEMS-basis voor starttijdvoorstellen.")
            return
        self.offer_options(
            sample,
            view,
            outlook,
            now,
            options,
            start,
            end,
            expires,
            "delayed_start",
            "scheduled_start",
        )

    def offer_options(self, sample, view, outlook, now, options, start, end, expires, kind, action):
        basis = outlook["replacement_basis"]
        key = (outlook["snapshot_id"], basis["basis_id"])
        value = dict(
            contract="hc-energy-proposals:v2",
            request_id=str(uuid4()),
            revision=1,
            basis_snapshot_id=outlook["snapshot_id"],
            replacement_basis_id=basis["basis_id"],
            generated_at=stamp(now),
            valid_until=stamp(expires),
            demand_basis="replace_controlled_load",
            comfort_equivalent=True,
            plans=[
                dict(
                    plan_id=p["plan_id"],
                    non_electric_cost_eur=p.get("non_electric_cost_eur", 0),
                    slots=[
                        dict(
                            starts_at=stamp(s["starts_at"]),
                            ends_at=stamp(s["ends_at"]),
                            energy_wh=round(s["energy_wh"], 3),
                        )
                        for s in p["slots"]
                    ],
                )
                for p in options
            ],
        )
        if basis.get("modeled_source_id"):
            value["modeled_source_id"] = basis["modeled_source_id"]
        local = dict(
            action=action,
            source="beneden",
            sample=copy.deepcopy(sample),
            schedule_revision=view["revision"],
            expires=expires,
            candidates=options,
            starts_at=start,
            ends_at=end,
        )
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO hc_energy_proposals VALUES (?, ?, ?)",
                (
                    value["request_id"],
                    now,
                    json.dumps(dict(request=value, local=local), allow_nan=False),
                ),
            )
            db.execute(
                "DELETE FROM hc_energy_proposals WHERE id NOT IN "
                "(SELECT id FROM hc_energy_proposals ORDER BY time DESC LIMIT 96)"
            )
        self.pending, self.local = value, local
        self.attempted = (self.attempted + [key])[-16:]
        self.status = dict(
            status="proposed",
            kind=kind,
            samples=min(p["samples"] for p in options),
            reason="Opwarmvoorstellen aangeboden aan HEMS.",
            starts_at=start,
            ends_at=end,
            valid_until=expires,
            request_id=value["request_id"],
            alternatives=len(options),
            sources=[p.get("source", "beneden") for p in options],
            targets=[p["target"] for p in options],
            heat_starts_at=[p["heat_starts_at"] for p in options if "heat_starts_at" in p],
        )
        self.publisher.submit(dict(state="requested", attributes=value))

    def delayed_options(
        self, sample, view, plan, startup, steady, standby, now, start, end, *, fixed_start=None
    ):
        options = delayed_candidates(
            sample,
            view,
            plan,
            startup,
            steady,
            standby,
            now,
            start,
            end,
            fixed_start=fixed_start,
            cooling=self.cooling,
        )
        context = self.cv_context
        if context and context.get("joint_basis"):
            if end != view["next"]["ends_at"]:
                return []
            other = cv_candidates(
                sample,
                view,
                plan,
                context,
                standby,
                now,
                start,
                end,
                fixed_start=fixed_start,
                cooling=self.cooling,
            )
            if other:
                options = options[:2] + other[:3]
            for p in options:
                p["slots"][0]["energy_wh"] += tail_allowance(
                    context, start, p["heat_starts_at"] if p.get("source") == "cv" else None
                )
        if fixed_start is not None and self.fixed_source is not None:
            options = [p for p in options if p.get("source", "beneden") == self.fixed_source]
        return options

    def view(self, now):
        if self.status["status"] == "proposed" and now >= self.status["valid_until"]:
            return dict(
                status="waiting",
                reason="Voorstel verlopen; nieuwe beoordeling nodig.",
                samples=self.status["samples"],
            )
        return dict(copy.deepcopy(self.status), replanning=self.feedback.view())
