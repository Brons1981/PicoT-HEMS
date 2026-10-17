"""Durable EV sessions and explicitly confirmed charger execution; no storage control."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import median
from threading import RLock
from typing import Any, cast
from uuid import uuid4

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
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not power_entity.startswith("sensor.") or not switch_entity.startswith("switch."):
            raise ValueError("EV vraagt een vermogenssensor en een switch")
        self.path = path
        self.power_entity = power_entity
        self.switch_entity = switch_entity
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
                    "Annuleer de bestaande EV-sessie vóór het wijzigen van de meetplug"
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
            return {**state, "power_entity": self.power_entity, "switch_entity": self.switch_entity}

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
            if self.current(state) is not None:
                self.invalidate_advice(state)
                self.save(state)
            return {"generated_at": self.now().isoformat(),
                    "request": state.get("charging_request")}

    def receive_advice(self, advice: Payload) -> bool:
        with self.lock:
            state = self.load()
            request = state.get("charging_request")
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
            return True

    def action(self, payload: Payload) -> Payload:
        with self.lock:
            state = self.load()
            session = self.current(state)
            action = payload.get("action")
            if action == "request_advice":
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
                if (isinstance(energy, bool) or not isinstance(energy, (int, float))
                        or not isfinite(energy) or not 0 < energy <= 88320):
                    raise ValueError("Geef een geldige laadbehoefte in kWh op")
                old = state.get("charging_request") or {}
                same = old.get("state") == "requested"
                if (same and old["ready_by"] == deadline.isoformat()
                        and old["remaining_energy_wh"] == energy
                        and old["fixed_power_w"] == profile["expected_power_w"]):
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
                }
                state["charging_advice"] = None
            elif action == "cancel_advice":
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
            elif action in {"start_now", "execute_advice"}:
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
                power = profile["expected_power_w"]
                duration = profile["expected_duration_seconds"]
                energy = power * duration / 3600
                session = {
                    "session_id": str(uuid4()), "version": 1, "state": "planned",
                    "recognized_at": now.isoformat(), "recognition_source": "user_start",
                    "planned_start": now.isoformat(),
                    "planned_end": (now + timedelta(seconds=duration)).isoformat(),
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
                    )
                    request.update(state="accepted", request_revision=accepted["request_revision"])
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
            else:
                raise ValueError("Onbekende EV-actie")
            self.save(state)
            return self.view()

    def tick(
        self,
        *,
        measured_at: datetime | None,
        power_w: float | None,
        switch_state: str,
        set_switch: Callable[[bool], None],
        switch_changed_at: datetime | None = None,
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
            session = self.current(state)
            if session is None:
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
            if (
                session is not None
                and measured_at is not None
                and session.get("last_measured_at") is not None
                and measured_at < instant(session["last_measured_at"])
            ):
                fresh = False
            if session is not None:
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
                        if session.get("accepted_advice") and now < start
                        else True
                        if start <= now < end and not session.get("manual_pause")
                        else None
                    )
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
                            if last is None or (now - instant(last)).total_seconds() >= 10:
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

    def snapshot(self, *, storage_support_allowed: bool = True) -> Payload:
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
                    "session": recent,
                    "recognition": state.get("recognition"),
                    "storage_support_allowed": storage_support_allowed,
                }
            return {
                "contract": CONTRACT,
                "source_id": "energy-devices:ev-session",
                "power_entity_id": self.power_entity,
                "switch_entity_id": self.switch_entity,
                "revision": str(session["version"]),
                "generated_at": now.isoformat(),
                "session": session,
                "recognition": state.get("recognition"),
                "storage_support_allowed": storage_support_allowed
                and not bool(session.get("accepted_advice")),
            }
