"""Immutable Candidate Engine records defined by ADR-024.

This first slice defines the Candidate envelope and its traceability. Concrete
household energy-path construction is added only when its supporting domain
models and capability records are available.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CandidateFamily(StrEnum):
    """Representative scenario families preserved during controlled branching."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    PRIORITY_FIRST = "priority_first"
    PV_FIRST = "pv_first"
    COST_FIRST = "cost_first"
    RESERVE_FIRST = "reserve_first"
    LIMITED_POWER_PARALLEL = "limited_power_parallel"


class CandidateExclusionKind(StrEnum):
    """Objective reasons why a scenario family did not become a candidate."""

    OBJECTIVELY_IMPOSSIBLE = "objectively_impossible"
    HARD_BOUNDARY = "hard_boundary"
    USER_RULE = "user_rule"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    DOMINATED = "dominated"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One complete scenario reference with immutable ADR-024 traceability."""

    candidate_id: str
    snapshot_id: str
    family: CandidateFamily
    energy_path_id: str
    opportunity_ids: tuple[str, ...]
    constraint_ids: tuple[str, ...]
    strategy_version: int
    capability_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        for value, label in (
            (self.candidate_id, "Candidate ID"),
            (self.snapshot_id, "Snapshot ID"),
            (self.energy_path_id, "Energy path ID"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.strategy_version < 1:
            raise ValueError("Strategy version must be at least 1.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Candidate confidence must be between 0.0 and 1.0.")
        self._require_unique_non_empty(self.opportunity_ids, "opportunity")
        self._require_unique_non_empty(self.constraint_ids, "constraint")
        self._require_unique_non_empty(self.capability_ids, "capability")
        if any(not assumption.strip() for assumption in self.assumptions):
            raise ValueError("Candidate assumptions must not be empty.")

    @staticmethod
    def _require_unique_non_empty(values: tuple[str, ...], label: str) -> None:
        if any(not value.strip() for value in values):
            raise ValueError(f"Candidate {label} IDs must not be empty.")
        if len(values) != len(set(values)):
            raise ValueError(f"Candidate {label} IDs must be unique.")


@dataclass(frozen=True, slots=True)
class CandidateExclusion:
    """Traceable reason why one representative scenario family was rejected."""

    family: CandidateFamily
    kind: CandidateExclusionKind
    reason: str
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("Candidate exclusion reason must not be empty.")
        if any(not source_id.strip() for source_id in self.source_ids):
            raise ValueError("Candidate exclusion source IDs must not be empty.")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Candidate exclusion source IDs must be unique.")


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """Finite immutable Candidate Engine output for one planning snapshot."""

    snapshot_id: str
    strategy_version: int
    candidates: tuple[Candidate, ...]
    exclusions: tuple[CandidateExclusion, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("Candidate Set snapshot ID must not be empty.")
        if self.strategy_version < 1:
            raise ValueError("Candidate Set strategy version must be at least 1.")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Each candidate ID may appear only once.")
        if any(candidate.snapshot_id != self.snapshot_id for candidate in self.candidates):
            raise ValueError("Every candidate must reference the Candidate Set snapshot.")
        if any(
            candidate.strategy_version != self.strategy_version
            for candidate in self.candidates
        ):
            raise ValueError("Every candidate must use the Candidate Set strategy version.")
