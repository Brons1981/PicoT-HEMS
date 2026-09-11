"""Bounded background collection and persistence for passive grid-charge reviews."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from zoneinfo import ZoneInfo

from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.daily_charge_assignment import DailyChargeAssignment
from picot.v2.daily_pv_comparison import DailyPVComparisonBasis
from picot.v2.grid_charge_review import ReviewSettings, _Series, actual_soc_view, review_day
from picot.v2.power_history import (
    HomeAssistantPowerHistoryReader,
    PowerHistorySnapshot,
    PowerSeriesSpec,
    rebase_power_history,
)


class GridChargeReviewObserver:
    """One daemon worker, no queue, no planner/store/actuator mutation capability."""

    def __init__(
        self,
        *,
        path: Path,
        reader: HomeAssistantPowerHistoryReader,
        specs: tuple[PowerSeriesSpec, ...],
        soc_entity_id: str,
        attach_household: Callable[[PowerHistorySnapshot], PowerHistorySnapshot],
        publish: Callable[[dict[str, Any]], None],
        charge_efficiency: float,
        discharge_efficiency: float,
        wear_eur_per_kwh: float,
        timezone: str = "Europe/Amsterdam",
    ) -> None:
        self.path, self.reader, self.attach_household, self.publish = (
            path,
            reader,
            attach_household,
            publish,
        )
        self.specs = (
            *specs,
            *(
                (PowerSeriesSpec("actual-soc", "storage_soc", soc_entity_id),)
                if soc_entity_id
                else ()
            ),
        )
        self.timezone = ZoneInfo(timezone)
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency
        self.wear = wear_eur_per_kwh
        self.lock = Lock()
        self.last_attempt: datetime | None = None
        self.last_day: str | None = None
        self.state: dict[str, Any] = {"schema_version": 1, "days": {}, "inputs": {}}
        try:
            if path.stat().st_size <= 5_000_000:
                value = json.loads(path.read_text())
                if value.get("schema_version") == 1 and all(
                    isinstance(value.get(k), dict) for k in ("days", "inputs")
                ):
                    self.state = value
        except (OSError, ValueError, AttributeError):
            pass

    def due(self, now: datetime) -> bool:
        return not self.lock.locked() and (
            self.last_attempt is None
            or now.astimezone(self.timezone).date().isoformat() != self.last_day
            or now - self.last_attempt >= timedelta(minutes=5)
        )

    def submit(
        self,
        snapshot: PlanningInputSnapshot,
        prices: tuple[PriceForecastPoint, ...],
        assignments: tuple[DailyChargeAssignment, ...],
        bases: tuple[DailyPVComparisonBasis, ...],
    ) -> None:
        day = snapshot.captured_at.astimezone(self.timezone).date().isoformat()
        if (
            self.last_attempt is not None
            and day == self.last_day
            and (snapshot.captured_at - self.last_attempt < timedelta(minutes=5))
        ):
            return
        if not self.lock.acquire(blocking=False):
            return
        self.last_attempt, self.last_day = snapshot.captured_at, day

        def work() -> None:
            try:
                self.refresh(snapshot, prices, assignments, bases)
            except Exception as exc:
                # Passive I/O/model faults must not affect a canonical poll.
                self.publish(
                    {
                        "status": "unavailable",
                        "reason": type(exc).__name__,
                        "days": list(self.state["days"].values()),
                        "actual_soc": {"status": "unavailable", "points": []},
                    }
                )
            finally:
                self.lock.release()

        try:
            Thread(target=work, name="picot-grid-charge-review", daemon=True).start()
        except RuntimeError:
            self.lock.release()
            raise

    def refresh(
        self,
        snapshot: PlanningInputSnapshot,
        prices: tuple[PriceForecastPoint, ...],
        assignments: tuple[DailyChargeAssignment, ...],
        bases: tuple[DailyPVComparisonBasis, ...],
    ) -> None:
        """Synchronous worker body, exposed for deterministic integration checks."""
        now = snapshot.captured_at
        today = now.astimezone(self.timezone).date()
        midnight = datetime.combine(today, datetime.min.time(), self.timezone).astimezone(UTC)
        if len(snapshot.current_storage_states) != 1:
            raise ValueError("single_storage_scope_required")
        storage = snapshot.current_storage_states[0]
        limit = next(
            item
            for item in snapshot.storage_physical_limits
            if item.execution_scope_id == storage.execution_scope_id
        )
        settings = ReviewSettings(
            storage.usable_capacity_wh,
            limit.minimum_soc,
            limit.maximum_soc,
            limit.maximum_charge_input_power_w,
            limit.maximum_discharge_output_power_w,
            self.charge_efficiency,
            self.discharge_efficiency,
            self.wear,
        )
        inputs = self.state["inputs"]
        context = inputs.setdefault(
            today.isoformat(),
            {
                "settings": asdict(settings),
                "prices": {},
                "settings_changed": False,
            },
        )
        context["settings_changed"] |= context["settings"] != asdict(settings)
        # Save published prices before they disappear from tomorrow's HA entity.
        for p in prices:
            if midnight <= p.starts_at < midnight + timedelta(hours=26):
                context["prices"][p.starts_at.isoformat()] = {
                    **asdict(p),
                    "starts_at": p.starts_at.isoformat(),
                    "ends_at": p.ends_at.isoformat(),
                }
        actual: dict[str, Any] = {"status": "unavailable", "points": []}
        for day in (today - timedelta(days=1), today):
            key = day.isoformat()
            old = self.state["days"].get(key, {})
            if day != today and old.get("finalized") and old.get("status") == "available":
                continue
            start = datetime.combine(day, datetime.min.time(), self.timezone).astimezone(UTC)
            end = min(
                now,
                datetime.combine(
                    day + timedelta(days=1), datetime.min.time(), self.timezone
                ).astimezone(UTC),
            )
            if end <= start or key not in inputs:
                continue
            # Separate raw read preserves unavailable markers; existing dashboards/ledger
            # keep their original history contract. SOC's transport scalar is percent.
            history = self.reader.read(
                specs=self.specs,
                starts_at=start - timedelta(minutes=5),
                ends_at=end,
                preserve_unavailable=True,
            )
            history = self.attach_household(rebase_power_history(history, starts_at=start))
            if day == today:
                actual = actual_soc_view(history)
            ctx = inputs[key]
            known_prices = tuple(
                PriceForecastPoint(
                    **{
                        **p,
                        "starts_at": datetime.fromisoformat(p["starts_at"]),
                        "ends_at": datetime.fromisoformat(p["ends_at"]),
                    }
                )
                for p in ctx["prices"].values()
            )
            owner = next(
                (
                    a
                    for a in assignments
                    if a.delivery_date == day and a.execution_scope_id == storage.execution_scope_id
                ),
                None,
            )
            windows = (
                ()
                if owner is None
                else tuple(
                    (s.starts_at, s.ends_at)
                    for s in (
                        *owner.main_segments,
                        *(
                            (owner.historical_completion_segment,)
                            if owner.historical_completion_segment
                            else ()
                        ),
                    )
                )
            )
            result = review_day(history, known_prices, ReviewSettings(**ctx["settings"]), windows)
            if ctx["settings_changed"]:
                result = {"status": "incomplete", "reason": "settings_changed_during_day"}
            basis = next(
                (b for b in bases if owner and b.assignment_id == owner.assignment_id), None
            )
            digest = sha256()
            for series in history.series:
                digest.update(series.source_entity_id.encode())
                for point in series.points:
                    digest.update(repr(point).encode())
            result.update(
                {
                    "day": key,
                    "captured_at": now.isoformat(),
                    "finalized": day < today,
                    "snapshot_id": snapshot.snapshot_id,
                    "assignment_id": owner.assignment_id if owner else None,
                    "route_plan_id": owner.route_plan_id if owner else None,
                    "settings": ctx["settings"],
                    "evidence_digest": digest.hexdigest(),
                    "pv_comparison": self._pv_comparison(history, basis),
                }
            )
            self.state["days"][key] = result
        # Keep 90 review days and 3 days of input tariffs; finalized missing days are
        # visible but excluded from aggregate conclusions, never invented as zero.
        for mapping, count in ((self.state["days"], 90), (inputs, 3)):
            for key in sorted(mapping)[:-count]:
                del mapping[key]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".writing")
        temporary.write_text(json.dumps(self.state, allow_nan=False, separators=(",", ":")))
        temporary.replace(self.path)
        self.publish(
            {
                "status": "available",
                "days": sorted(self.state["days"].values(), key=lambda d: d["day"]),
                "actual_soc": actual,
            }
        )

    @staticmethod
    def _pv_comparison(
        history: PowerHistorySnapshot,
        basis: DailyPVComparisonBasis | None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "unavailable"}
        if basis is None:
            return result
        result["basis_id"] = basis.basis_id
        intervals = tuple(i for i in basis.intervals if i.ends_at <= history.ends_at)
        if not intervals:
            return result
        raw = next((s for s in history.series if s.role == "pv_generation"), None)
        if raw is None or history.error is not None:
            return result
        series = _Series(raw)
        actual = 0.0
        try:
            for i in intervals:
                times = sorted(
                    {
                        i.starts_at,
                        i.ends_at,
                        *(t for t in series.times if i.starts_at < t < i.ends_at),
                    }
                )
                for a, b in zip(times, times[1:], strict=False):
                    actual += series.value(a) * (b - a).total_seconds() / 3600
        except ValueError:
            return result
        expected = sum((i.lower_wh + i.central_wh) / 2 for i in intervals)
        return {
            **result,
            "status": "available",
            "actual_kwh": round(actual / 1000, 4),
            "expected_kwh": round(expected / 1000, 4),
            "difference_kwh": round((actual - expected) / 1000, 4),
            "starts_at": intervals[0].starts_at.isoformat(),
            "ends_at": intervals[-1].ends_at.isoformat(),
        }
