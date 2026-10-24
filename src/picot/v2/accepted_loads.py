"""Approved profiles with expiring HC reservations and confirmed execution."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

from picot.v2.contracts import HouseholdLoadForecastInterval
from picot.v2.energy_portfolio import fingerprint, instant
from picot.v2.load_replacement import LoadReplacementBasis, _forecast_digest

if TYPE_CHECKING:
    from picot.v2.planning_input import PlanningInputBundle


class _Profile(TypedDict):
    source_id: str
    modeled_source_id: str | None
    start: datetime
    end: datetime
    power: float


RESERVATION_ENTITY = "sensor.picot_hc_energy_reservation"
EXECUTION_ENTITY = "sensor.picot_hc_energy_execution"
DEFAULT_PATH = Path("/data/picot_v2_accepted_loads.sqlite")


def key(value: dict[str, Any]) -> str:
    return fingerprint({k: value[k] for k in ("request_fingerprint", "selected_plan_id")})


class AcceptedLoads:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS issued "
                "(id TEXT PRIMARY KEY, created REAL, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution "
                "(source TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

            db.execute(
                "CREATE TABLE IF NOT EXISTS reservations "
                "(source TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def issue(
        self,
        request: dict[str, Any],
        selection: dict[str, Any],
        basis: LoadReplacementBasis | None,
        now: datetime,
        *,
        reservation_only: bool = False,
        terminal_requirement: dict[str, Any] | None = None,
    ) -> None:
        """Called after validate_selection; failure must prevent publishing a permit."""
        if (
            basis is None
            or request.get("contract") != "hc-energy-proposals:v2"
            or request["replacement_basis_id"] != basis.basis_id
            or request["basis_snapshot_id"] != basis.snapshot_id
            or request.get("modeled_source_id") != basis.modeled_source_id
            or selection["request_fingerprint"] != fingerprint(request)
        ):
            raise ValueError("approved_profile_basis_missing")
        plan = next(p for p in request["plans"] if p["plan_id"] == selection["selected_plan_id"])
        record = dict(
            selection=selection,
            source_id=basis.source_id,
            modeled_source_id=basis.modeled_source_id,
            slots=plan["slots"],
            id=key(selection),
            reservation_only=reservation_only,
            terminal_requirement=terminal_requirement,
        )
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO issued VALUES (?, ?, ?)",
                (record["id"], now.timestamp(), json.dumps(record, allow_nan=False)),
            )
            db.execute(
                "DELETE FROM issued WHERE created < ?", ((now - timedelta(days=7)).timestamp(),)
            )

    def reserve(self, value: object, now: datetime) -> bool:
        """Renew only HC's explicit intent; never grant or extend start permission."""
        if not isinstance(value, dict) or set(value) != {
            "contract",
            "request_id",
            "request_fingerprint",
            "selected_plan_id",
            "reported_at",
            "valid_until",
            "status",
        }:
            return False
        try:
            reported, until = instant(value["reported_at"]), instant(value["valid_until"])
            if (
                value["contract"] != "hc-energy-reservation:v1"
                or value["status"] not in ("reserved", "cancelled")
                or not reported <= now < until <= reported + timedelta(seconds=120)
            ):
                return False
            with self.connect() as db:
                row = db.execute("SELECT payload FROM issued WHERE id=?", (key(value),)).fetchone()
                if not row:
                    return False
                approved = json.loads(row[0])
                if (
                    value["request_id"] != approved["selection"]["request_id"]
                    or reported < instant(approved["selection"]["generated_at"])
                    or now >= instant(approved["slots"][-1]["ends_at"])
                ):
                    return False
                previous = db.execute(
                    "SELECT payload FROM reservations WHERE source=?", (approved["source_id"],)
                ).fetchone()
                if previous:
                    old = json.loads(previous[0])
                    if (
                        reported <= instant(old["reported_at"])
                        or old["id"] == approved["id"]
                        and old["status"] == "cancelled"
                        or old["id"] != approved["id"]
                        and instant(approved["selection"]["generated_at"])
                        <= instant(old["selection"]["generated_at"])
                    ):
                        return False
                execution = db.execute(
                    "SELECT payload FROM execution WHERE source=?", (approved["source_id"],)
                ).fetchone()
                if execution:
                    executed = json.loads(execution[0])
                    if (
                        executed["id"] == approved["id"]
                        or instant(approved["selection"]["generated_at"])
                        <= instant(executed["executed_at"])
                        or executed["status"] == "running"
                        and now < instant(executed["slots"][-1]["ends_at"])
                    ):
                        return False
                record = dict(
                    approved,
                    reported_at=value["reported_at"],
                    valid_until=value["valid_until"],
                    status=value["status"],
                )
                db.execute(
                    "INSERT OR REPLACE INTO reservations VALUES (?, ?)",
                    (approved["source_id"], json.dumps(record, allow_nan=False)),
                )
            return True
        except (KeyError, TypeError, ValueError):
            return False

    def profiles(self, now: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # Read both tables in one SQLite snapshot: a start must not disappear or
        # count twice while the background observer confirms its execution.
        with self.connect() as db:
            db.execute("BEGIN")
            executions = {
                r[0]: json.loads(r[1]) for r in db.execute("SELECT source, payload FROM execution")
            }
            values = [json.loads(r[0]) for r in db.execute("SELECT payload FROM reservations")]
        running = [
            v
            for v in executions.values()
            if v["status"] == "running"
            and instant(v["executed_at"]) <= now < instant(v["slots"][-1]["ends_at"])
        ]
        planned = []
        for value in values:
            executed = executions.get(value["source_id"])
            if executed and (
                executed["id"] == value["id"]
                or instant(executed["executed_at"]) >= instant(value["selection"]["generated_at"])
                or executed["status"] == "running"
                and now < instant(executed["slots"][-1]["ends_at"])
            ):
                continue
            if value["status"] == "reserved" and instant(value["reported_at"]) <= now < min(
                instant(value["valid_until"]), instant(value["slots"][-1]["ends_at"])
            ):
                planned.append(value)
        return running, planned

    def planned(self, now: datetime) -> list[dict[str, Any]]:
        return self.profiles(now)[1]

    def terminal_requirement(self, source_id: str, now: datetime) -> dict[str, Any] | None:
        """Carry the original comparison floor across reservation and replanning."""
        records = [r for r in self.planned(now) if r["source_id"] == source_id]
        return (
            cast(dict[str, Any] | None, records[0].get("terminal_requirement")) if records else None
        )

    def observe(self, value: object, now: datetime) -> bool:
        """A late receipt may confirm an earlier valid start; expired permission is not renewed."""
        if not isinstance(value, dict) or set(value) != {
            "contract",
            "request_id",
            "request_fingerprint",
            "selected_plan_id",
            "executed_at",
            "reported_at",
            "status",
        }:
            return False
        try:
            executed, reported = instant(value["executed_at"]), instant(value["reported_at"])
            if (
                value["contract"] != "hc-energy-execution:v1"
                or value["status"] not in ("running", "finished")
                or not executed <= reported <= now
                or now - reported > timedelta(seconds=120)
            ):
                return False
            with self.connect() as db:
                row = db.execute("SELECT payload FROM issued WHERE id=?", (key(value),)).fetchone()
                if not row:
                    return False
                approved = json.loads(row[0])
                selection = approved["selection"]
                if (
                    approved.get("reservation_only", False)
                    or value["request_id"] != selection["request_id"]
                    or not instant(selection["generated_at"])
                    <= executed
                    < instant(selection["valid_until"])
                    or not instant(approved["slots"][0]["starts_at"])
                    <= executed
                    < instant(approved["slots"][-1]["ends_at"])
                ):
                    return False
                previous = db.execute(
                    "SELECT payload FROM execution WHERE source=?", (approved["source_id"],)
                ).fetchone()
                if previous:
                    old = json.loads(previous[0])
                    if old["id"] == approved["id"]:
                        if (
                            old["executed_at"] != value["executed_at"]
                            or old["status"] == "finished"
                            or instant(old["reported_at"]) >= reported
                        ):
                            return False
                    elif instant(old["executed_at"]) >= executed:
                        return False
                active = dict(
                    approved,
                    executed_at=value["executed_at"],
                    reported_at=value["reported_at"],
                    status=value["status"],
                )
                db.execute(
                    "INSERT OR REPLACE INTO execution VALUES (?, ?)",
                    (approved["source_id"], json.dumps(active, allow_nan=False)),
                )
            return True
        except (KeyError, TypeError, ValueError, StopIteration):
            return False

    def active(self, now: datetime) -> list[dict[str, Any]]:
        return self.profiles(now)[0]

    def apply(self, bundle: PlanningInputBundle) -> PlanningInputBundle:
        """Apply once to fresh measured input, never to the observation/history itself."""
        summary = dict(bundle.controlled_load_summary or {})
        if summary.get("accepted_loads_applied"):
            return bundle
        snapshot = bundle.snapshot
        running, planned = self.profiles(snapshot.captured_at)
        records = running + planned
        if not records:
            return bundle
        forecast, basis = snapshot.household_load_forecast, bundle.load_replacement_basis
        if forecast is None:
            raise ValueError("accepted_load_requires_household_forecast")
        usable = basis is not None and basis.matches(snapshot)
        profiles: list[_Profile] = [
            _Profile(
                source_id=r["source_id"],
                modeled_source_id=r.get("modeled_source_id"),
                start=max(instant(s["starts_at"]), snapshot.captured_at),
                end=instant(s["ends_at"]),
                power=float(s["energy_wh"])
                / (instant(s["ends_at"]) - instant(s["starts_at"])).total_seconds(),
            )
            for r in records
            for s in r["slots"]
            if instant(s["ends_at"]) > snapshot.captured_at
        ]
        boundaries = {p[t] for p in profiles for t in ("start", "end")}
        if usable and basis is not None:
            boundaries.update((basis.starts_at, basis.ends_at))
            boundaries.update(t for i in basis.component for t in (i.starts_at, i.ends_at))
        rows: list[HouseholdLoadForecastInterval] = []
        components: list[HouseholdLoadForecastInterval] = []
        added, removed, conservative = 0.0, 0.0, False
        rebasable = (
            not running
            and len(planned) == 1
            and usable
            and basis is not None
            and planned[0]["source_id"] == basis.source_id
            and planned[0].get("modeled_source_id") == basis.modeled_source_id
        )
        for item in forecast.intervals:
            edges = sorted(
                {item.starts_at, item.ends_at}
                | {t for t in boundaries if item.starts_at < t < item.ends_at}
            )
            for left, right in zip(edges, edges[1:], strict=False):
                fraction = (right - left) / (item.ends_at - item.starts_at)
                energy, excluded = (
                    item.expected_energy_wh * fraction,
                    item.battery_excluded_energy_wh * fraction,
                )
                covering = [p for p in profiles if p["start"] <= left and right <= p["end"]]
                increment = sum(p["power"] * (right - left).total_seconds() for p in covering)
                subtract = 0.0
                replaced = False
                if covering:
                    prior = (
                        next(
                            (
                                i
                                for i in basis.component
                                if i.starts_at <= left and right <= i.ends_at
                            ),
                            None,
                        )
                        if usable and basis is not None
                        else None
                    )
                    if (
                        prior is not None
                        and basis is not None
                        and basis.starts_at <= left
                        and right <= basis.ends_at
                        and any(
                            p["source_id"] == basis.source_id
                            and p["modeled_source_id"] == basis.modeled_source_id
                            for p in covering
                        )
                    ):
                        candidate = (
                            prior.expected_energy_wh
                            * (right - left)
                            / (prior.ends_at - prior.starts_at)
                        )
                        if candidate <= energy - excluded + 1e-6:
                            subtract = min(candidate, energy - excluded)
                            replaced = True
                    conservative |= not replaced and increment > 0
                if rebasable and basis is not None:
                    prior_component = next(
                        (i for i in basis.component if i.starts_at <= left and right <= i.ends_at),
                        None,
                    )
                    if prior_component is None and basis.starts_at <= left < basis.ends_at:
                        rebasable = False
                    attributed = (
                        (
                            prior_component.expected_energy_wh
                            * (right - left)
                            / (prior_component.ends_at - prior_component.starts_at)
                        )
                        if prior_component
                        else 0
                    )
                    component_energy = attributed - subtract + increment
                    if component_energy > energy - subtract + increment - excluded + 1e-6:
                        rebasable = False
                    components.append(
                        replace(
                            item,
                            starts_at=left,
                            ends_at=right,
                            expected_energy_wh=max(0, component_energy),
                            battery_excluded_energy_wh=0,
                        )
                    )
                added += increment
                removed += subtract
                identity = fingerprint(
                    dict(
                        base=item.interval_id,
                        start=left.isoformat(),
                        end=right.isoformat(),
                        energy=energy - subtract + increment,
                    )
                )[:16]
                rows.append(
                    replace(
                        item,
                        interval_id="accepted-" + identity,
                        starts_at=left,
                        ends_at=right,
                        expected_energy_wh=energy - subtract + increment,
                        battery_excluded_energy_wh=excluded,
                    )
                )
        signature = fingerprint({"profiles": sorted(r["id"] for r in records)})
        updated = replace(
            forecast,
            forecast_id="accepted-" + fingerprint({"rows": [r.interval_id for r in rows]})[:16],
            intervals=tuple(rows),
        )
        summary.update(
            accepted_loads_applied=True,
            accepted_load_profile=signature,
            accepted_load_count=len(records),
            reserved_load_count=len(planned),
            running_load_count=len(running),
            accepted_load_added_wh=added,
            accepted_load_removed_wh=removed,
            accepted_load_conservative=conservative,
        )
        # Before start, replace the reserved component rather than counting it twice.
        # Running profiles remain unavailable for renegotiation.
        replacement = None
        if rebasable and not conservative and basis is not None:
            digest = _forecast_digest(updated)
            replacement = replace(
                basis,
                forecast_digest=digest,
                component=tuple(components),
                basis_id=fingerprint(
                    dict(parent=basis.basis_id, forecast=digest, profiles=signature)
                ),
            )
        return replace(
            bundle,
            snapshot=replace(
                snapshot,
                household_load_forecast=updated,
                storage_reserve_checkpoints=tuple(
                    sorted(
                        set(
                            snapshot.storage_reserve_checkpoints
                            + tuple(
                                (
                                    snapshot.current_storage_states[0].execution_scope_id,
                                    instant(r["terminal_requirement"]["at"]),
                                    r["terminal_requirement"]["energy_wh"],
                                )
                                for r in records
                                if r.get("terminal_requirement")
                                and len(snapshot.current_storage_states) == 1
                                and instant(r["terminal_requirement"]["at"]) > snapshot.captured_at
                            )
                        )
                    )
                ),
            ),
            controlled_load_summary=summary,
            load_replacement_basis=replacement,
        )
