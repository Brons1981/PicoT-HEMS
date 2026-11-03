"""Validate HC's advisory forecast and replace only attributed airco demand."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from picot.v2.energy_portfolio import fingerprint, instant
from picot.v2.load_replacement import LoadReplacementBasis, _forecast_digest, replace_profile

if TYPE_CHECKING:
    from picot.v2.planning_input import PlanningInputBundle


def validate(value: Any, now: datetime) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or (
        value.get("contract") != "hc-day-ahead:v1"
        or value.get("scope") != "beneden"
        or value.get("source_assumption") != "airco"
        or value.get("execution_authorized") is not False
        or value.get("status") not in ("ready", "provisional")
        or value.get("timezone") != "Europe/Amsterdam"
        or not isinstance(value.get("revision"), str)
    ):
        raise ValueError("hc_forecast_missing_or_unavailable")
    generated, until = instant(value["generated_at"]), instant(value["valid_until"])
    if not generated <= now < until <= generated + timedelta(hours=2):
        raise ValueError("hc_forecast_stale")
    dates = {
        now.astimezone(ZoneInfo("Europe/Amsterdam")).date() + timedelta(days=n) for n in (0, 1)
    }
    if value.get("delivery_date") not in {d.isoformat() for d in dates}:
        raise ValueError("hc_forecast_wrong_delivery_day")
    rows = value.get("slots")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 300:
        raise ValueError("hc_forecast_invalid_slots")
    result: list[dict[str, Any]] = []
    for row in rows:
        start, end = instant(row["starts_at"]), instant(row["ends_at"])
        energy = row["energy_wh"]
        if (
            not generated <= start < end <= generated + timedelta(hours=51)
            or type(energy) not in (int, float)
            or not isfinite(energy)
            or not 0 <= energy <= 20000 * (end - start).total_seconds() / 3600
            or result
            and result[-1]["end"] != start
        ):
            raise ValueError("hc_forecast_invalid_slots")
        result.append(dict(start=start, end=end, energy=energy))
    return result


def apply(
    bundle: PlanningInputBundle, value: Any, airco_basis: LoadReplacementBasis | None
) -> PlanningInputBundle:
    summary = dict(bundle.controlled_load_summary or {})
    previous = summary.get("hc_day_ahead")
    if isinstance(previous, dict) and previous.get("applied"):
        return bundle
    status: dict[str, Any] = dict(
        applied=False,
        status="fallback",
        fallback="historical_household_forecast",
        execution_authorized=False,
    )
    try:
        if isinstance(value, dict):
            status.update(
                revision=value.get("revision"),
                delivery_date=value.get("delivery_date"),
                forecast_status=value.get("status"),
                reasons=value.get("reasons", []),
            )
            if value.get("status") == "disabled" and value.get("contract") == "hc-day-ahead:v1":
                status.update(status="disabled", reason="automatic_schedule_disabled")
                summary["hc_day_ahead"] = status
                return replace(bundle, controlled_load_summary=summary)
        slots = validate(value, bundle.snapshot.captured_at)
        basis = airco_basis
        if (
            basis is None
            or not basis.matches(bundle.snapshot)
            or basis.source_id != value.get("source_id")
            or basis.modeled_source_id is not None
        ):
            raise ValueError("hc_forecast_exact_heating_attribution_missing")
        clipped = []
        for candidate in slots:
            start, end = (
                max(candidate["start"], basis.starts_at),
                min(candidate["end"], basis.ends_at),
            )
            if start < end:
                clipped.append(
                    dict(
                        start=start,
                        end=end,
                        energy=candidate["energy"]
                        * (end - start)
                        / (candidate["end"] - candidate["start"]),
                    )
                )
        if not clipped:
            raise ValueError("hc_forecast_outside_planning_horizon")
        updated = replace_profile(bundle.snapshot, basis, clipped)
        forecast = updated.household_load_forecast
        assert forecast is not None
        updated = replace(
            updated,
            household_load_forecast=replace(
                forecast,
                intervals=tuple(
                    replace(
                        item,
                        confidence=min(
                            item.confidence, 0.5 if value["status"] == "provisional" else 1
                        ),
                        source_reference="hc-day-ahead:" + value["revision"],
                        method_version="attributed-hc-day-ahead:v1",
                    )
                    if any(
                        s["start"] <= item.starts_at and item.ends_at <= s["end"] for s in clipped
                    )
                    else item
                    for item in forecast.intervals
                ),
            ),
        )
        # Rebase attribution for later accepted HC profiles. They replace the day
        # forecast, preserving any independently attributed CV auxiliary component.
        combined = bundle.load_replacement_basis
        rebased = None
        if combined is not None and combined.matches(bundle.snapshot):
            forecast = updated.household_load_forecast
            assert forecast is not None
            components = []
            for item in forecast.intervals:
                left, right = item.starts_at, item.ends_at
                old = next(
                    (i for i in combined.component if i.starts_at <= left and right <= i.ends_at),
                    None,
                )
                pure = next(
                    (i for i in basis.component if i.starts_at <= left and right <= i.ends_at), None
                )
                slot = next((s for s in clipped if s["start"] <= left and right <= s["end"]), None)
                if old is None:
                    raise ValueError("hc_forecast_rebase_gap")
                energy = old.expected_energy_wh * (right - left) / (old.ends_at - old.starts_at)
                if slot is not None:
                    if pure is None:
                        raise ValueError("hc_forecast_component_gap")
                    energy -= (
                        pure.expected_energy_wh * (right - left) / (pure.ends_at - pure.starts_at)
                    )
                    energy += slot["energy"] * (right - left) / (slot["end"] - slot["start"])
                if (
                    energy < -1e-6
                    or energy > item.expected_energy_wh - item.battery_excluded_energy_wh + 1e-6
                ):
                    raise ValueError("hc_forecast_component_invalid")
                components.append(
                    replace(item, expected_energy_wh=max(0, energy), battery_excluded_energy_wh=0)
                )
            rebased = replace(
                combined,
                component=tuple(components),
                forecast_digest=_forecast_digest(forecast),
                basis_id=fingerprint(dict(parent=combined.basis_id, hc=value["revision"])),
            )
        status.update(
            applied=True,
            status=value["status"],
            fallback=None,
            reason=None,
            source_assumption="airco",
            energy_wh=sum(s["energy"] for s in clipped),
            starts_at=clipped[0]["start"].isoformat(),
            ends_at=clipped[-1]["end"].isoformat(),
        )
        summary["hc_day_ahead"] = status
        return replace(
            bundle,
            snapshot=updated,
            controlled_load_summary=summary,
            load_replacement_basis=rebased,
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        status["reason"] = str(exc)
        summary["hc_day_ahead"] = status
        return replace(bundle, controlled_load_summary=summary)
