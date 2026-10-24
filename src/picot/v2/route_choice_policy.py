"""User admission constraints on existing candidates; never a new price objective."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from picot.domain.daily_reference_charge_window import DailyMainChargeWindow
from picot.domain.energy_path import EnergyPath
from picot.domain.evaluation import CandidateValidity
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.mep_candidate_outcomes import (
    MainChargeCandidateSource,
    MainChargeComparablePortfolio,
)
from picot.v2.daily_charge_assignment import DailyChargeAssignment


def main_signature(window: DailyMainChargeWindow) -> list[list[str]]:
    return [
        [
            s.starts_at.astimezone(UTC).isoformat(),
            s.ends_at.astimezone(UTC).isoformat(),
            s.intent.value,
        ]
        for s in window.main_segments
    ]


def constrain(
    portfolio: MainChargeComparablePortfolio, allowed: set[str], reason: str
) -> MainChargeComparablePortfolio:
    """Keep all evidence and let Evaluation select only admitted alternatives."""
    return replace(
        portfolio,
        outcome_set=replace(
            portfolio.outcome_set,
            outcomes=tuple(
                o
                if o.candidate_id in allowed or o.validity is CandidateValidity.INVALID
                else replace(o, validity=CandidateValidity.INVALID, invalidity_reasons=(reason,))
                for o in portfolio.outcome_set.outcomes
            ),
        ),
    )


def requested_candidates(
    portfolio: MainChargeComparablePortfolio, record: dict[str, Any], at: datetime
) -> set[str]:
    signature = record["offer"]["alternative"]["main_signature"]

    def remaining(items: list[list[str]]) -> list[list[str]]:
        return [
            [
                max(at, datetime.fromisoformat(a)).astimezone(UTC).isoformat(),
                datetime.fromisoformat(b).astimezone(UTC).isoformat(),
                intent,
            ]
            for a, b, intent in items
            if datetime.fromisoformat(b) > at
        ]

    return {
        s.candidate_id
        for s in portfolio.sources
        if s.window is not None and remaining(main_signature(s.window)) == remaining(signature)
    }


def respects_choice(path: EnergyPath, record: dict[str, Any], at: datetime) -> bool:
    """Economic changes may shorten selected charging, never add/move grid charging.

    Applies to owned main charging; genuine reserve/target repair is admitted by
    its existing trigger outside this policy. Other assignments retain authority.
    """
    signature = record["offer"]["alternative"]["main_signature"]
    allowed = [
        (datetime.fromisoformat(a), datetime.fromisoformat(b))
        for a, b, intent in signature
        if intent == "grid_requirement"
    ]
    for s in path.segments:
        if (
            s.main_assignment_id == record["assignment_id"]
            and s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
            and s.ends_at > at
        ):
            if not any(a <= max(at, s.starts_at) and s.ends_at <= b for a, b in allowed):
                return False
    return True


def locked_candidates(
    portfolio: MainChargeComparablePortfolio, records: list[dict[str, Any]], at: datetime
) -> set[str]:
    paths = {p.path_id: p for p in portfolio.candidate_set.energy_paths}
    return {
        c.candidate_id
        for c in portfolio.candidate_set.candidates
        if c.candidate_id == portfolio.incumbent_candidate_id
        or all(respects_choice(paths[c.energy_path_id], r, at) for r in records)
    }


def _summary(
    source: MainChargeCandidateSource,
    label: str,
    day_start: datetime,
    day_end: datetime,
    timezone: ZoneInfo,
) -> dict[str, Any]:
    w = source.window
    assert w is not None
    rows = [i for i in w.projection.intervals if day_start <= i.starts_at < day_end]
    if not rows:
        raise ValueError("route comparison requires projection evidence inside the delivery day")
    return {
        "label": label,
        # Presentation evidence only. Keep the candidate's complete schedule,
        # including non-charging actions, separate from the consent signature.
        "timeline": {
            "candidate_id": source.candidate_id,
            "schedule_id": w.schedule.schedule_id,
            "snapshot_id": w.schedule.snapshot_id,
            "starts_at": w.schedule.horizon_start.isoformat(),
            "ends_at": w.schedule.horizon_end.isoformat(),
            "segments": [
                {
                    "starts_at": interval.starts_at.isoformat(),
                    "ends_at": interval.ends_at.isoformat(),
                    "intent": interval.intent.value,
                    "storage_export_target_wh": interval.storage_export_target_wh,
                }
                for interval in w.schedule.intervals[:512]
            ],
            "truncated": len(w.schedule.intervals) > 512,
            "total_segments": len(w.schedule.intervals),
        },
        "main_signature": main_signature(w),
        "windows": [
            f"{s.starts_at.astimezone(timezone):%d-%m %H:%M}–{s.ends_at.astimezone(timezone):%H:%M}"
            for s in w.main_segments
        ],
        "grid_import_kwh": sum(i.grid_to_household_wh + i.grid_to_storage_input_wh for i in rows)
        / 1000,
        "pv_storage_kwh": sum(i.pv_to_storage_input_wh for i in rows) / 1000,
        "terminal_energy_kwh": rows[-1].storage_energy_at_end_wh / 1000,
        "terminal_soc": rows[-1].storage_energy_at_end_wh / w.target_storage_energy_wh * 100,
        "acquisition_eur_per_stored_kwh": source.financial.acquisition_eur_per_stored_kwh,
    }


def prepare_offer(
    portfolio: MainChargeComparablePortfolio,
    winner_id: str,
    owner: DailyChargeAssignment,
    at: datetime,
) -> tuple[dict[str, Any], datetime] | None:
    """Use already simulated, valid candidates with strictly more PV storage."""
    winner = next((s for s in portfolio.sources if s.candidate_id == winner_id), None)
    if winner is None or winner.window is None:
        return None
    timezone = ZoneInfo(owner.timezone)
    night = any(
        s.intent.value == "grid_requirement"
        and (
            s.starts_at.astimezone(timezone).hour < 7 or s.starts_at.astimezone(timezone).hour >= 22
        )
        for s in winner.window.main_segments
    )
    if not night:
        return None
    automatic = _summary(
        winner, "Automatische nachtroute", owner.starts_at, owner.ends_at, timezone
    )
    valid = {
        o.candidate_id
        for o in portfolio.outcome_set.outcomes
        if o.validity is CandidateValidity.VALID
    }
    alternatives = {}
    for source in portfolio.sources:
        if source.candidate_id not in valid or source.window is None:
            continue
        summary = _summary(
            source, "Route met meer zonnestroom", owner.starts_at, owner.ends_at, timezone
        )
        if summary["pv_storage_kwh"] > automatic["pv_storage_kwh"] + 0.001:
            # A reply must arrive before the first changed action, not merely
            # before the PV window. Expired alternatives cannot undo execution.
            a, b = winner.window.schedule.intervals, source.window.schedule.intervals
            differences = [
                max(x.starts_at, y.starts_at)
                for x in a
                for y in b
                if max(x.starts_at, y.starts_at) < min(x.ends_at, y.ends_at)
                and (x.intent, x.storage_export_target_wh) != (y.intent, y.storage_export_target_wh)
            ]
            expires = min(differences) if differences else at
            if expires > at:
                alternatives[source.candidate_id] = (summary, expires)
    if not alternatives:
        return {
            "automatic": automatic,
            "alternative": None,
            "delivery_date": owner.delivery_date.isoformat(),
        }, min(s.starts_at for s in winner.window.main_segments)
    subset = constrain(portfolio, set(alternatives), "not_more_pv_storage")
    choice = EvaluationEngine().evaluate(
        subset.candidate_set, subset.strategy, subset.outcome_set, created_at=at
    )
    if choice.record.winning_candidate_id not in alternatives:
        return None
    summary, expires = alternatives[choice.record.winning_candidate_id]
    return {
        "automatic": automatic,
        "alternative": summary,
        "delivery_date": owner.delivery_date.isoformat(),
    }, expires
