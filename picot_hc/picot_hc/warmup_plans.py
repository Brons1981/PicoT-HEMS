"""Advisory continuation profiles for an already confirmed downstairs heat run."""

import math

from .energy_model import finite
from .hourly_weather import planning_models


def candidates(sample, view, plan, warmup, steady, now, start, end):
    window = view.get("next")
    if (
        sample is None
        or not window
        or view.get("current")
        or not plan.get("preheating")
        or plan.get("learning_status", {}).get("phase") != "preheat"
        or not now < start < window["starts_at"] < end
        or end > window["ends_at"]
        or end - now > 15 * 3600
        or start - now > 900
    ):
        return []
    source = plan.get("sources", {}).get("beneden", {})
    if not source.get("temperature_supported"):
        return []
    low, high, step = (source.get(k) for k in ("minimum", "maximum", "step"))
    if not all(finite(v) for v in (low, high, step)) or step <= 0:
        return []
    bounded = planning_models(plan, [warmup, steady], sample, now, start, end)
    if bounded is None:
        return []
    (warmup, steady), _ = bounded
    targets = [window["target"]]
    if not window["hard"]:
        targets += [window["target"] - 0.5, window["target"] + 0.5]
    result = []
    for target in targets:
        if (
            not window["minimum"] <= target <= window["maximum"]
            or not low <= target <= high
            or not math.isclose((target - low) / step, round((target - low) / step), abs_tol=1e-5)
            or target - sample["indoor"] < 0.5
        ):
            continue
        query = dict(sample, target=target)
        heating = warmup.estimate(query, now)
        holding = steady.estimate(dict(query, indoor=target), now)
        if heating["energy_wh"] is None or holding["power_w"] is None:
            continue
        duration = heating["duration_seconds"]
        reached = start + duration
        # Common prefix: existing heating continues unchanged before start. Reserve the full
        # measured trajectory afterwards; do not subtract guessed progress or startup energy.
        if not start < reached <= window["starts_at"]:
            continue
        watts = heating["energy_wh"] * 3600 / duration
        if not 0 < watts <= 20000 or not 0 < holding["power_w"] <= 20000:
            continue
        result.append(
            dict(
                plan_id="warmup_" + str(len(result) + 1),
                target=target,
                samples=heating["samples"],
                warmup=heating,
                maintenance=holding,
                reaches_at=reached,
                slots=[
                    dict(
                        starts_at=start, ends_at=reached, energy_wh=watts * (reached - start) / 3600
                    ),
                    dict(
                        starts_at=reached,
                        ends_at=end,
                        energy_wh=holding["power_w"] * (end - reached) / 3600,
                    ),
                ],
            )
        )
    return result
