"""Compact read-only dashboard projection for the daily observer."""

from __future__ import annotations

from picot.domain.daily_reference_candidate import DailyReferenceCandidate
from picot.domain.daily_reference_intent import DailyReferenceIntentSchedule
from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
from picot.v2.independent_daily_observer_runtime import (
    DailyObserverRuntimeOutcome,
)


def build_daily_observer_dashboard_view(
    outcome: DailyObserverRuntimeOutcome,
) -> dict[str, object]:
    """Project one passive outcome without exposing control authority."""
    base: dict[str, object] = {
        "available": outcome.status == "completed",
        "status": outcome.status,
        "reason": outcome.reason,
        "snapshot_id": outcome.snapshot_id,
        "run_id": outcome.run_id,
        "captured_at": outcome.captured_at.isoformat(),
        "duration_ms": outcome.duration_ms,
        "observer_only": True,
        "selection_permitted": False,
        "commitment_permitted": False,
        "method_version": outcome.method_version,
        "objective": None,
        "direction": None,
        "best_observation_ids": [],
        "candidates": [],
    }
    if outcome.observation is None:
        return base

    observation = outcome.observation
    evaluation = observation.observer_result.evaluation
    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in observation.observer_result.candidate_set.candidates
    }
    schedules_by_id = {
        schedule.schedule_id: schedule
        for schedule in observation.strategy_space.schedules
    }
    base.update({
        "objective": evaluation.objective,
        "direction": evaluation.direction.value,
        "best_observation_ids": list(evaluation.best_candidate_ids),
        "candidates": [
            _candidate_view(
                observation,
                record.candidate_id,
                record.intent_schedule_id,
                record.admissible,
                tuple(reason.value for reason in record.exclusion_reasons),
                record.worst_case_financial_result_eur,
                record.minimum_confidence,
                record.best_observation,
                candidates_by_id,
                schedules_by_id,
            )
            for record in evaluation.records
        ],
    })
    return base


def _candidate_view(
    observation: DailyReferenceStrategyObservation,
    candidate_id: str,
    schedule_id: str,
    admissible: bool,
    exclusion_reasons: tuple[str, ...],
    financial_result_eur: float,
    minimum_confidence: float,
    best_observation: bool,
    candidates_by_id: dict[str, DailyReferenceCandidate],
    schedules_by_id: dict[str, DailyReferenceIntentSchedule],
) -> dict[str, object]:
    candidate = candidates_by_id[candidate_id]
    schedule = schedules_by_id[schedule_id]
    return {
        "candidate_id": candidate_id,
        "family": candidate.family.value,
        "intent_schedule_id": schedule_id,
        "admissible": admissible,
        "exclusion_reasons": list(exclusion_reasons),
        "worst_case_financial_result_eur": financial_result_eur,
        "minimum_confidence": minimum_confidence,
        "best_observation": best_observation,
        "complete_across_scenarios": candidate.complete_across_scenarios,
        "target_reached_across_scenarios": (
            candidate.target_reached_across_scenarios
        ),
        "reserve_respected_across_scenarios": (
            candidate.reserve_respected_across_scenarios
        ),
        "intents_used": [intent.value for intent in candidate.intents_used],
        "horizon_start": schedule.horizon_start.isoformat(),
        "horizon_end": schedule.horizon_end.isoformat(),
        "intent_intervals": [
            {
                "starts_at": interval.starts_at.isoformat(),
                "ends_at": interval.ends_at.isoformat(),
                "intent": interval.intent.value,
                "storage_export_target_wh": interval.storage_export_target_wh,
            }
            for interval in schedule.intervals
        ],
        "scenarios": [
            {
                "scenario": scenario.scenario.value,
                "target_reached_at": (
                    scenario.target_reached_at.isoformat()
                    if scenario.target_reached_at is not None
                    else None
                ),
                "target_held_at_horizon_end": (
                    scenario.target_held_at_horizon_end
                ),
                "reserve_respected": scenario.reserve_respected,
                "storage_energy_at_horizon_end_wh": (
                    scenario.storage_energy_at_horizon_end_wh
                ),
                "net_financial_result_eur": scenario.net_financial_result_eur,
                "confidence": scenario.confidence,
            }
            for scenario in candidate.scenario_outcomes
        ],
        "source_observation_id": observation.observation_id,
    }
