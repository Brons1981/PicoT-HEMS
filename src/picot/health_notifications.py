"""Durable, asynchronous Home Assistant health events; no control authority."""

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Condition, Thread
from urllib.request import Request, urlopen


class HealthNotifier:
    def __init__(self, token: str, app: str, path: Path, *, enabled: bool = True,
                 recovery_enabled: bool = True) -> None:
        self.token, self.app, self.path = token, app, path
        self.enabled = enabled and bool(token)
        self.recovery_enabled = recovery_enabled
        self._condition = Condition()
        self._stopped = False
        self._active: dict[str, bool] = {}
        self._fingerprints: dict[str, str] = {}
        self._pending: list[dict[str, object]] = []
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            self._active = saved["active"]
            self._pending = saved["pending"]
            self._fingerprints = saved.get("fingerprints", {})
            if (not isinstance(self._active, dict) or not isinstance(self._pending, list)
                    or not isinstance(self._fingerprints, dict)):
                raise ValueError("Invalid notification state")
        except (OSError, ValueError, KeyError, TypeError):
            self._active, self._pending, self._fingerprints = {}, [], {}
        self._thread = Thread(target=self._run, name=f"{app}-health-events", daemon=True)
        if self.enabled:
            self._thread.start()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"active": self._active, "pending": self._pending,
                                             "fingerprints": self._fingerprints}),
                                 encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            pass  # Notification storage must never interrupt control.

    def observe(self, key: str, active: bool, message: str, *, severity: str = "warning",
                fingerprint: str | None = None) -> None:
        if not self.enabled:
            return
        with self._condition:
            if self._active.get(key, False) == active and (
                not active or fingerprint is None or self._fingerprints.get(key) == fingerprint
            ):
                return
            self._active[key] = active
            if active and fingerprint is not None:
                self._fingerprints[key] = fingerprint
            elif not active:
                self._fingerprints.pop(key, None)
            if active or self.recovery_enabled:
                self._pending.append({
                    "app": self.app, "key": key, "active": active, "message": message,
                    "title": f"PicoT {self.app} — {'storing / terugval' if active else 'hersteld'}",
                    "severity": severity if active else "info",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "tag": f"picot_{self.app}_{key}",
                })
            self._save()
            self._condition.notify()

    def _send(self, event: dict[str, object]) -> None:
        request = Request("http://supervisor/core/api/events/picot_health_alert",
                          data=json.dumps(event).encode(), method="POST",
                          headers={"Authorization": f"Bearer {self.token}",
                                   "Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            response.read()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopped:
                    self._condition.wait()
                if self._stopped:
                    return
                event = self._pending[0]
            try:
                self._send(event)
            except Exception:
                with self._condition:
                    if not self._stopped:
                        self._condition.wait(timeout=30)
                continue
            with self._condition:
                self._pending.pop(0)
                self._save()

    def close(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
