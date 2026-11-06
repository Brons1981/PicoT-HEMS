"""Independent electrical timing facts; climate rules stay inside HC."""

from datetime import datetime, timedelta

from .day_ahead import stamp, steady
from .energy_model import finite
from .schedule import TZ, occurrences, wall_time


def build(settings, enabled, context, cooling, now, heating_minimum, model=None, source_id=None):
    if not enabled or not settings["enabled"]:
        return []
    end = wall_time(datetime.fromtimestamp(now, TZ).date() + timedelta(days=2), 0)
    windows = occurrences(settings, now)
    edges = {now, end}
    for w in windows:
        edges.update(t for t in (w["starts_at"], w["ends_at"]) if now < t < end)
    facts = []
    for left, right in zip(sorted(edges), sorted(edges)[1:], strict=False):
        window = next((w for w in windows if w["starts_at"] <= left < w["ends_at"]), None)
        active = bool(window and window["target"] >= heating_minimum)
        previous = next((w for w in windows if w["ends_at"] == left), None)
        released = bool(
            window and not active and previous and previous["target"] >= heating_minimum
        )
        facts.append(
            dict(
                starts_at=stamp(left),
                ends_at=stamp(right),
                timing_status="known" if window else "unknown",
                operation="load_expected"
                if active
                else "load_released"
                if released
                else "conditional_load",
                energy_status="unknown",
                energy_wh=None,
                reason="energy_estimate_missing",
            )
        )
    # A scheduled release is independent of warmup energy. Only quantify its
    # initial coast when fresh temperature and measured cooling support it.
    # This is a provisional scenario: continued heating until release preserves
    # at least the lower of present indoor temperature and the comfort target.
    if not context or not context.get("valid") or not finite(context.get("indoor")):
        return facts
    current = next((w for w in windows if w["starts_at"] <= now < w["ends_at"]), None)
    if current is None:
        return facts
    if (
        model is not None
        and source_id
        and current["target"] >= heating_minimum
        and abs(context["indoor"] - current["target"]) <= 0.3
    ):
        try:
            power, method = steady(
                model, dict(context, source_id=source_id, target=current["target"]), now
            )
        except Exception:
            power = None
        if finite(power):
            for fact in facts:
                left = datetime.fromisoformat(fact["starts_at"]).timestamp()
                right = datetime.fromisoformat(fact["ends_at"]).timestamp()
                if now <= left < right <= current["ends_at"]:
                    fact.update(
                        energy_status="provisional",
                        energy_wh=power * (right - left) / 3600,
                        reason="measured_maintenance:" + method,
                    )
    try:
        rate = cooling.estimate(context, now).get("cooling_rate")
    except Exception:
        return facts
    if not finite(rate) or rate <= 0:
        return facts
    release = now if current["target"] < heating_minimum else current["ends_at"]
    following = next((w for w in windows if w["starts_at"] <= release < w["ends_at"]), None)
    if following is None or following["target"] >= heating_minimum:
        return facts
    indoor = min(context["indoor"], current["target"]) if release > now else context["indoor"]
    stop = min(following["ends_at"], release + max(0, indoor - following["target"]) / rate * 3600)
    # The next higher window may start early. Never promise zero during preheat.
    next_heat = next(
        (w for w in windows if w["starts_at"] >= release and w["target"] >= heating_minimum), None
    )
    if next_heat and settings.get("learning_enabled"):
        stop = min(stop, next_heat["starts_at"] - settings["max_preheat_minutes"] * 60)
    if stop <= release:
        return facts
    result = []
    for fact in facts:
        left = datetime.fromisoformat(fact["starts_at"]).timestamp()
        right = datetime.fromisoformat(fact["ends_at"]).timestamp()
        points = sorted({left, right} | {t for t in (release, stop) if left < t < right})
        for a, b in zip(points, points[1:], strict=False):
            row = dict(fact, starts_at=stamp(a), ends_at=stamp(b))
            if release <= a and b <= stop:
                row.update(
                    operation="load_released",
                    energy_status="provisional",
                    energy_wh=0,
                    reason="measured_coast_after_release",
                )
            result.append(row)
    return result
