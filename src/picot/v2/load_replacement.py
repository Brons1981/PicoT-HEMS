"""HEMS-owned attribution for replacing one measured component in an advisory plan."""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from picot.v2.contracts import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PlanningInputSnapshot,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _forecast_digest(forecast: HouseholdLoadForecast) -> str:
    return _digest(
        [
            forecast.forecast_id,
            [
                [
                    i.starts_at.isoformat(),
                    i.ends_at.isoformat(),
                    i.expected_energy_wh,
                    i.battery_excluded_energy_wh,
                    i.confidence,
                ]
                for i in forecast.intervals
            ],
        ]
    )


@dataclass(frozen=True)
class LoadReplacementBasis:
    basis_id: str
    snapshot_id: str
    forecast_digest: str
    source_id: str
    starts_at: datetime
    ends_at: datetime
    component: tuple[HouseholdLoadForecastInterval, ...]
    modeled_source_id: str | None = None

    def matches(self, snapshot: PlanningInputSnapshot) -> bool:
        return (
            self.snapshot_id == snapshot.snapshot_id
            and snapshot.household_load_forecast is not None
            and self.forecast_digest == _forecast_digest(snapshot.household_load_forecast)
        )

    def public(self) -> dict[str, Any]:
        value = dict(
            status="ready",
            basis_id=self.basis_id,
            source_id=self.source_id,
            starts_at=self.starts_at.isoformat(),
            ends_at=self.ends_at.isoformat(),
            demand_basis="replace_controlled_load",
            execution_authorized=False,
        )
        if self.modeled_source_id is not None:
            value.update(
                modeled_source_id=self.modeled_source_id,
                attribution="measured_and_reviewed_modeled_subset:v1",
            )
        return value


def build_basis(
    snapshot: PlanningInputSnapshot,
    historical: HouseholdLoadForecast | None,
    exact: dict[str, HouseholdLoadForecast] | None,
    *,
    modeled_source_id: str | None = None,
) -> LoadReplacementBasis | None:
    """Called only with complete attribution of the actual historical sample set.

    The parallel matched-only model is insufficient evidence. Current excess is
    protected for its entire projected window; separately added EV demand remains.
    """
    active = snapshot.household_load_forecast
    if historical is None or active is None or historical.fallback_active or not exact:
        return None
    total, component = exact["total"], exact["controlled"]
    if len(total.intervals) != len(historical.intervals):
        return None
    for a, b in zip(total.intervals, historical.intervals, strict=True):
        if (
            (a.starts_at, a.ends_at) != (b.starts_at, b.ends_at)
            or abs(a.expected_energy_wh - b.expected_energy_wh) > 1e-6
            or abs(a.confidence - b.confidence) > 1e-9
        ):
            return None
    if not component.intervals:
        return None
    start = snapshot.captured_at
    guard = snapshot.household_load_guard
    if guard is not None and (guard.active or guard.extra_power_w > 0):
        start = max(start, guard.assessed_at + timedelta(minutes=15))
    end = component.intervals[-1].ends_at
    if start >= end:
        return None
    source = component.intervals[0].source_reference.removeprefix("paired-history:")
    fingerprint = _forecast_digest(active)
    identifier = _digest(
        [snapshot.snapshot_id, fingerprint, source, start.isoformat(), _forecast_digest(component)]
    )
    if modeled_source_id is not None:
        identifier = _digest([identifier, modeled_source_id, "reviewed-subset:v1"])
    return LoadReplacementBasis(
        identifier,
        snapshot.snapshot_id,
        fingerprint,
        source,
        start,
        end,
        component.intervals,
        modeled_source_id,
    )


def replace_profile(
    snapshot: PlanningInputSnapshot,
    basis: LoadReplacementBasis,
    slots: list[dict[str, Any]],
    scale: float = 1,
) -> PlanningInputSnapshot:
    if not basis.matches(snapshot):
        raise ValueError("replacement_basis_changed")
    if (
        not slots
        or slots[0]["start"] < basis.starts_at
        or slots[-1]["end"] > basis.ends_at
        or any(a["end"] != b["start"] for a, b in zip(slots, slots[1:], strict=False))
    ):
        raise ValueError("replacement_window_not_covered")
    forecast = snapshot.household_load_forecast
    assert forecast is not None
    boundaries = {s[t] for s in slots for t in ("start", "end")}
    boundaries.update(t for i in basis.component for t in (i.starts_at, i.ends_at))
    rows = []
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
            slot = next((s for s in slots if s["start"] <= left < s["end"]), None)
            if slot is not None:
                prior = next(
                    (i for i in basis.component if i.starts_at <= left and right <= i.ends_at), None
                )
                if prior is None:
                    raise ValueError("replacement_component_gap")
                removed = (
                    prior.expected_energy_wh * (right - left) / (prior.ends_at - prior.starts_at)
                )
                if removed > energy - excluded + 1e-6:
                    raise ValueError("replacement_component_exceeds_eligible_demand")
                energy = max(excluded, energy - removed) + slot["energy"] * scale * (
                    right - left
                ) / (slot["end"] - slot["start"])
            identifier = _digest(
                [basis.basis_id, left.isoformat(), right.isoformat(), energy, excluded]
            )
            rows.append(
                replace(
                    item,
                    interval_id="replacement-" + identifier[:16],
                    starts_at=left,
                    ends_at=right,
                    expected_energy_wh=energy,
                    battery_excluded_energy_wh=excluded,
                )
            )
    return replace(
        snapshot,
        household_load_forecast=replace(
            forecast,
            forecast_id="replacement-" + _digest([r.interval_id for r in rows])[:16],
            intervals=tuple(rows),
        ),
    )
