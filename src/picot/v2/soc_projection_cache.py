"""Bounded persistence of an original canonical SOC curve, for display only."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

# Display cut points can contain two source-labelled endpoints per update.
MAX_CACHE_BYTES = 8_000_000
MAX_HISTORY_BYTES = 32_000_000
MAX_POINTS = 4096
IDENTITY_KEYS = ("plan_id", "candidate_id", "energy_path_id", "valid_from", "valid_until")


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("timestamp must have timezone")
    return result


def _validate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported SOC projection")
    identity = value.get("identity")
    if not isinstance(identity, dict) or any(
        not isinstance(identity.get(k), str) or not identity[k] for k in IDENTITY_KEYS
    ):
        raise ValueError("incomplete projection identity")
    captured = _time(value.get("captured_at"))
    valid_until = _time(identity["valid_until"])
    if captured >= valid_until or _time(identity["valid_from"]) >= valid_until:
        raise ValueError("invalid projection validity")
    points = value.get("soc_timeline")
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        raise ValueError("invalid curve length")
    previous = None
    for point in points:
        if not isinstance(point, dict):
            raise ValueError("invalid point")
        at = _time(point.get("at"))
        soc = point.get("soc_percent")
        if (
            at < captured or at > valid_until or (previous is not None and at <= previous)
            or isinstance(soc, bool) or not isinstance(soc, (float, int))
            or not isfinite(soc) or not 0 <= soc <= 100
            or not isinstance(point.get("primitive"), str)
        ):
            raise ValueError("invalid curve point")
        previous = at
    return {**value, "identity": {
        **identity, "valid_from": _time(identity["valid_from"]).astimezone(UTC).isoformat(),
        "valid_until": valid_until.astimezone(UTC).isoformat(),
    }}


class SOCProjectionCache:
    """Never feeds simulation, evaluation, commitments or execution."""

    def __init__(self, path: Path, *, history_path: Path | None = None) -> None:
        self.path = path
        self.history_path = history_path
        self.status = "empty"
        self._projection: dict[str, Any] | None = None
        self._history_checked = False
        self.display_history = SOCDisplayHistory()
        try:
            with path.open("rb") as source:
                raw = source.read(MAX_CACHE_BYTES + 1)
            if len(raw) > MAX_CACHE_BYTES:
                raise ValueError("SOC cache too large")
            self._projection = _validate(json.loads(raw))
            try:
                self.display_history.load(self._projection.pop("display_history", None))
            except (ValueError, TypeError, KeyError):
                pass
            self.status = "loaded"
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            self.status = "cache_unavailable"

    def remember(self, status: dict[str, Any]) -> None:
        try:
            plan = status.get("chosen_plan") or {}
            value = _validate({
                "schema_version": 1,
                "identity": {k: plan.get(k) for k in IDENTITY_KEYS},
                "captured_at": status.get("soc_projection_captured_at"),
                "soc_timeline": status.get("soc_timeline"),
            })
            if value == self._projection:
                return
            self._projection = value
            self._save()
        except (OSError, ValueError, TypeError):
            self.status = "cache_unavailable"

    def _save(self) -> None:
        if self._projection is not None:
            value = {**self._projection, "display_history": self.display_history.value}
            encoded = json.dumps(value, separators=(",", ":"), allow_nan=False)
            if len(encoded.encode()) > MAX_CACHE_BYTES:
                raise ValueError("SOC cache too large")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(self.path)
            self.status = "saved"

    def display(self, status: dict[str, Any]) -> dict[str, Any]:
        before = self.display_history.value
        result = self.display_history.apply(status)
        if self.display_history.value["points"] != before["points"]:
            try:
                self._save()
            except (OSError, ValueError, TypeError):
                self.status = "cache_unavailable"
        return result

    def restore(self, status: dict[str, Any]) -> dict[str, Any] | None:
        plan = status.get("chosen_plan") or {}
        if not isinstance(plan, dict):
            return None
        identity = {k: plan.get(k) for k in IDENTITY_KEYS}
        try:
            identity["valid_from"] = _time(identity.get("valid_from")).astimezone(UTC).isoformat()
            identity["valid_until"] = _time(identity.get("valid_until")).astimezone(UTC).isoformat()
            now = _time(status.get("captured_at"))
            if now >= _time(identity.get("valid_until")):
                return None
            if not self._history_checked and (
                self._projection is None or self._projection["identity"] != identity
            ):
                self._history_checked = True
                recovered = self._from_history(identity)
                if recovered is not None:
                    self.remember({
                        "chosen_plan": identity,
                        "soc_projection_captured_at": recovered["captured_at"],
                        "soc_timeline": recovered["soc_timeline"],
                    })
            value = self._projection
            if (value is not None and value["identity"] == identity
                    and _time(value["captured_at"]) <= now
                    and _time(value["soc_timeline"][-1]["at"]) > now):
                return {
                    **status, "soc_timeline": value["soc_timeline"],
                    "soc_projection_captured_at": value["captured_at"],
                    "soc_projection_retained": True,
                }
        except (OSError, ValueError, TypeError, KeyError):
            self.status = "history_unavailable"
        return None

    def _from_history(self, identity: dict[str, Any]) -> dict[str, Any] | None:
        if self.history_path is None:
            return None
        found = None
        with self.history_path.open("rb") as source:
            size = source.seek(0, 2)
            offset = max(0, size - MAX_HISTORY_BYTES)
            source.seek(offset)
            if offset:
                source.readline(MAX_HISTORY_BYTES)
            # Only inspect the tail present at open, never chase live appends.
            remaining = size - source.tell()
            while remaining > 0:
                line = source.readline(min(remaining, 8_000_001))
                if not line:
                    break
                remaining -= len(line)
                if len(line) > 8_000_000:
                    return found
                try:
                    poll = json.loads(line).get("poll", {})
                    value = _historical_projection(poll, identity)
                    if value is not None:
                        found = value
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue
        return found


def _historical_projection(poll: Any, identity: dict[str, Any]) -> dict[str, Any] | None:
    evaluation = poll.get("evaluation", {})
    if (evaluation.get("status") != "winner_selected"
            or evaluation.get("winning_candidate_id") != identity["candidate_id"]
            or evaluation.get("winning_energy_path_id") != identity["energy_path_id"]):
        return None
    plans = poll.get("execution_plan_set", {}).get("plans", [])
    if not any(
        p.get("plan_id") == identity["plan_id"]
        and p.get("winning_candidate_id") == identity["candidate_id"]
        and p.get("winning_energy_path_id") == identity["energy_path_id"]
        and _time(p.get("valid_from")) == _time(identity["valid_from"])
        and _time(p.get("valid_until")) == _time(identity["valid_until"])
        for p in plans
    ):
        return None
    path = next((p for p in poll["candidate_set"]["energy_paths"]
                 if p.get("path_id") == identity["energy_path_id"]
                 and p.get("snapshot_id") == poll.get("snapshot_id")
                 and p.get("run_id") == poll.get("run_id")), None)
    if path is None:
        return None
    captured = _time(poll["captured_at_utc"])
    points = []
    for state in path["projected_states"]:
        at = _time(state["at"])
        soc = state.get("battery_soc")
        if at < captured or soc is None:
            continue
        if isinstance(soc, bool) or not isinstance(soc, (int, float)):
            raise ValueError("invalid projected SOC")
        segment = next((s for s in path["segments"]
                        if _time(s["starts_at"]) < at <= _time(s["ends_at"])), None)
        points.append({
            "at": state["at"], "soc_percent": round(soc * 100, 2),
            "primitive": ("actual" if at == captured else
                          segment["primitive"] if segment else "projected"),
        })
    return _validate({"schema_version": 1, "identity": identity,
                      "captured_at": poll["captured_at_utc"], "soc_timeline": points})


class SOCDisplayHistory:
    """Rolling display points only; canonical curves retain their own identity."""

    def __init__(self) -> None:
        self.value: dict[str, Any] = {"updated_at": None, "points": []}

    def load(self, value: Any) -> None:
        if value is None:
            return
        updated = _time(value["updated_at"])
        points = value["points"]
        if not isinstance(points, list) or len(points) > MAX_POINTS:
            raise ValueError("invalid display history")
        previous = None
        for point in points:
            at = _time(point["at"])
            soc = point["soc_percent"]
            if (previous is not None and (at < previous or (
                    at == previous and point.get("break_before") is not True))
                    or isinstance(soc, bool) or not isinstance(soc, (int, float))
                    or not isfinite(soc) or not 0 <= soc <= 100
                    or not isinstance(point.get("primitive"), str)
                    or not isinstance(point.get("source_identity"), dict)):
                raise ValueError("invalid display point")
            previous = at
        self.value = {"updated_at": updated.isoformat(), "points": points}

    def apply(self, status: dict[str, Any]) -> dict[str, Any]:
        try:
            now = _time(status.get("captured_at"))
            if self.value["updated_at"] and now < _time(self.value["updated_at"]):
                return status
            cutoff = now - timedelta(hours=48)
            old = self.value["points"]
            timeline = status.get("soc_timeline") or []
            active = (status.get("decision") or {}).get("status") in {
                "winner_selected", "plan_retained",
            }
            if active and timeline:
                plan = status.get("chosen_plan") or {}
                identity = {key: plan.get(key) for key in IDENTITY_KEYS}
                sourced = [{**p, "source_identity": identity,
                            "source_captured_at": status.get("soc_projection_captured_at")}
                           for p in timeline]
                if self.value["updated_at"] is None:
                    old = sourced
                future = [p for p in sourced if _time(p["at"]) >= now]
                start = _display_boundary(sourced, now)
                if start is not None and (not future or _time(future[0]["at"]) > now):
                    future.insert(0, start)
            else:
                # Keep history, but never show a stale future during fallback.
                future = []
            past = [p for p in old if cutoff <= _time(p["at"]) < now]
            boundary = _display_boundary(old, now)
            if boundary is not None and past:
                past.append(boundary)
            if past and future:
                # The new forecast starts its own stroke. Connecting to its
                # measured anchor would change the already elapsed old stroke.
                future[0] = {**future[0], "break_before": True}
            points = (past + future)[-MAX_POINTS:]
            value = {"updated_at": now.isoformat(), "points": points}
            self.load(value)
            return {**status, "soc_display_timeline": points}
        except (ValueError, TypeError, KeyError):
            return status


def _display_boundary(points: list[dict[str, Any]], at: datetime) -> dict[str, Any] | None:
    """Clip the existing SVG polyline, never simulate a new energy state."""
    for index, point in enumerate(points):
        right = _time(point["at"])
        if right == at:
            return dict(point)
        if right > at:
            if index == 0 or point.get("break_before") is True:
                return None
            previous = points[index - 1]
            left = _time(previous["at"])
            fraction = (at - left).total_seconds() / (right - left).total_seconds()
            return {**point, "at": at.isoformat(), "soc_percent": (
                previous["soc_percent"]
                + fraction * (point["soc_percent"] - previous["soc_percent"])
            ), "display_interpolated": True}
    return None
