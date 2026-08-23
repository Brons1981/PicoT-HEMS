"""Independent candidates derived exclusively from a complete daily reference run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.daily_reference_simulation import PVScenario


class DailyReferenceCandidateFamily(StrEnum):
    """Physical intent families proven by the independent simulator."""

    NOM_FULL_HORIZON = "nom_full_horizon"
    HOUSEHOLD_SUPPORT_ONLY = "household_support_only"
    NOM = "nom"
    STANDBY = "standby"
    GRID_REQUIREMENT = "grid_requirement"
    STORAGE_EXPORT = "storage_export"
    MIXED_SCHEDULE = "mixed_schedule"


@dataclass(frozen=True, slots=True)
class DailyReferenceCandidateScenario:
    """One uncertainty outcome retained inside a reference candidate."""

    scenario: PVScenario
    trajectory_id: str
    physically_complete: bool
    target_reached_during_horizon: bool
    target_reached_at: datetime | None
    target_held_at_horizon_end: bool
    reserve_respected: bool
    storage_energy_at_horizon_end_wh: float
    net_financial_result_eur: float
    confidence: float

    def __post_init__(self) -> None:
        if not self.trajectory_id.strip() or not self.physically_complete:
            raise ValueError("Reference candidate requires a complete trajectory.")
        if self.target_reached_during_horizon != (self.target_reached_at is not None):
            raise ValueError("Reference candidate target outcome and time must agree.")
        if self.storage_energy_at_horizon_end_wh < 0.0:
            raise ValueError("Reference candidate storage energy must not be negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Reference candidate confidence must be between 0.0 and 1.0.")


@dataclass(frozen=True, slots=True)
class DailyReferenceCandidate:
    """Complete unranked candidate retaining all uncertainty outcomes."""

    candidate_id: str
    source_run_id: str
    snapshot_id: str
    family: DailyReferenceCandidateFamily
    scenario_outcomes: tuple[DailyReferenceCandidateScenario, ...]
    complete_across_scenarios: bool
    target_reached_across_scenarios: bool
    target_held_across_scenarios: bool
    reserve_respected_across_scenarios: bool
    worst_case_financial_result_eur: float
    minimum_confidence: float
    observer_only: bool
    selection_eligible: bool
    method_version: str
    intent_schedule_id: str = "nom-full-horizon"
    intents_used: tuple[DailyStorageIntent, ...] = (DailyStorageIntent.NOM,)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.source_run_id.strip():
            raise ValueError("Reference candidate identity must be explicit.")
        if not self.snapshot_id.strip() or not self.method_version.strip():
            raise ValueError("Reference candidate lineage must be explicit.")
        if not self.intent_schedule_id.strip() or not self.intents_used:
            raise ValueError("Reference candidate intent schedule must be explicit.")
        if len(self.intents_used) != len(set(self.intents_used)):
            raise ValueError("Reference candidate intents must be unique.")
        scenarios = tuple(item.scenario for item in self.scenario_outcomes)
        if set(scenarios) != set(PVScenario) or len(scenarios) != len(PVScenario):
            raise ValueError("Reference candidate requires lower, central and upper.")
        if self.complete_across_scenarios != all(
            item.physically_complete for item in self.scenario_outcomes
        ):
            raise ValueError("Reference candidate completeness does not reconcile.")
        if self.target_reached_across_scenarios != all(
            item.target_reached_during_horizon for item in self.scenario_outcomes
        ):
            raise ValueError("Reference candidate target reach does not reconcile.")
        if self.target_held_across_scenarios != all(
            item.target_held_at_horizon_end for item in self.scenario_outcomes
        ):
            raise ValueError("Reference candidate target hold does not reconcile.")
        if self.reserve_respected_across_scenarios != all(
            item.reserve_respected for item in self.scenario_outcomes
        ):
            raise ValueError("Reference candidate reserve outcome does not reconcile.")
        if self.worst_case_financial_result_eur != min(
            item.net_financial_result_eur for item in self.scenario_outcomes
        ):
            raise ValueError("Reference candidate worst financial result does not reconcile.")
        if self.minimum_confidence != min(
            item.confidence for item in self.scenario_outcomes
        ):
            raise ValueError("Reference candidate confidence does not reconcile.")
        if not self.observer_only or self.selection_eligible:
            raise ValueError("Reference candidate must remain observer-only and unselected.")


@dataclass(frozen=True, slots=True)
class DailyReferenceCandidateSet:
    """Candidate Engine output that cannot rank or promote candidates."""

    candidate_set_id: str
    source_run_id: str
    snapshot_id: str
    candidates: tuple[DailyReferenceCandidate, ...]
    observer_only: bool
    ranking_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.candidate_set_id.strip() or not self.source_run_id.strip():
            raise ValueError("Reference candidate set identity must be explicit.")
        if not self.snapshot_id.strip() or not self.method_version.strip():
            raise ValueError("Reference candidate set lineage must be explicit.")
        if not self.candidates:
            raise ValueError("Reference candidate set must contain proven candidates.")
        if any(item.source_run_id != self.source_run_id for item in self.candidates):
            raise ValueError("Reference candidates must share one source run.")
        if any(item.snapshot_id != self.snapshot_id for item in self.candidates):
            raise ValueError("Reference candidates must share one snapshot.")
        if not self.observer_only or self.ranking_permitted:
            raise ValueError("Reference candidate set must remain observer-only and unranked.")


@dataclass(frozen=True, slots=True)
class DailyReferencePortfolioCandidateSet:
    """One unranked candidate per complete portfolio strategy result."""

    candidate_set_id: str
    source_portfolio_id: str
    snapshot_id: str
    candidates: tuple[DailyReferenceCandidate, ...]
    observer_only: bool
    ranking_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if not self.candidate_set_id.strip() or not self.source_portfolio_id.strip():
            raise ValueError("Portfolio candidate set identity must be explicit.")
        if not self.snapshot_id.strip() or not self.method_version.strip():
            raise ValueError("Portfolio candidate set lineage must be explicit.")
        if not self.candidates:
            raise ValueError("Portfolio candidate set requires proven candidates.")
        schedule_ids = tuple(item.intent_schedule_id for item in self.candidates)
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("Portfolio candidates must have unique intent schedules.")
        if any(item.snapshot_id != self.snapshot_id for item in self.candidates):
            raise ValueError("Portfolio candidates must share one snapshot.")
        if not self.observer_only or self.ranking_permitted:
            raise ValueError("Portfolio candidates must remain observer-only and unranked.")
