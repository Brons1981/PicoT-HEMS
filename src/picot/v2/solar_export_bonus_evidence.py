"""Persist raw export allowance evidence, separately from financial estimates."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from picot.domain.solar_export_bonus import SolarExportBonusContext, SolarExportBonusPolicy
from picot.v2.power_history import PowerHistorySeries, PowerHistorySnapshot


def _integrate(series: PowerHistorySeries, start: datetime, end: datetime) -> float | None:
    points = sorted(series.points, key=lambda p: p.sampled_at)
    held = next((p for p in reversed(points) if p.sampled_at <= start), None)
    if held is None or series.history_semantics != "state_hold":
        return None
    cursor = start
    total = 0.0
    for point in [p for p in points if start < p.sampled_at < end]:
        if not isfinite(held.power_w) or held.power_w < 0:
            return None
        total += held.power_w * (point.sampled_at - cursor).total_seconds() / 3_600_000
        cursor, held = point.sampled_at, point
    if not isfinite(held.power_w) or held.power_w < 0:
        return None
    return total + held.power_w * (end - cursor).total_seconds() / 3_600_000


class SolarExportBonusEvidence:
    """Never reads inferred financial amounts; only raw HA state-held grid power."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = RLock()
        try:
            if path.is_file() and path.stat().st_size > 4_000_000:
                raise ValueError("bonus evidence exceeds bounded history")
            loaded = json.loads(path.read_text()) if path.is_file() else {}
            if not isinstance(loaded, dict):
                raise ValueError("invalid bonus evidence")
            archives = loaded.get("archives", [])
            if not isinstance(archives, list) or len(archives) > 128:
                raise ValueError("invalid bonus policy history")
            if any(not isinstance(item, dict) or not item.get("policy") for item in archives):
                raise ValueError("bonus policy archive is missing identity")
            for version in [loaded, *archives]:
                if not isinstance(version, dict):
                    raise ValueError("invalid bonus policy version")
                policy = None
                if version.get("policy"):
                    values = json.loads(version["policy"])
                    values["effective_from"] = datetime.fromisoformat(values["effective_from"])
                    if values["annual_exported_at"] is not None:
                        values["annual_exported_at"] = datetime.fromisoformat(
                            values["annual_exported_at"]
                        )
                    policy = SolarExportBonusPolicy(**values)
                if policy is not None and policy.annual_exported_at is not None:
                    # A matching policy identity alone is not evidence. All
                    # counters must belong to that explicit annual anchor.
                    cursor = datetime.fromisoformat(version["cursor"])
                    used = version["exported_kwh"]
                    openings = version["openings"]
                    if (
                        cursor.utcoffset() is None
                        or cursor < policy.annual_exported_at
                        or isinstance(used, bool)
                        or not isinstance(used, (int, float))
                        or not isfinite(used)
                        or used < 0
                        or not isinstance(openings, dict)
                    ):
                        raise ValueError("invalid anchored export observations")
                    tz = ZoneInfo(policy.timezone_name)
                    year = cursor.astimezone(tz).year
                    if year == policy.annual_exported_at.astimezone(tz).year:
                        if used < (policy.annual_exported_kwh or 0):
                            raise ValueError("annual export counter precedes baseline")
                    else:
                        january = datetime(year, 1, 1, tzinfo=tz).astimezone(UTC).isoformat()
                        if openings.get(january) != 0:
                            raise ValueError("annual export reset lacks raw opening evidence")
                source = version.get("source_entity_id", "")
                evidence_ids = version.get("source_evidence_ids", [])
                if (
                    not isinstance(source, str)
                    or not isinstance(evidence_ids, list)
                    or not all(isinstance(item, str) for item in evidence_ids)
                ):
                    raise ValueError("invalid raw export provenance")
                if version.get("cursor"):
                    if datetime.fromisoformat(version["cursor"]).utcoffset() is None:
                        raise ValueError("invalid export observation time")
                    used = float(version["exported_kwh"])
                    if not isfinite(used) or used < 0:
                        raise ValueError("invalid annual exported energy")
                openings = version.get("openings", {})
                if not isinstance(openings, dict) or len(openings) > 800:
                    raise ValueError("invalid export opening observations")
                for at, energy in openings.items():
                    if (
                        datetime.fromisoformat(at).utcoffset() is None
                        or not isfinite(float(energy))
                        or float(energy) < 0
                    ):
                        raise ValueError("invalid export opening observation")
            self.state: dict[str, Any] = loaded
        except (OSError, ValueError, TypeError, KeyError):
            # Missing evidence cannot stop the ordinary battery plan. Configure
            # re-establishes only the explicit baseline; unknown elapsed export
            # remains a coverage gap until raw history proves it.
            self.state = {}
        self.policy: SolarExportBonusPolicy | None = None

    def configure(self, policy: SolarExportBonusPolicy | None) -> None:
        with self.lock:
            self.policy = policy
            if policy is None:
                return
            identity = json.dumps(asdict(policy), default=str, sort_keys=True)
            if self.state.get("policy") != identity:
                previous = self.state
                archives = list(previous.get("archives", []))
                if previous.get("policy"):
                    archives.append({k: v for k, v in previous.items() if k != "archives"})
                archives = archives[-128:]
                self.state = {"policy": identity, "openings": {}, "archives": archives}
                old = json.loads(previous["policy"]) if previous.get("policy") else {}
                if (
                    old.get("annual_exported_at") == str(policy.annual_exported_at)
                    and old.get("annual_exported_kwh") == policy.annual_exported_kwh
                ):
                    for key in ("cursor", "exported_kwh", "openings", "source_entity_id"):
                        if key in previous:
                            self.state[key] = previous[key]
                elif policy.annual_exported_at is not None:
                    self.state.update(
                        cursor=policy.annual_exported_at.isoformat(),
                        exported_kwh=policy.annual_exported_kwh,
                    )
                self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".writing")
        temp.write_text(json.dumps(self.state, separators=(",", ":")), encoding="utf-8")
        temp.replace(self.path)

    def observe(self, history: PowerHistorySnapshot) -> None:
        with self.lock:
            policy = self.policy
            if (
                policy is None
                or policy.annual_exported_at is None
                or history.method_version != "home-assistant-power-history:v1"
                or history.status != "available"
                or history.error is not None
            ):
                return
            series = [s for s in history.series if s.role == "grid_export"]
            if (
                len(series) != 1
                or not series[0].source_entity_id
                or any(p.evidence_id.startswith("financial:") for p in series[0].points)
            ):
                return
            cursor = datetime.fromisoformat(self.state["cursor"])
            tz = ZoneInfo(policy.timezone_name)
            year_start = datetime(history.ends_at.astimezone(tz).year, 1, 1, tzinfo=tz)
            if cursor < year_start and history.starts_at <= year_start <= history.ends_at:
                # The new calendar-year allowance is known independently of a
                # missing final observation in the previous year.
                cursor = year_start
                self.state["cursor"] = cursor.isoformat()
                self.state["exported_kwh"] = 0.0
                self.state["openings"][cursor.astimezone(UTC).isoformat()] = 0.0
            if history.starts_at > cursor or history.ends_at <= cursor:
                return
            while cursor < history.ends_at:
                midnight = datetime.combine(
                    cursor.astimezone(tz).date() + timedelta(days=1), time(), tz
                )
                end = min(midnight, history.ends_at)
                if cursor < policy.effective_from < end:
                    end = policy.effective_from
                energy = _integrate(series[0], cursor, end)
                if energy is None:
                    return
                self.state["exported_kwh"] += energy
                cursor = end
                self.state["cursor"] = cursor.isoformat()
                if end == midnight or end == policy.effective_from:
                    if end.astimezone(tz).year != (end - timedelta(seconds=1)).astimezone(tz).year:
                        self.state["exported_kwh"] = 0.0
                    self.state["openings"][end.astimezone(UTC).isoformat()] = self.state[
                        "exported_kwh"
                    ]
                self.state["source_entity_id"] = series[0].source_entity_id
                self.state["source_evidence_ids"] = [p.evidence_id for p in series[0].points[-2:]]
                openings = self.state["openings"]
                self.state["openings"] = {key: openings[key] for key in sorted(openings)[-800:]}
            self._save()

    def context(
        self,
        at: datetime,
        history: PowerHistorySnapshot | None = None,
        maximum_unobserved_export_power_w: float | None = None,
    ) -> SolarExportBonusContext | None:
        if history is not None:
            self.observe(history)
        with self.lock:
            policy = self.policy
            if policy is None:
                return None
            if at < policy.effective_from:
                for archive in reversed(self.state.get("archives", [])):
                    values = json.loads(archive["policy"])
                    values["effective_from"] = datetime.fromisoformat(values["effective_from"])
                    if values["annual_exported_at"] is not None:
                        values["annual_exported_at"] = datetime.fromisoformat(
                            values["annual_exported_at"]
                        )
                    if values["effective_from"] <= at:
                        current_state, current_policy = self.state, self.policy
                        try:
                            self.state, self.policy = archive, SolarExportBonusPolicy(**values)
                            return self.context(
                                at,
                                maximum_unobserved_export_power_w=maximum_unobserved_export_power_w,
                            )
                        finally:
                            self.state, self.policy = current_state, current_policy
            evidence: tuple[str, ...] = ("solar-export-bonus:configured-supplier-policy",)
            if not policy.enabled:
                return SolarExportBonusContext(policy, at, (), evidence, "disabled")
            if policy.annual_exported_at is None or policy.annual_exported_kwh is None:
                return SolarExportBonusContext(
                    policy, at, (), evidence, "unavailable", "annual_export_baseline_missing"
                )
            anchor = policy.annual_exported_at
            cursor = datetime.fromisoformat(self.state["cursor"])
            tz = ZoneInfo(policy.timezone_name)
            reason = None
            observed = cursor
            if at <= anchor:
                used = policy.annual_exported_kwh
                year = anchor.astimezone(tz).year
                observed = anchor
            elif at == cursor:
                used = float(self.state["exported_kwh"])
                year = at.astimezone(tz).year
            elif at.astimezone(UTC).isoformat() in self.state["openings"]:
                used = float(self.state["openings"][at.astimezone(UTC).isoformat()])
                year = at.astimezone(tz).year
                observed = at
            elif (
                at > cursor
                and at - cursor <= timedelta(days=1)
                and maximum_unobserved_export_power_w is not None
                and isfinite(maximum_unobserved_export_power_w)
                and maximum_unobserved_export_power_w >= 0
                and at.astimezone(tz).year == cursor.astimezone(tz).year
            ):
                used = float(self.state["exported_kwh"]) + (
                    maximum_unobserved_export_power_w * (at - cursor).total_seconds() / 3_600_000
                )
                year = at.astimezone(tz).year
                reason = "bounded_unobserved_export"
            else:
                return SolarExportBonusContext(
                    policy,
                    observed,
                    (),
                    evidence,
                    "unavailable",
                    "annual_export_coverage_incomplete",
                )
            evidence += (
                "annual-export-baseline:" + anchor.isoformat(),
                "raw-export-observed-through:" + observed.isoformat(),
            )
            if self.state.get("source_entity_id"):
                evidence += ("raw-export-source:" + self.state["source_entity_id"],)
                evidence += tuple(self.state.get("source_evidence_ids", []))
            if reason:
                evidence += (reason,)
            return SolarExportBonusContext(
                policy, observed, ((year, max(0.0, 7500.0 - used)),), evidence, reason=reason
            )

    def policy_boundaries(self, start: datetime, end: datetime) -> tuple[datetime, ...]:
        with self.lock:
            versions = [*self.state.get("archives", []), self.state]
            return tuple(
                sorted(
                    {
                        datetime.fromisoformat(json.loads(v["policy"])["effective_from"])
                        for v in versions
                        if v.get("policy")
                        and start
                        < datetime.fromisoformat(json.loads(v["policy"])["effective_from"])
                        < end
                    }
                )
            )
