"""Optional modeled contribution, kept distinct from the measured component."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from math import isfinite
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from picot.v2.contracts import HouseholdLoadForecast

if TYPE_CHECKING:
    from picot.v2.planning_input import HouseholdLoadObservation

from picot.v2.controlled_load_history import paired_forecasts


def attribute_model(
    observation: HouseholdLoadObservation | None, payload: object, captured_at: datetime
) -> HouseholdLoadObservation | None:
    if observation is None or not isinstance(payload, dict):
        return observation
    try:
        value = payload.get("estimated_component", {})
        power, source = value["power_w"], value["source_id"]
        generated = datetime.fromisoformat(value["generated_at"])
        measured = observation.controlled_power_w
        if (
            value["contract"] != "modeled-load:v1"
            or value["status"] != "estimated"
            or type(power) not in (int, float)
            or not isfinite(power)
            or measured is None
            or source == observation.controlled_source_id
            or not 0
            <= power
            <= observation.power_w - observation.identified_external_power_w - measured
            or not isinstance(source, str)
            or len(source) != 64
            or any(c not in "0123456789abcdef" for c in source)
            or generated.utcoffset() is None
            or not 0 <= (captured_at - generated).total_seconds() <= 60
            or abs((observation.sampled_at - generated).total_seconds()) > 30
        ):
            return observation
        return replace(
            observation,
            modeled_power_w=float(power),
            modeled_source_id=source,
            modeled_reviews=read_reviews(value.get("reviewed_components"), captured_at),
        )
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return observation


def read_reviews(values: object, captured_at: datetime) -> tuple[tuple[str, float, float], ...]:
    """A reviewed subset can only annotate history, never replace a physical value."""
    if not isinstance(values, (list, tuple)) or len(values) > 80:
        return ()
    result = []
    for value in values:
        try:
            moment = datetime.fromisoformat(value["sampled_at"])
            total, subset = value["power_w"], value["replaceable_power_w"]
            if (
                moment.utcoffset() is None
                or not 90 <= (captured_at - moment).total_seconds() <= 1260
                or any(type(v) not in (int, float) or not isfinite(v) for v in (total, subset))
                or not 0 <= subset <= total <= 2000
            ):
                continue
            result.append((moment.isoformat(), float(total), float(subset)))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return tuple(result)


def apply_reviews(
    observations: Sequence[HouseholdLoadObservation],
) -> tuple[HouseholdLoadObservation, ...]:
    from bisect import bisect_left, bisect_right

    grouped: dict[str, dict[tuple[float, float], float]] = {}
    for observation in observations:
        source = observation.modeled_source_id
        if source is None:
            continue
        entries = grouped.setdefault(source, {})
        for stamp, total, subset in observation.modeled_reviews:
            key = (datetime.fromisoformat(stamp).timestamp(), total)
            entries[key] = min(entries.get(key, subset), subset)
    index: dict[str | None, tuple[list[float], list[tuple[float, float, float]]]] = {}
    for source, entries in grouped.items():
        rows = sorted((stamp, total, subset) for (stamp, total), subset in entries.items())
        index[source] = ([r[0] for r in rows], rows)
    result = []
    for observation in observations:
        times, rows = index.get(observation.modeled_source_id, ([], []))
        sampled_at = observation.sampled_at.timestamp()
        matches = [
            r[2]
            for r in rows[
                bisect_left(times, sampled_at - 15) : bisect_right(times, sampled_at + 15)
            ]
            if r[1] == observation.modeled_power_w
        ]
        result.append(
            replace(observation, replaceable_modeled_power_w=min(matches))
            if matches
            else observation
        )
    return tuple(result)


def modeled_forecasts(
    observations: Sequence[HouseholdLoadObservation],
    *,
    source_id: str,
    run_id: str,
    snapshot_id: str,
    starts_at: datetime,
    horizon_end: datetime,
) -> dict[str, HouseholdLoadForecast] | None:
    # Reuse identical sample selection and weights; never mutate physical observations.
    proxy = [
        SimpleNamespace(
            sampled_at=o.sampled_at,
            power_w=o.power_w,
            controlled_power_w=o.modeled_power_w,
            controlled_source_id=o.modeled_source_id,
        )
        for o in observations
    ]
    result = paired_forecasts(
        proxy,
        source_id=source_id,
        require_complete=True,
        run_id=run_id,
        snapshot_id=snapshot_id,
        starts_at=starts_at,
        horizon_end=horizon_end,
    )
    if result is None:
        return None
    return {
        kind: replace(
            forecast,
            intervals=tuple(
                replace(
                    i,
                    method_version="modeled-paired-weighted-clock-quarter:v1",
                    source_reference="modeled-history:" + source_id,
                )
                for i in forecast.intervals
            ),
        )
        for kind, forecast in result.items()
    }


def joint_forecasts(
    observations: Sequence[HouseholdLoadObservation],
    *,
    source_id: str,
    run_id: str,
    snapshot_id: str,
    starts_at: datetime,
    horizon_end: datetime,
    modeled_source_id: str,
) -> dict[str, HouseholdLoadForecast] | None:
    """Replace only the reviewed subset; the retained modeled part stays in residual."""
    proxy = []
    for o in observations:
        valid = (
            o.controlled_source_id == source_id
            and o.modeled_source_id == modeled_source_id
            and o.controlled_power_w is not None
            and o.replaceable_modeled_power_w is not None
        )
        proxy.append(
            SimpleNamespace(
                sampled_at=o.sampled_at,
                power_w=o.power_w,
                controlled_power_w=o.controlled_power_w + o.replaceable_modeled_power_w
                if valid
                and o.controlled_power_w is not None
                and o.replaceable_modeled_power_w is not None
                else None,
                controlled_source_id=source_id if valid else None,
            )
        )
    return cast(
        dict[str, HouseholdLoadForecast] | None,
        paired_forecasts(
            proxy,
            source_id=source_id,
            require_complete=True,
            run_id=run_id,
            snapshot_id=snapshot_id,
            starts_at=starts_at,
            horizon_end=horizon_end,
        ),
    )
