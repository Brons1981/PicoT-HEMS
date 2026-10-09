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

    def action(self, payload: Payload) -> Payload:
        with self.lock:
            state = self.load()
            session = self.current(state)
            action = payload.get("action")
            if action == "verify_resume":
                if payload.get("confirmed") is not True:
                    raise ValueError("Bevestig eerst dat de auto na uit/aan werkelijk hervat")
                state["resume_verified"] = True
            elif action == "plan":
                if session is None or session["session_id"] != payload.get("session_id"):
                    raise ValueError("Herken eerst de aangesloten auto gedurende 30 seconden")
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
                high = fresh and power_w is not None and power_w >= 100 and switch_state == "on"
                if not high:
                    state.pop("recognition_start", None)
                    state.pop("recognition_samples", None)
                    state.pop("recognition_energy_wh", None)
                    state.pop("recognition_previous", None)
                else:
                    assert measured_at is not None and power_w is not None
                    state.setdefault("recognition_start", measured_at.isoformat())
                    samples = state.setdefault("recognition_samples", [])
                    previous = state.get("recognition_previous")
                    if previous and measured_at > instant(previous[0]):
                        elapsed = (measured_at - instant(previous[0])).total_seconds()
                        if elapsed <= 15:
                            state["recognition_energy_wh"] = (
                                state.get("recognition_energy_wh", 0)
                                + (previous[1] + power_w) / 2 * elapsed / 3600
                            )
                    state["recognition_previous"] = [measured_at.isoformat(), power_w]
                    samples.append(power_w)
                    del samples[:-60]
                    if (measured_at - instant(state["recognition_start"])).total_seconds() >= 30:
                        learned = [
                            s["delivered_energy_wh"]
                            for s in state["sessions"]
                            if s["state"] == "completed" and s.get("measurement_complete")
                        ]
                        session = {
                            "session_id": str(uuid4()),
                            "version": 1,
                            "state": "recognized",
                            "recognized_at": now.isoformat(),
                            "expected_power_w": median(samples),
                            "expected_duration_seconds": (
                                median(learned) * 3600 / median(samples) if learned else None
                            ),
                            "remaining_energy_wh": median(learned) if learned else None,
                            "delivered_energy_wh": state.get("recognition_energy_wh", 0.0),
                            "current_power_w": power_w,
                            "last_measured_at": measured_at.isoformat(),
                            "last_power_w": power_w,
                            "measurement_complete": True,
                            "confirmed": False,
                            "owns_switch": False,
                            "error": None,
                            "duration_source": "learned" if learned else "unknown",
                            "energy_source": "integrated_power",
                            "uncertainty": "duration_unknown"
                            if not learned
                            else "learned_estimate",
                            "recognition_samples": samples[-30:],
                        }
                        state["sessions"].append(session)
                        state["sessions"] = state["sessions"][-30:]
                        state.pop("recognition_start", None)
                        state.pop("recognition_samples", None)
            if (
                session is not None
                and measured_at is not None
                and measured_at < instant(session["last_measured_at"])
            ):
                fresh = False
            if session is not None:
                session["switch_state"] = switch_state
                session["current_power_w"] = power_w if fresh else None
                session["measurement_available"] = fresh
                if fresh:
                    assert measured_at is not None and power_w is not None
                    previous = instant(session["last_measured_at"])
                    elapsed = (measured_at - previous).total_seconds()
                    if 0 < elapsed <= 15:
                        energy = (session["last_power_w"] + power_w) / 2 * elapsed / 3600
                        session["delivered_energy_wh"] += energy
                    elif elapsed > 15:
                        session["measurement_complete"] = False
                    if elapsed > 0:
                        session["last_measured_at"] = measured_at.isoformat()
                        session["last_power_w"] = power_w
                    if session.get("confirmed"):
                        used = session["delivered_energy_wh"] - session["planned_delivered_base_wh"]
                        estimate = session["target_energy_wh"]
                        session["remaining_energy_wh"] = max(0.0, estimate - used)
                    if power_w >= 100:
                        session.pop("low_since", None)
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
                        else True
                        if start <= now < end and not session.get("manual_pause")
                        else None
                    )
                    if desired is not None:
                        if switch_state == ("on" if desired else "off"):
                            if not desired:
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
                            state["resume_verified"] and switch_state in {"on", "off"}
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
                "storage_support_allowed": storage_support_allowed,
            }
