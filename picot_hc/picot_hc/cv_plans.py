"""CV recipes stay in HC; HEMS receives only energy intervals and gas cost."""

import copy
from types import SimpleNamespace

from .cv_energy_model import estimate
from .delayed_start import candidates as delayed_candidates
from .energy_model import finite


def tail_allowance(context, start, end=None):
    context = context or {}
    until, power = context.get("prior_tail_until"), context.get("prior_tail_power_w")
    if not finite(until) or not finite(power) or power < 0:
        return 0
    return power * max(0, (min(until, end) if end is not None else until) - start) / 3600


def candidates(
    sample, view, plan, context, standby_w, now, start, end, *, fixed_start=None, cooling=None
):
    if end != (view.get("next") or {}).get("ends_at"):
        return []
    if not finite(plan.get("costs", {}).get("cv")):
        return []
    if (
        not context
        or context.get("sample") is None
        or not finite(standby_w)
        or not finite(context.get("gas_price"))
        or not 0 <= context["gas_price"] <= 20
    ):
        return []
    original = context["sample"]
    upstairs = plan.get("owned", {}).get("boven")
    source = plan.get("sources", {}).get("boven", {})
    earliest = now
    if upstairs:
        since = upstairs.get("since")
        if (not finite(since) or since > now or upstairs.get("released")
                or "boven" in plan.get("faults", {})):
            return []
        # A renewed fixed plan keeps its original transfer deadline while Off
        # feedback is pending. Execution still requires observed, confirmed Off.
        earliest = since + 300
        if fixed_start is None:
            earliest = max(now, earliest)
        earliest += plan.get("cv_handover_seconds", 60)
    elif source.get("state", "off") != "off" or source.get("pending"):
        return []  # Never claim or stop a manually operated upstairs source.
    if (
        original.get("gas_screening", {}).get("status") != "available"
        or original["gas_screening"].get("active") is not False
    ):
        return []

    def query(point):
        return dict(
            original,
            indoor=point["indoor"],
            outdoor=point["outdoor"],
            target=point["target"],
            weather=copy.deepcopy(point.get("weather")),
        )

    def warming(point, moment):
        value = estimate(context["warmup"].records, query(point), moment)
        electricity = value.get("electricity")
        return dict(
            value,
            energy_wh=(
                electricity["energy_wh"] + standby_w * value["duration_seconds"] / 3600
                if electricity
                else None
            ),
        )

    def holding(point, moment):
        value = context["maintenance"].estimate(query(point), moment)
        return dict(
            value, power_w=value["power_w"] + standby_w if value["power_w"] is not None else None
        )

    cv_plan = copy.deepcopy(plan)
    cv_plan["sources"]["beneden"] = copy.deepcopy(plan["sources"]["cv"])
    options = delayed_candidates(
        sample,
        view,
        cv_plan,
        SimpleNamespace(estimate=warming),
        SimpleNamespace(estimate=holding),
        standby_w,
        now,
        start,
        end,
        fixed_start=fixed_start,
        cooling=cooling,
    )
    for p in options:
        gas = p["startup_estimate"]["gas_m3"]
        rate = p["maintenance"]["gas_m3_per_hour"]
        tail = p["startup_estimate"]["electricity"]["postrun_energy_wh"]
        p["slots"][-1]["energy_wh"] += tail
        p.update(
            source="cv",
            plan_id="cv_" + p["plan_id"],
            startup_gas_m3=gas,
            gas_price=context["gas_price"],
            cv_sample=copy.deepcopy(original),
            cv_postrun_wh=tail,
            standby_w=standby_w,
            non_electric_cost_eur=(gas + rate * (end - p["reaches_at"]) / 3600)
            * context["gas_price"],
        )
    return [
        p
        for p in options
        if p["heat_starts_at"] >= earliest
        and finite(p["non_electric_cost_eur"]) and 0 <= p["non_electric_cost_eur"] <= 1000
    ]
