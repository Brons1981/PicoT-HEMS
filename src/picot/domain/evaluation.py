"""Immutable Evaluation Engine records defined by ADR-032."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from picot.domain.objectives import ObjectiveKind

if TYPE_CHECKING:
    from picot.domain.candidate import Candidate
    from picot.domain.energy_path import EnergyPath


class ComparisonDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class CandidateValidity(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class RelativeResult(StrEnum):
    BETTER = "better"
    EQUAL = "equal"
    WORSE = "worse"
    UNAVAILABLE = "unavailable"


class TieBreakKind(StrEnum):
    CONFIDENCE = "confidence"
    RECOVERABILITY = "recoverability"
    EXECUTION_COMPLEXITY = "execution_complexity"
    EXPECTED_SWITCHING_COUNT = "expected_switching_count"
    CANDIDATE_IDENTIFIER = "candidate_identifier"


class EvaluationOutcomeStatus(StrEnum):
    WINNER_SELECTED = "winner_selected"
    NO_VALID_CANDIDATE = "no_valid_candidate"


@dataclass(frozen=True, slots=True)
class ObjectiveOutcome:
    objective: ObjectiveKind
    value: float
    direction: ComparisonDirection
    unit: str
    confidence: float
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.unit.strip():
            raise ValueError("Objective outcome unit must not be empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Objective outcome confidence must be between 0.0 and 1.0.")
        if any(not item.strip() for item in self.evidence_ids):
            raise ValueError("Objective outcome evidence IDs must not be empty.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Objective outcome evidence IDs must be unique.")


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    candidate_id: str
    objective_outcomes: tuple[ObjectiveOutcome, ...]
    confidence: float
    recoverability: float | None
    execution_complexity: int
    expected_switching_count: int | None
    complexity_version: str
    validity: CandidateValidity
    invalidity_reasons: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("Candidate outcome candidate ID must not be empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Candidate outcome confidence must be between 0.0 and 1.0.")
        if self.recoverability is not None and not 0.0 <= self.recoverability <= 1.0:
            raise ValueError("Recoverability must be between 0.0 and 1.0.")
        if self.execution_complexity < 0:
            raise ValueError("Execution complexity must not be negative.")
        if self.expected_switching_count is not None and self.expected_switching_count < 0:
            raise ValueError("Expected switching count must not be negative.")
        if not self.complexity_version.strip():
            raise ValueError("Complexity version must not be empty.")
        objectives = [item.objective for item in self.objective_outcomes]
        if len(objectives) != len(set(objectives)):
            raise ValueError("Each objective may appear only once per Candidate Outcome.")
        if self.validity is CandidateValidity.INVALID and not self.invalidity_reasons:
            raise ValueError("Invalid Candidate Outcomes require at least one reason.")
        if self.validity is CandidateValidity.VALID and self.invalidity_reasons:
            raise ValueError("Valid Candidate Outcomes may not contain invalidity reasons.")


@dataclass(frozen=True, slots=True)
class CandidateOutcomeSet:
    snapshot_id: str
    strategy_version: int
    candidate_set_reference: str
    outcomes: tuple[CandidateOutcome, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("Candidate Outcome Set snapshot ID must not be empty.")
        if self.strategy_version < 1:
            raise ValueError("Candidate Outcome Set strategy version must be at least 1.")
        if not self.candidate_set_reference.strip():
            raise ValueError("Candidate Set reference must not be empty.")
        ids = [item.candidate_id for item in self.outcomes]
        if len(ids) != len(set(ids)):
            raise ValueError("Each Candidate Outcome ID may appear only once.")


@dataclass(frozen=True, slots=True)
class CandidateComparisonValue:
    candidate_id: str
    value: float | int | str | None
    result: RelativeResult


@dataclass(frozen=True, slots=True)
class ObjectiveComparisonRecord:
    objective: ObjectiveKind
    configured_weight: int
    direction: ComparisonDirection | None
    unit: str | None
    values: tuple[CandidateComparisonValue, ...]
    retained_candidate_ids: tuple[str, ...]
    available: bool
    decisive: bool


@dataclass(frozen=True, slots=True)
class TieBreakRecord:
    kind: TieBreakKind
    values: tuple[CandidateComparisonValue, ...]
    retained_candidate_ids: tuple[str, ...]
    available: bool
    decisive: bool


@dataclass(frozen=True, slots=True)
class InvalidCandidateRecord:
    candidate_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    evaluation_id: str
    schema_version: int
    snapshot_id: str
    strategy_version: int
    candidate_set_reference: str
    evaluated_candidate_ids: tuple[str, ...]
    invalid_candidates: tuple[InvalidCandidateRecord, ...]
    strategic_objective_order: tuple[ObjectiveKind, ...]
    objective_comparisons: tuple[ObjectiveComparisonRecord, ...]
    tie_breaks: tuple[TieBreakRecord, ...]
    decisive_step: str | None
    winning_candidate_id: str | None
    created_at: datetime
    implementation_version: str

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip():
            raise ValueError("Evaluation ID must not be empty.")
        if self.schema_version < 1:
            raise ValueError("Evaluation schema version must be at least 1.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Evaluation creation time must be timezone-aware.")
        if not self.implementation_version.strip():
            raise ValueError("Evaluation implementation version must not be empty.")


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    status: EvaluationOutcomeStatus
    record: EvaluationRecord
    winning_candidate: Candidate | None
    winning_energy_path: EnergyPath | None

    def __post_init__(self) -> None:
        has_winner = self.winning_candidate is not None and self.winning_energy_path is not None
        if self.status is EvaluationOutcomeStatus.WINNER_SELECTED and not has_winner:
            raise ValueError("Winner-selected results require Candidate and Energy Path.")
        if self.status is EvaluationOutcomeStatus.NO_VALID_CANDIDATE and has_winner:
            raise ValueError("No-valid-candidate results may not contain a winner.")
        if has_winner:
            assert self.winning_candidate is not None
            assert self.winning_energy_path is not None
            if self.winning_candidate.energy_path_id != self.winning_energy_path.path_id:
                raise ValueError("Winning Candidate and Energy Path must reference each other.")
