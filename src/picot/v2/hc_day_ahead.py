"""Validate HC's advisory forecast and replace only attributed airco demand."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from picot.v2.contracts import ExternalLoadFact
from picot.v2.energy_portfolio import fingerprint, instant
from picot.v2.load_replacement import LoadReplacementBasis, _forecast_digest, replace_profile

if TYPE_CHECKING:
    from picot.v2.planning_input import PlanningInputBundle


def unavailable_explanation(attributes: dict[str, Any]) -> str:
    """Describe advisory unavailability without accepting its forecast payload."""
    labels = {
        "no_warmup_measurements": "onvoldoende bruikbare opwarmhistorie",
        "fresh_thermal_context_required": "actuele temperatuur- en regelgegevens ontbreken",
        "no_energy_measurements": "onvoldoende bruikbare energiehistorie",
        "no_comparable_energy_measurements": "geen vergelijkbare energiemetingen",
        "forecast_generation_failed": "aanmaken van de prognose mislukt",
    }
    reasons = attributes.get("reasons")
    known = (
        [text for code, text in labels.items() if code in reasons]
        if attributes.get("contract") == "hc-day-ahead:v1" and isinstance(reasons, list)
        else []
    )
    cause = "; ".join(known) or "oorzaak niet aangeleverd of niet herkend"
    return f"Niet beschikbaar: {cause}. Huishoudprognose wordt gebruikt."


def validate(value: Any, now: datetime) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or (
        value.get("contract") != "hc-day-ahead:v1"
        or value.get("scope") != "beneden"
        or value.get("source_assumption") != "airco"
        or value.get("execution_authorized") is not False
        or value.get("status") not in ("ready", "provisional", "partial")
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


def load_facts(
    value: Any, now: datetime, *, report: dict[str, Any] | None = None,
) -> tuple[ExternalLoadFact, ...]:
    if not isinstance(value, dict) or "load_facts" not in value:
        return ()
    # Reuse envelope freshness/identity validation, with a harmless validation row.
    check = dict(
        value,
        slots=[
            dict(starts_at=value.get("generated_at"), ends_at=value.get("valid_until"), energy_wh=0)
        ],
    )
    validate(check, now)
    source = value.get("source_id")
    if not isinstance(source, str) or not source:
        raise ValueError("hc_forecast_source_missing")
    rows = value["load_facts"]
    if not isinstance(rows, list) or len(rows) > 300:
        if report is not None:
            report.update(rejected_timing_facts=len(rows) if isinstance(rows, list) else 1,
                          load_fact_rejections={"hc_load_facts_invalid": 1})
        return ()
    generated, until = instant(value["generated_at"]), instant(value["valid_until"])
    result: list[ExternalLoadFact] = []
    rejected: dict[str, int] = {}
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise ValueError("invalid row")
            start, end = instant(row["starts_at"]), instant(row["ends_at"])
            if not generated <= start < end <= generated + timedelta(hours=51):
                raise ValueError("invalid timing")
        except (KeyError, TypeError, ValueError, OverflowError):
            code = "hc_load_facts_invalid_timing"
            rejected[code] = rejected.get(code, 0) + 1
            continue
        timing = row.get("timing_status")
        operation = row.get("operation")
        if timing not in ("known", "unknown") or operation not in (
            "load_expected",
            "conditional_load",
            "load_released",
        ):
            code = "hc_load_facts_invalid_operation"
            rejected[code] = rejected.get(code, 0) + 1
            continue
        status, energy = row.get("energy_status"), row.get("energy_wh")
        if (
            status not in ("ready", "provisional")
            or energy is None
            or type(energy) not in (int, float)
            or (
                not isfinite(energy)
                or not 0 <= energy <= 20000 * (end - start).total_seconds() / 3600
            )
        ):
            status, energy = "unknown", None
        reason = str(row.get("reason", "unspecified"))[:160]
        result.append(
            ExternalLoadFact(
                source,
                value["revision"],
                generated,
                until,
                start,
                end,
                timing,
                operation,
                status,
                energy,
                reason,
            )
        )
    # No last-row-wins rule: quarantine every overlapping interval, even when
    # one of them was encountered earlier. Independent intervals remain useful.
    result.sort(key=lambda fact: (fact.starts_at, fact.ends_at))
    conflicts: set[int] = set()
    for index, fact in enumerate(result):
        for other_index in range(index + 1, len(result)):
            if result[other_index].starts_at >= fact.ends_at:
                break
            conflicts.update((index, other_index))
    if conflicts:
        rejected["hc_load_facts_overlap"] = len(conflicts)
    if report is not None:
        report.update(rejected_timing_facts=sum(rejected.values()), load_fact_rejections=rejected)
    return tuple(fact for index, fact in enumerate(result) if index not in conflicts)


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
        facts = load_facts(value, bundle.snapshot.captured_at, report=status)
        if facts:
            bundle = replace(bundle, snapshot=replace(bundle.snapshot, external_load_facts=facts))
            status.update(
                timing_facts=len(facts),
                unknown_energy_intervals=sum(f.energy_wh is None for f in facts),
            )
        if isinstance(value, dict) and value.get("status") == "partial":
            slots: list[dict[str, Any]] = [
                dict(start=f.starts_at, end=f.ends_at, energy=f.energy_wh)
                for f in facts
                if f.energy_wh is not None
            ]
            if not slots:
                raise ValueError("hc_forecast_energy_unknown")
        else:
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
        updated = bundle.snapshot
        # Known intervals can be separated by unknown intervals. Apply each known
        # interval and rebase the digest; unknown demand remains unchanged.
        groups: list[list[dict[str, Any]]] = []
        for known_slot in clipped:
            if not groups or groups[-1][-1]["end"] != known_slot["start"]:
                groups.append([])
            groups[-1].append(known_slot)
        for group in groups:
            assert updated.household_load_forecast is not None
            current_basis = replace(
                basis, forecast_digest=_forecast_digest(updated.household_load_forecast)
            )
            updated = replace_profile(updated, current_basis, group)
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
                            item.confidence,
                            0.5 if value["status"] in ("provisional", "partial") else 1,
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
            fallback="historical_household_forecast_for_unknown_intervals"
            if value["status"] == "partial"
            else None,
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
