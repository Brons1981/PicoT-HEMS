"""Durable EV sessions and explicitly confirmed charger execution; no storage control."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import median
from threading import Event, RLock
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

Payload = dict[str, Any]

CONTRACT = "energy-device-session-demand:v1"
OPEN = {"recognized", "planned", "active", "interrupted"}
RECOGNITION_MAX_AGE_SECONDS = 75


def instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Een tijd met tijdzone is vereist")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Een tijdzone is vereist")
    return result.astimezone(UTC)


class EVSessionManager:
    """One configured charger. Session identity survives pauses and restarts."""

    def __init__(
        self,
        path: Path,
        *,
        power_entity: str,
        switch_entity: str,
        vehicle_state_entity: str = "",
        plug_entity: str = "binary_sensor.330e_laadkabel",
        soc_entity: str = "sensor.wba5x71010fj59919_state_of_charge_predicted_on_integration_side",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not power_entity.startswith("sensor.") or not switch_entity.startswith("switch."):
            raise ValueError("EV vraagt een vermogenssensor en een switch")
        self.path = path
        self.power_entity = power_entity
        self.switch_entity = switch_entity
        if vehicle_state_entity and not vehicle_state_entity.startswith("sensor."):
            raise ValueError("Voertuigstatus vraagt een sensor")
        self.vehicle_state_entity = vehicle_state_entity
        if plug_entity and not plug_entity.startswith("binary_sensor."):
            raise ValueError("Aansluitstatus vraagt een binary_sensor")
        self.plug_entity = plug_entity
        if soc_entity and not soc_entity.startswith("sensor."):
            raise ValueError("Auto-SOC vraagt een sensor")
        self.soc_entity = soc_entity
        self.exchange_wake = Event()
        self.now = now or (lambda: datetime.now(UTC))
        self.lock = RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS ev_session_state (id INTEGER PRIMARY KEY, "
                "payload TEXT NOT NULL)"
            )
            db.execute(
                "INSERT OR IGNORE INTO ev_session_state VALUES (1, ?)",
                (json.dumps({"sessions": [], "resume_verified": False}),),
            )

        state = self.load()
        old_target = state.get("switch_entity")
        old_source = state.get("power_entity")
        if old_target is not None and (old_target != switch_entity or old_source != power_entity):
            if self.current(state) is not None:
                raise ValueError(
                    "Annuleer de bestaande EV-sessie v��r het wijzigen van de meetplug"
                )
            state["resume_verified"] = False
            state.pop("profile", None)
            state.pop("charging_request", None)
            state.pop("charging_advice", None)
        state.update(switch_entity=switch_entity, power_entity=power_entity)
        self.save(state)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def load(self) -> Payload:
        with self.connect() as db:
            return cast(
                Payload,
                json.loads(
                    db.execute("SELECT payload FROM ev_session_state WHERE id=1").fetchone()[0]
                ),
            )

    def save(self, state: Payload) -> None:
        with self.connect() as db:
            db.execute("UPDATE ev_session_state SET payload=? WHERE id=1", (json.dumps(state),))

    @staticmethod
    def current(state: Payload) -> Payload | None:
        return next((s for s in reversed(state["sessions"]) if s["state"] in OPEN), None)

    @staticmethod
    def change(session: Payload, **changes: object) -> None:
        if any(session.get(k) != v for k, v in changes.items()):
            session.update(changes)
            session["version"] += 1

    def view(self) -> Payload:
        with self.lock:
            state = self.load()
            return {**state, "power_entity": self.power_entity, "switch_entity": self.switch_entity,
                    "plug_entity": self.plug_entity, "soc_entity": self.soc_entity}

    def _soc_problem(self, state: Payload, stamp: datetime) -> str | None:
        age = (self.now() - stamp).total_seconds()
        if age < 0:
            return "SOC-rapporttijd ligt in de toekomst"
        try:
            connected = (instant(state["plug_observed_at"])
                         if state.get("plug_state") == "on" else None)
            before_connection = (connected - stamp).total_seconds() if connected else 0
            # BMW can publish its arrival SOC just before publishing the cable state.
            if before_connection > 120:
                return (f"SOC-rapport is {before_connection:.0f} seconden van vóór aansluiten; "
                        "maximaal 120 seconden toegestaan")
            if age <= 1800 and before_connection <= 0:
                return None
            if state.get("soc_charge_observed_at") and instant(
                    state["soc_charge_observed_at"]) > stamp:
                return "Na dit SOC-rapport is laadvermogen gemeten; nieuw SOC-rapport nodig"
            if (connected is not None
                    and 0 <= (self.now() - instant(state.get("plug_checked_at"))).total_seconds()
                    <= 30):
                return None
        except (TypeError, ValueError, KeyError):
            pass
        return (f"Auto-SOC is {age / 60:.0f} minuten oud; "
                "geen actuele bevestiging van deze aansluiting")

    def _soc_usable(self, state: Payload, stamp: datetime) -> bool:
        return self._soc_problem(state, stamp) is None

    def observe_soc(self, value: object, reported_at: object, *, error: str | None = None) -> None:
        with self.lock:
            state = self.load()
            percent = None
            stamp = None
            age = None
            status, reason = "ready", "SOC beschikbaar"
            try:
                percent = float(str(value))
                if not isfinite(percent) or not 0 <= percent <= 100:
                    raise ValueError("invalid percent")
            except (TypeError, ValueError):
                status, reason = "unavailable", "Auto-SOC ontbreekt of is geen geldig percentage"
            if status == "ready":
                try:
                    stamp = instant(reported_at)
                    age = (self.now() - stamp).total_seconds()
                    if age < 0:
                        status, reason = "future", "SOC-rapporttijd ligt in de toekomst"
                    else:
                        problem = self._soc_problem(state, stamp)
                        if problem:
                            status, reason = "stale", problem
                        elif (state.get("plug_state") == "on"
                              and stamp < instant(state["plug_observed_at"])):
                            reason = ("SOC vlak vóór aansluiten geaccepteerd als beginstand "
                                      "(maximaal 120 seconden); geen later laadvermogen gemeten")
                        elif age > 1800:
                            reason = "SOC van deze aansluiting; geen later laadvermogen gemeten"
                except (TypeError, ValueError):
                    status, reason = "missing_timestamp", "SOC-rapporttijd ontbreekt of is ongeldig"
            if error:
                status = "read_failed"
                reason = "Auto-SOC kon niet uit Home Assistant worden gelezen"
            state["soc_observation"] = {
                "source": self.soc_entity, "raw_state": str(value)[:100],
                "reported_at": str(reported_at)[:100] if reported_at is not None else None,
                "checked_at": self.now().isoformat(), "age_seconds": age,
                "status": status, "reason": reason,
                "plug_observed_at": state.get("plug_observed_at"),
                "arrival_margin_seconds": 120,
            }
            state["vehicle_soc"] = ({"percent": percent, "reported_at": stamp.isoformat(),
                                     "source": self.soc_entity}
                                    if status == "ready" and stamp is not None else None)
            self.save(state)

    def _target_energy(self, state: Payload) -> float | None:
        target = state.get("charge_target")
        if not target or not target.get("enabled"):
            return None
        soc = state.get("vehicle_soc")
        if not soc or not self._soc_usable(state, instant(soc["reported_at"])):
            raise ValueError("Wachten op een actueel SOC-percentage van de auto: "
                                 + state.get("soc_observation", {}).get("reason",
                                     "nog geen bruikbaar SOC-rapport ontvangen"))
        return float(max(0.0, target["percent"] - soc["percent"])
                     * target["full_charge_kwh"] * 10)

    def observe_plug(self, value: str, changed_at: object) -> None:
        """One durable request per connection; missing data is not a disconnect."""
        with self.lock:
            state = self.load()
            state["plug_state"] = value
            state["plug_checked_at"] = self.now().isoformat()
            policy = state.get("auto_charge") or {}
            if value not in {"on", "off"} or changed_at is None:
                self.save(state)
                return
            try:
                stamp = instant(changed_at)
                if stamp > self.now():
                    return
                previous = state.get("plug_observed_at")
                if previous and stamp < instant(previous):
                    return
            except ValueError:
                return
            state["plug_observed_at"] = stamp.isoformat()
            session = self.current(state)
            request = state.get("charging_request") or {}
            if value == "off":
                state.pop("plug_connection", None)
                if request.get("source") == "plug" and request.get("state") in {
                    "requested", "accepted", "executing"
                }:
                    request["state"] = "cancelled"
                    state["charging_advice"] = None
                if session and session.get("request_source") == "plug":
                    self.change(session, cancel_requested=True)
                self.save(state)
                return
            token = self.plug_entity + ":" + stamp.isoformat()
            if (not policy.get("enabled") or state.get("plug_connection") == token
                    or session or request.get("state") in {"requested", "accepted", "executing"}
                    or not state.get("profile")):
                self.save(state)
                return
            now = self.now().astimezone(ZoneInfo(policy["timezone"]))
            hour, minute = map(int, policy["ready_time"].split(":"))
            ready = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if ready <= now:
                ready += timedelta(days=1)
            profile = state["profile"]
            try:
                energy = self._target_energy(state)
            except ValueError as exc:
                state["auto_charge_status"] = str(exc)
                self.save(state)
                return
            if energy is not None and energy < profile["expected_power_w"] / 60:
                state["plug_connection"] = token
                state["auto_charge_status"] = "Laaddoel bereikt of minder dan één minuut nodig"
                self.save(state)
                return
            self.save(state)
            self.action({"action": "request_automatic", "source": "plug",
                         "ready_by": ready.isoformat(),
                         "required_energy_wh": energy if energy is not None else
                         profile["expected_power_w"] * profile["expected_duration_seconds"] / 3600})
            state = self.load()
            state["plug_connection"] = token
            state["auto_charge_status"] = "Laadmoment aanvragen"
            self.save(state)

    def refresh_automatic_request(self) -> None:
        """Keep user intent while renewing expired advice, without authorising a stale plan."""
        with self.lock:
            state = self.load()
            request = state.get("charging_request") or {}
            session = self.current(state)
            if (request.get("automatic_execution") and request.get("state") == "accepted"
                    and session and session.get("joint_pending")
                    and session.get("error") == "market binding requires its restored shared plan"):
                self._renew_request(state, "Laadmoment opnieuw aanvragen zonder oude marktroutes")
                self.save(state)
                return
            if request.get("state") != "requested" or not request.get("automatic_execution"):
                return
            now = self.now()
            if now >= instant(request["ready_by"]):
                request.update(state="expired", status_reason="De eindtijd is verstreken")
                state["charging_advice"] = None
            elif (now - instant(request["evidence_at"])).total_seconds() >= 300:
                self._renew_request(state, "Actueel laadmoment opnieuw aanvragen")
            self.save(state)

    def _renew_request(self, state: Payload, reason: str) -> None:
        request = state["charging_request"]
        session = self.current(state)
        if session is not None:
            # Only an uncommitted session can be superseded automatically.
            if not session.get("joint_pending") or session.get("cancel_requested"):
                return
            self.change(session, state="cancelled", confirmed=False, joint_pending=False)
        now = self.now()
        request.update(state="requested" if now < instant(request["ready_by"]) else "expired",
                       request_revision=request["request_revision"] + 1,
                       available_from=now.isoformat(), evidence_at=now.isoformat(),
                       status_reason=reason)
        state["charging_advice"] = None
        self.exchange_wake.set()

    @staticmethod
    def invalidate_advice(state: Payload) -> None:
        request = state.get("charging_request")
        if request and request["state"] == "requested":
            request.update(state="cancelled", request_revision=request["request_revision"] + 1)
        state["charging_advice"] = None

    def advice_exchange(self) -> Payload:
        with self.lock:
            state = self.load()
            # A physical session supersedes a pending hypothetical request.
            session = self.current(state)
            if session is not None and not session.get("joint_pending"):
                self.invalidate_advice(state)
                self.save(state)
            return {"generated_at": self.now().isoformat(),
                    "request": state.get("charging_request"),
                    "selected_advice": session.get("accepted_advice") if session else None}

    def receive_advice(self, advice: Payload) -> bool:
        with self.lock:
            state = self.load()
            request = state.get("charging_request")
            session = self.current(state)
            if advice.get("execution_status") == "blocked":
                accepted = session.get("accepted_advice") if session else None
                if (not session or not accepted or not request
                        or request.get("state") != "accepted"
                        or not accepted.get("selection_id")
                        or any(advice.get(k) != accepted.get(k) for k in (
                            "selection_id", "session_id", "request_revision"))):
                    return False
                session["error"] = str(advice.get("reason", "joint_plan_not_confirmed"))[:240]
                if request.get("automatic_execution") and advice.get("reason") in {
                    "joint_selection_expired_request_new_advice", "joint_ev_selection_expired",
                    "joint_ev_slot_requires_fresh_advice", "joint_ev_battery_owner_changed",
                }:
                    self._renew_request(state, "Advies vernieuwen na gewijzigde planning")
                self.save(state)
                return True
            if advice.get("execution_status") == "committed":
                accepted = session.get("accepted_advice") if session else None
                if (not session or not accepted or not request
                        or request.get("state") not in {"accepted", "executing"}
                        or session.get("cancel_requested")
                        or not accepted.get("selection_id")
                        or any(advice.get(k) != accepted.get(k) for k in (
                            "selection_id", "session_id", "request_revision"))
                        or not advice.get("battery_plan_id")):
                    return False
                try:
                    age = (self.now() - instant(advice.get("committed_at"))).total_seconds()
                    if (not 0 <= age <= 300
                            or self.now() > instant(session["planned_start"])
                            and session.get("joint_pending")):
                        return False
                except (ValueError, TypeError):
                    return False
                session.update(confirmed=True, start_status="waiting_for_schedule", error=None,
                               joint_pending=False,
                               joint_receipt=advice)
                request["state"] = "executing"
                self.save(state)
                return True
            if (not request or request["state"] != "requested"
                    or self.current(state) is not None
                    or advice.get("contract") != "energy-device-charging-advice:v1"
                    or advice.get("session_id") != request["session_id"]
                    or type(advice.get("request_revision")) is not int
                    or advice.get("status") not in {"ready", "provisional", "blocked", "infeasible"}
                    or advice.get("request_revision") != request["request_revision"]):
                return False
            try:
                age = (self.now() - instant(advice.get("generated_at"))).total_seconds()
                if not 0 <= age <= 300:
                    return False
                previous = state.get("charging_advice")
                if previous and instant(previous["generated_at"]) > instant(advice["generated_at"]):
                    return False
                slots = advice.get("slots", [])
                if not isinstance(slots, list) or len(slots) > 200:
                    return False
                end = instant(request["available_from"])
                energy = 0.0
                for slot in slots:
                    if not isinstance(slot, dict):
                        return False
                    start, next_end = instant(slot.get("starts_at")), instant(slot.get("ends_at"))
                    amount = slot.get("energy_wh")
                    if (start < end or next_end <= start
                            or next_end > instant(request["ready_by"])
                            or isinstance(amount, bool) or not isinstance(amount, (int, float))
                            or not isfinite(amount) or amount <= 0):
                        return False
                    energy += amount
                    end = next_end
                if energy > request["remaining_energy_wh"] + 1e-6:
                    return False
            except (ValueError, TypeError):
                return False
            state["charging_advice"] = advice
            self.save(state)
            if (request.get("automatic_execution") and advice.get("status") in {
                    "ready", "provisional"} and len(advice.get("slots", [])) == 1):
                try:
                    self.action({"action": "execute_advice", **{
                        key: advice[key] for key in (
                            "session_id", "request_revision", "generated_at")}})
                except ValueError:
                    state = self.load()
                    self._renew_request(state, "Laadblok verlopen; nieuw advies aanvragen")
                    self.save(state)
            return True

    def action(self, payload: Payload) -> Payload:
        with self.lock:
            state = self.load()
            session = self.current(state)
            action = payload.get("action")
            request_target = state.get("charge_target", {})
            if action == "request_full_charge":
                request_target = {"enabled": True, "percent": 100.0,
                                  "full_charge_kwh": request_target.get("full_charge_kwh", 11.7)}
                settings = state.get("auto_charge", {})
                request_zone = ZoneInfo(settings.get("timezone", "Europe/Amsterdam"))
                local_now = self.now().astimezone(request_zone)
                clock = datetime.strptime(settings.get("ready_time", "07:00"), "%H:%M")
                deadline = local_now.replace(hour=clock.hour, minute=clock.minute,
                                             second=0, microsecond=0)
                if deadline <= local_now:
                    deadline += timedelta(days=1)
                payload = {**payload, "ready_by": payload.get("ready_by") or deadline.isoformat()}
                action = "request_automatic"
            if action == "save_charge_target":
                enabled = payload.get("enabled")
                percent, full = payload.get("percent"), payload.get("full_charge_kwh")
                if (type(enabled) is not bool or isinstance(percent, bool)
                        or not isinstance(percent, (int, float)) or not isfinite(percent)
                        or not 1 <= percent <= 100 or isinstance(full, bool)
                        or not isinstance(full, (int, float)) or not isfinite(full)
                        or not 1 <= full <= 150):
                    raise ValueError("Kies een doel van 1–100% en geldige energie voor 0–100%")
                state["charge_target"] = {"enabled": enabled, "percent": float(percent),
                                           "full_charge_kwh": float(full)}
            elif action == "save_auto_charge":
                enabled = payload.get("enabled")
                if type(enabled) is not bool:
                    raise ValueError("Kies automatisch laden aan of uit")
                ready_time = str(payload.get("ready_time", "07:00"))
                try:
                    parsed = datetime.strptime(ready_time, "%H:%M")
                    zone = str(payload.get("timezone", "Europe/Amsterdam"))
                    ZoneInfo(zone)
                except (ValueError, KeyError) as exc:
                    raise ValueError("Kies een geldige eindtijd en tijdzone") from exc
                if enabled and (not state.get("profile") or not self.plug_entity):
                    raise ValueError("Sla eerst het laadprofiel en de aansluitensor op")
                state["auto_charge"] = {"enabled": enabled,
                                        "ready_time": parsed.strftime("%H:%M"), "timezone": zone}
            elif action in {"request_advice", "request_automatic"}:
                if (action == "request_automatic" and session is not None
                        and session.get("joint_pending") and not session.get("confirmed")):
                    self.change(session, state="cancelled", joint_pending=False)
                    if state.get("charging_request"):
                        state["charging_request"]["state"] = "cancelled"
                    session = None
                if session is not None:
                    raise ValueError("Annuleer of voltooi eerst de bestaande laadsessie")
                profile = state.get("profile")
                if not profile:
                    raise ValueError("Sla eerst het laadprofiel op")
                now = self.now()
                deadline = instant(payload.get("ready_by"))
                if not now < deadline <= now + timedelta(days=7):
                    raise ValueError("Kies een eindtijd binnen de komende zeven dagen")
                energy = payload.get("required_energy_wh")
                if action == "request_automatic":
                    estimated = self._target_energy({**state, "charge_target": request_target})
                    if estimated is not None:
                        if estimated < profile["expected_power_w"] / 60:
                            raise ValueError("Laaddoel bereikt of minder dan één minuut nodig")
                        energy = estimated
                if (isinstance(energy, bool) or not isinstance(energy, (int, float))
                        or not isfinite(energy) or not 0 < energy <= 88320):
                    raise ValueError("Geef een geldige laadbehoefte in kWh op")
                old = state.get("charging_request") or {}
                same = old.get("state") == "requested"
                if (same and old["ready_by"] == deadline.isoformat()
                        and old["remaining_energy_wh"] == energy
                        and old["fixed_power_w"] == profile["expected_power_w"]
                        and old.get("soc_target") == (request_target.get("percent")
                            if request_target.get("enabled") else None)
                        and bool(old.get("automatic_execution"))
                        == (action == "request_automatic")):
                    return self.view()
                state["charging_request"] = {
                    "contract": "energy-device-charging-request:v1",
                    "session_id": old["session_id"] if same else str(uuid4()),
                    "request_revision": old["request_revision"] + 1 if same else 1,
                    "state": "requested", "available_from": now.isoformat(),
                    "ready_by": deadline.isoformat(), "remaining_energy_wh": float(energy),
                    "fixed_power_w": profile["expected_power_w"],
                    "evidence_source": "user_grid_energy_estimate",
                    "evidence_at": now.isoformat(), "charge_target": "requested_grid_energy",
                    "automatic_execution": action == "request_automatic",
                    "source": "plug" if payload.get("source") == "plug" else "user",
                    "soc_target": (request_target["percent"]
                                   if request_target.get("enabled") else None),
                }
                state["charging_advice"] = None
            elif action == "cancel_advice":
                if session is not None and session.get("joint_pending"):
                    self.change(session, state="cancelled", confirmed=False)
                    if state.get("charging_request"):
                        state["charging_request"]["state"] = "cancelled"
                self.invalidate_advice(state)
            elif action == "save_profile":
                power = payload.get("expected_power_w")
                duration = payload.get("expected_duration_seconds")
                for value in (power, duration):
                    if (isinstance(value, bool) or not isinstance(value, (int, float))
                            or not isfinite(value)):
                        raise ValueError("Vermogen en laadduur moeten geldige getallen zijn")
                power = float(cast(float, power))
                duration = float(cast(float, duration))
                if not 100 <= power <= 3680:
                    raise ValueError("Laadvermogen moet tussen 100 en 3680 W liggen")
                if not 60 <= duration <= 24 * 3600:
                    raise ValueError("Laadduur moet tussen 1 minuut en 24 uur liggen")
                state["profile"] = {
                    "expected_power_w": power, "expected_duration_seconds": duration,
                }
            elif action in {"start_now", "start_at", "execute_advice"}:
                accepted = None
                request = state.get("charging_request") or {}
                if action == "execute_advice":
                    accepted = state.get("charging_advice")
                    if (session is not None and session.get("accepted_advice")
                            and session["session_id"] == payload.get("session_id")
                            and session["accepted_advice"]["generated_at"]
                            == payload.get("generated_at")):
                        return self.view()
                    if (not accepted or request.get("state") != "requested"
                            or accepted.get("status") not in {"ready", "provisional"}
                            or any(payload.get(k) != accepted.get(k)
                                   for k in ("session_id", "request_revision", "generated_at"))
                            or not 0 <= (self.now() - instant(
                                accepted["generated_at"])).total_seconds() <= 300
                            or len(accepted.get("slots", [])) != 1):
                        raise ValueError("Advies gewijzigd of verlopen; bekijk het actuele advies")
                    slot = accepted["slots"][0]
                    start, end = instant(slot["starts_at"]), instant(slot["ends_at"])
                    duration = (end - start).total_seconds()
                    energy = request["remaining_energy_wh"]
                    power = request["fixed_power_w"]
                    if (end <= self.now() or start < self.now() - timedelta(seconds=60)
                            or end > instant(request["ready_by"])
                            or not 60 <= duration <= 86400
                            or abs(slot["energy_wh"] - energy) > 0.01
                            or abs(power * duration / 3600 - energy) > 0.01):
                        raise ValueError("Laadblok niet uitvoerbaar; vraag een actueel advies aan")
                if session is not None:
                    raise ValueError("Er is al een open EV-sessie; hervat of annuleer die eerst")
                profile = state.get("profile")
                if not profile:
                    raise ValueError("Sla eerst het laadprofiel op")
                self.invalidate_advice(state)
                now = self.now()
                scheduled = instant(payload.get("planned_start")) if action == "start_at" else now
                if action == "start_at" and not now < scheduled <= now + timedelta(days=7):
                    raise ValueError("Kies een starttijd binnen de komende zeven dagen")
                power = profile["expected_power_w"]
                duration = profile["expected_duration_seconds"]
                energy = power * duration / 3600
                if action in {"start_now", "start_at"}:
                    target_energy = self._target_energy(state)
                    if target_energy is not None:
                        if target_energy < power / 60:
                            raise ValueError("Laaddoel bereikt of minder dan één minuut nodig")
                        energy = target_energy
                        duration = energy * 3600 / power
                        if duration > 86400:
                            raise ValueError("Geschatte laadduur is langer dan 24 uur")
                session = {
                    "session_id": str(uuid4()), "version": 1, "state": "planned",
                    "recognized_at": now.isoformat(), "recognition_source": "user_start",
                    "planned_start": scheduled.isoformat(),
                    "planned_end": (scheduled + timedelta(seconds=duration)).isoformat(),
                    "fixed_start": action == "start_at",
                    "expected_power_w": power, "expected_duration_seconds": duration,
                    "remaining_energy_wh": energy, "target_energy_wh": energy,
                    "delivered_energy_wh": 0.0, "planned_delivered_base_wh": 0.0,
                    "current_power_w": None, "last_measured_at": None, "last_power_w": None,
                    "measurement_complete": True, "measurement_available": False,
                    "confirmed": True, "owns_switch": False, "manual_pause": False,
                    "direct_start_authorized": True, "start_status": "waiting_for_switch",
                    "error": None, "duration_source": "saved_user_profile",
                    "energy_source": "integrated_power", "uncertainty": "user_estimate",
                    "recognition_samples": [],
                    "soc_target": (state["charge_target"]["percent"]
                                   if state.get("charge_target", {}).get("enabled") else None),
                    "soc_at_request": (state.get("vehicle_soc") or {}).get("percent"),
                }
                if accepted is not None:
                    slot = accepted["slots"][0]
                    start, end = instant(slot["starts_at"]), instant(slot["ends_at"])
                    session.update(
                        session_id=request["session_id"],
                        recognition_source="accepted_hems_advice",
                        planned_start=start.isoformat(), planned_end=end.isoformat(),
                        expected_power_w=request["fixed_power_w"],
                        expected_duration_seconds=(end - start).total_seconds(),
                        remaining_energy_wh=request["remaining_energy_wh"],
                        target_energy_wh=request["remaining_energy_wh"],
                        accepted_advice=accepted, duration_source="hems_advice",
                        start_status="waiting_for_schedule", ready_by=request["ready_by"],
                        request_source=request.get("source", "user"),
                        soc_target=request.get("soc_target"),
                    )
                    request.update(state="accepted", request_revision=accepted["request_revision"])
                    if accepted.get("selection_id"):
                        session.update(confirmed=False, start_status="waiting_for_hems",
                                       joint_pending=True)
                state["sessions"].append(session)
                state["sessions"] = state["sessions"][-30:]
            elif action == "verify_resume":
                if payload.get("confirmed") is not True:
                    raise ValueError("Bevestig eerst dat de auto na uit/aan werkelijk hervat")
                state["resume_verified"] = True
            elif action == "plan":
                if session is not None and session.get("accepted_advice"):
                    raise ValueError("Annuleer het vastgezette laadblok voor een nieuwe planning")
                if session is None or session["session_id"] != payload.get("session_id"):
                    raise ValueError("Herken eerst de aangesloten auto met een meting boven 2000 W")
                if session["state"] == "active":
                    raise ValueError("Onderbreek het laden eerst met de smartplug")
                start = instant(payload.get("planned_start"))
                if start <= self.now():
                    raise ValueError("Kies een toekomstige starttijd")
                power = float(
                    payload.get("expected_power_w", session.get("expected_power_w", 0)) or 0
                )
                duration = float(payload.get("expected_duration_seconds", 0))
                if not isfinite(power) or not 100 <= power <= 3680:
                    raise ValueError("Laadvermogen moet tussen 100 en 3680 W liggen")
                if not isfinite(duration) or not 60 <= duration <= 24 * 3600:
                    raise ValueError("Laadduur moet tussen 1 minuut en 24 uur liggen")
                if not state["resume_verified"]:
                    raise ValueError("Voer eerst de hervattest uit en bevestig deze")
                self.change(
                    session,
                    state="planned",
                    planned_start=start.isoformat(),
                    expected_power_w=power,
                    remaining_energy_wh=power * duration / 3600,
                    target_energy_wh=power * duration / 3600,
                    expected_duration_seconds=duration,
                    planned_end=(start + timedelta(seconds=duration)).isoformat(),
                    confirmed=True,
                    error=None,
                    command=None,
                    last_command_at=None,
                    duration_source="user_confirmed",
                    uncertainty="user_estimate",
                    manual_pause=False,
                )
                session["planned_delivered_base_wh"] = session["delivered_energy_wh"]
            elif action == "resume":
                if session is None or not session.get("confirmed"):
                    raise ValueError("Geen bevestigde sessie om te hervatten")
                self.change(session, manual_pause=False)
            elif action == "cancel":
                if session is None or session["session_id"] != payload.get("session_id"):
                    raise ValueError("Onbekende sessie")
                # Explicit cancellation also requests the selected charger off.
                self.change(session, cancel_requested=True)
                if session.get("joint_pending") and state.get("charging_request"):
                    state["charging_request"]["state"] = "cancelled"
            else:
                raise ValueError("Onbekende EV-actie")
            self.save(state)
            self.exchange_wake.set()
            return self.view()

    def vehicle_auto_off(
        self, state: Payload, session: Payload, *, now: datetime,
        switch_state: str, switch_changed_at: datetime | None,
        vehicle_state: str | None, vehicle_changed_at: datetime | None,
        set_switch: Callable[[bool], None],
    ) -> bool:
        """One minute after a current vehicle end event, stop even a manual session."""
        value = (vehicle_state or "unavailable").strip().lower()
        session["vehicle_state"] = value
        changed_source = session.get("vehicle_state_entity") != self.vehicle_state_entity
        session["vehicle_state_entity"] = self.vehicle_state_entity
        new_switch_on = (
            switch_state == "on" and switch_changed_at is not None
            and (not session.get("vehicle_switch_on_at")
                 or switch_changed_at > instant(session["vehicle_switch_on_at"]))
        )
        if new_switch_on:
            assert switch_changed_at is not None
            session["vehicle_switch_on_at"] = switch_changed_at.isoformat()
        reset = changed_source or new_switch_on or not self.vehicle_state_entity
        if reset:
            for key in ("vehicle_active_at", "vehicle_end_seen_at", "vehicle_stop_requested",
                        "vehicle_completion_at", "vehicle_end_event_at"):
                session.pop(key, None)
        # A pending stop is durable across transient missing BMW data and restart.
        if session.get("vehicle_stop_requested") and switch_state == "off":
            self.change(session, state="completed", confirmed=False, command=None,
                        completion_reason="vehicle_charging_ended", error=None)
            session.pop("vehicle_stop_requested", None)
            session.pop("vehicle_end_seen_at", None)
            session.pop("vehicle_active_at", None)
            return True
        fresh = (
            bool(self.vehicle_state_entity) and vehicle_changed_at is not None
            and 0 <= (now - vehicle_changed_at).total_seconds() <= 300
            and vehicle_changed_at >= instant(session["recognized_at"])
            and (switch_changed_at is None or vehicle_changed_at >= switch_changed_at)
            and (not session.get("planned_start")
                 or vehicle_changed_at >= instant(session["planned_start"]))
        )
        if fresh and value == "chargingactive" and switch_state == "on":
            assert vehicle_changed_at is not None
            session["vehicle_active_at"] = vehicle_changed_at.isoformat()
            for key in ("vehicle_end_seen_at", "vehicle_stop_requested", "vehicle_end_event_at",
                        "vehicle_completion_at"):
                session.pop(key, None)
        elif not session.get("vehicle_stop_requested"):
            valid_end = (fresh and value == "chargingended" and switch_state == "on"
                         and session.get("vehicle_active_at") and vehicle_changed_at is not None
                         and vehicle_changed_at > instant(session["vehicle_active_at"])
                         and (session.get("command") != "turn_off"
                              or (session.get("last_command_at")
                                  and instant(session["vehicle_active_at"])
                                  > instant(session["last_command_at"]))))
            if valid_end:
                assert vehicle_changed_at is not None
                session.setdefault("vehicle_end_seen_at", now.isoformat())
                session["vehicle_end_event_at"] = vehicle_changed_at.isoformat()
            else:
                session.pop("vehicle_end_seen_at", None)
                if switch_state != "on" or value not in {"chargingactive", "chargingended"}:
                    session.pop("vehicle_active_at", None)
        since = session.get("vehicle_end_seen_at")
        if (since and (now - instant(since)).total_seconds() >= 60
                and switch_state == "on"):
            session["vehicle_stop_requested"] = True
            session["vehicle_completion_at"] = session["vehicle_end_event_at"]
        if not session.get("vehicle_stop_requested"):
            return False
        # Same persisted intent / ten-second retry rule as the scheduled executor.
        last = session.get("last_command_at")
        if switch_state == "on" and (
            last is None or (now - instant(last)).total_seconds() >= 10
        ):
            session.update(command="turn_off", last_command_at=now.isoformat(), owns_switch=True)
            self.save(state)
            try:
                set_switch(False)
                session["error"] = None
            except (OSError, ValueError) as error:
                session["error"] = str(error)[:240]
        return True

    def tick(
        self,
        *,
        measured_at: datetime | None,
        power_w: float | None,
        switch_state: str,
        set_switch: Callable[[bool], None],
        switch_changed_at: datetime | None = None,
        vehicle_state: str | None = None,
        vehicle_changed_at: datetime | None = None,
    ) -> Payload:
        """Called every second; missing data never proves charge completion."""
        with self.lock:
            state = self.load()
            now = self.now()
            fresh = (
                measured_at is not None
                and power_w is not None
                and isfinite(power_w)
                and power_w >= 0
                and 0 <= (now - measured_at).total_seconds() <= 15
            )
            if fresh and power_w is not None and power_w >= 100 and measured_at is not None:
                state["soc_charge_observed_at"] = measured_at.isoformat()
            session = self.current(state)
            request = state.get("charging_request") or {}
            hold_for_advice = bool(request.get("automatic_execution") and (
                request.get("state") == "requested" or session and session.get("joint_pending")))
            if hold_for_advice and switch_state == "on":
                last_hold = state.get("advice_hold_command_at")
                if last_hold is None or (now - instant(last_hold)).total_seconds() >= 10:
                    state["advice_hold_command_at"] = now.isoformat()
                    self.save(state)
                    try:
                        set_switch(False)
                        state.pop("advice_hold_error", None)
                    except (OSError, ValueError) as exc:
                        state["advice_hold_error"] = str(exc)[:240]
            if session is None and not hold_for_advice:
                age = (now - measured_at).total_seconds() if measured_at is not None else None
                usable = (age is not None and 0 <= age <= RECOGNITION_MAX_AGE_SECONDS
                          and power_w is not None and isfinite(power_w) and power_w >= 0)
                after_switch_on = (switch_changed_at is None or (
                    measured_at is not None and measured_at >= switch_changed_at
                ))
                previous_report = state.get("last_recognition_report")
                new_report = (measured_at is not None and (
                    previous_report is None or measured_at > instant(previous_report)
                ))
                high = (usable and after_switch_on and new_report
                        and power_w is not None and power_w > 2000 and switch_state == "on")
                state["recognition"] = {
                    "power_w": power_w if power_w is not None and isfinite(power_w) else None,
                    "measured_at": measured_at.isoformat() if measured_at else None,
                    "measurement_age_seconds": age,
                    "max_age_seconds": RECOGNITION_MAX_AGE_SECONDS,
                    "switch_state": switch_state,
                    "reason": ("switch_not_on" if switch_state != "on" else
                               "measurement_missing_or_stale" if not usable else
                               "measurement_before_switch_on" if not after_switch_on else
                               "power_not_above_2000w" if power_w is None or power_w <= 2000 else
                               "waiting_for_new_measurement" if not new_report else "recognized"),
                }
                if usable and new_report and measured_at is not None:
                    state["last_recognition_report"] = measured_at.isoformat()
                if high:
                    assert measured_at is not None and power_w is not None
                    session = {
                        "session_id": str(uuid4()), "version": 1, "state": "recognized",
                        "recognized_at": now.isoformat(), "expected_power_w": power_w,
                        "expected_duration_seconds": None, "remaining_energy_wh": None,
                        "delivered_energy_wh": 0.0, "current_power_w": power_w,
                        "last_measured_at": measured_at.isoformat(), "last_power_w": power_w,
                        "measurement_complete": True, "confirmed": False, "owns_switch": False,
                        "error": None, "duration_source": "unknown",
                        "energy_source": "integrated_power", "uncertainty": "duration_unknown",
                        "recognition_samples": [power_w],
                    }
                    state["sessions"].append(session)
                    state["sessions"] = state["sessions"][-30:]
            tracked = session or (state["sessions"][-1] if state["sessions"] else None)
            vehicle_handled = False
            if tracked is not None:
                vehicle_handled = self.vehicle_auto_off(
                    state, tracked, now=now, switch_state=switch_state,
                    switch_changed_at=switch_changed_at, vehicle_state=vehicle_state,
                    vehicle_changed_at=vehicle_changed_at, set_switch=set_switch,
                )
            if (
                session is not None
                and measured_at is not None
                and session.get("last_measured_at") is not None
                and measured_at < instant(session["last_measured_at"])
            ):
                fresh = False
            if session is not None and not vehicle_handled:
                soc = state.get("vehicle_soc")
                if (session.get("soc_target") is not None and soc
                        and 0 <= (now - instant(soc["reported_at"])).total_seconds() <= 1800
                        and soc["percent"] >= session["soc_target"]):
                    session["complete_requested"] = True
                    session["soc_target_reached"] = True
                    # Also cancel an uncommitted selection; never start it later.
                    if session.get("joint_pending"):
                        session["cancel_requested"] = True
                        if state.get("charging_request"):
                            state["charging_request"]["state"] = "cancelled"
                if session.get("direct_start_authorized") and measured_at is not None:
                    if (measured_at < instant(session["recognized_at"])
                            or (switch_changed_at is not None
                                and measured_at < switch_changed_at)):
                        fresh = False
                previous_switch_state = session.get("switch_state")
                session["switch_state"] = switch_state
                session["current_power_w"] = power_w if fresh else None
                session["measurement_available"] = fresh
                if fresh:
                    assert measured_at is not None and power_w is not None
                    previous = (
                        instant(session["last_measured_at"])
                        if session.get("last_measured_at") else measured_at
                    )
                    elapsed = (measured_at - previous).total_seconds()
                    if 0 < elapsed <= 15:
                        energy = (session["last_power_w"] + power_w) / 2 * elapsed / 3600
                        session["delivered_energy_wh"] += energy
                    elif elapsed > 15:
                        session["measurement_complete"] = False
                    if elapsed > 0 or session.get("last_measured_at") is None:
                        session["last_measured_at"] = measured_at.isoformat()
                        session["last_power_w"] = power_w
                    if session.get("confirmed"):
                        used = session["delivered_energy_wh"] - session["planned_delivered_base_wh"]
                        estimate = session["target_energy_wh"]
                        session["remaining_energy_wh"] = max(0.0, estimate - used)
                    if power_w >= 100:
                        if session.get("direct_start_authorized"):
                            session["start_status"] = "charging"
                            session["charging_observed"] = True
                        session.pop("low_since", None)
                        if elapsed > 0:
                            session["recognition_samples"].append(power_w)
                            del session["recognition_samples"][:-30]
                        if session.get("confirmed") and len(session["recognition_samples"]) == 30:
                            stable_power = median(session["recognition_samples"])
                            if abs(stable_power - session["expected_power_w"]) >= 100:
                                self.change(session, expected_power_w=stable_power)
                        # A future plan is preserved even if the user briefly turns the plug on.
                        if session["state"] != "planned" or (
                            session.get("owns_switch") and now >= instant(session["planned_start"])
                        ):
                            self.change(session, state="active")
                    elif switch_state == "on" and session["state"] == "active":
                        session.setdefault("low_since", measured_at.isoformat())
                        if (measured_at - instant(session["low_since"])).total_seconds() >= 300:
                            if session.get("owns_switch"):
                                session["complete_requested"] = True
                            else:
                                self.change(
                                    session,
                                    state="completed",
                                    remaining_energy_wh=0.0,
                                    completion_reason="measured_low_power",
                                )
                else:
                    # Never count a missing interval as a continuous low-power end.
                    session.pop("low_since", None)
                    if session.get("direct_start_authorized") and switch_state == "on":
                        session["measurement_complete"] = False
                if session.get("direct_start_authorized"):
                    if switch_state == "on":
                        session.setdefault("switch_on_observed_at", now.isoformat())
                        if not session.get("charging_observed"):
                            elapsed_on = (
                                now - instant(session["switch_on_observed_at"])
                            ).total_seconds()
                            session["start_status"] = (
                                "measurement_unavailable" if not fresh else
                                "charging_not_started" if elapsed_on >= 120 else
                                "waiting_for_charging"
                            )
                    elif (switch_state == "off" and previous_switch_state != "off"
                          and session.get("switch_on_observed_at")
                          and session.get("owns_switch") and session.get("command") != "turn_off"):
                        self.change(session, state="interrupted", manual_pause=True)
                if switch_state == "off" and session["state"] == "active":
                    self.change(session, state="interrupted")
                    if session.get("owns_switch") and session.get("command") != "turn_off":
                        session["manual_pause"] = True
                if session.get("confirmed") or session.get("cancel_requested"):
                    start = (
                        instant(session["planned_start"]) if session.get("planned_start") else now
                    )
                    end = instant(session["planned_end"]) if session.get("planned_end") else now
                    stop = (
                        session.get("cancel_requested")
                        or session.get("complete_requested")
                        or now >= end
                    )
                    desired = (
                        False
                        if stop
                        else False
                        if (session.get("accepted_advice") or session.get("fixed_start"))
                        and now < start
                        else True
                        if start <= now < end and not session.get("manual_pause")
                        else None
                    )
                    if (desired is True and session.get("request_source") == "plug"
                            and not session.get("charging_observed")):
                        checked = state.get("plug_checked_at")
                        if (state.get("plug_state") != "on" or not checked
                                or not 0 <= (now - instant(checked)).total_seconds() <= 30):
                            desired = False
                            session["start_status"] = "waiting_for_connection"
                    if desired is not None:
                        if switch_state == ("on" if desired else "off"):
                            if not desired and not stop:
                                session["command"] = None
                            elif not desired:
                                self.change(
                                    session,
                                    state="cancelled"
                                    if session.get("cancel_requested")
                                    else "completed",
                                    confirmed=False,
                                    command=None,
                                    completion_reason="cancelled"
                                    if session.get("cancel_requested")
                                    else "soc_target_reached"
                                    if session.get("soc_target_reached")
                                    else "vehicle_charging_ended"
                                    if session.get("vehicle_completion_at")
                                    else "measured_low_power"
                                    if session.get("complete_requested")
                                    else "scheduled_deadline",
                                )
                            else:
                                session["command"] = None
                                session["owns_switch"] = True
                                if session["state"] == "planned":
                                    self.change(session, state="interrupted")
                        elif desired is False or (
                            (state["resume_verified"] or session.get("direct_start_authorized"))
                            and switch_state in {"on", "off"}
                        ):
                            last = session.get("last_command_at")
                            if (last is None or session.get("command") != (
                                    "turn_on" if desired else "turn_off")
                                    or (now - instant(last)).total_seconds() >= 10):
                                session.update(
                                    command="turn_on" if desired else "turn_off",
                                    last_command_at=now.isoformat(),
                                    owns_switch=True,
                                )
                                self.save(
                                    state
                                )  # intent survives service timeout / process restart
                                try:
                                    set_switch(desired)
                                    session["error"] = None
                                except (OSError, ValueError) as error:
                                    session["error"] = str(error)[:240]
            if session is not None:
                remaining = session.get("remaining_energy_wh")
                session["remaining_duration_seconds"] = (
                    remaining * 3600 / session["expected_power_w"]
                    if remaining is not None
                    else None
                )
            self.save(state)
            return self.view()

    def snapshot(self, *, storage_support_allowed: bool = False) -> Payload:
        with self.lock:
            state = self.load()
            session = self.current(state)
            now = self.now()
            if session is None:
                recent = state["sessions"][-1] if state["sessions"] else None
                return {
                    "contract": CONTRACT,
                    "source_id": "energy-devices:ev-session",
                    "power_entity_id": self.power_entity,
                    "switch_entity_id": self.switch_entity,
                    "revision": str(recent["version"]) if recent else "0",
                    "generated_at": now.isoformat(),
                    "session": {k: v for k, v in recent.items()
                                if not k.startswith("vehicle_")} if recent else None,
                    "recognition": state.get("recognition"),
                    "storage_support_allowed": False,
                }
            return {
                "contract": CONTRACT,
                "source_id": "energy-devices:ev-session",
                "power_entity_id": self.power_entity,
                "switch_entity_id": self.switch_entity,
                "revision": str(session["version"]),
                "generated_at": now.isoformat(),
                "session": {k: v for k, v in session.items() if not k.startswith("vehicle_")},
                "recognition": state.get("recognition"),
                "storage_support_allowed": False,
            }
