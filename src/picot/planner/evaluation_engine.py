"""Deterministic Candidate comparison defined by ADR-026 and ADR-032."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from hashlib import sha256

from picot.domain.candidate import CandidateSet
from picot.domain.evaluation import (
    CandidateComparisonValue,
    CandidateOutcome,
    CandidateOutcomeSet,
    CandidateValidity,
    ComparisonDirection,
    EvaluationOutcomeStatus,
    EvaluationRecord,
    EvaluationResult,
    InvalidCandidateRecord,
    ObjectiveComparisonRecord,
    RelativeResult,
    TieBreakKind,
    TieBreakRecord,
)
from picot.domain.objectives import ObjectiveKind, PlannerStrategy

IMPLEMENTATION_VERSION = "evaluation-v1"


class EvaluationEngine:
    """Compare supplied Candidate Outcomes without simulation or hidden scoring."""

    @staticmethod
    def candidate_set_reference(candidate_set: CandidateSet) -> str:
        joined = "|".join(candidate.candidate_id for candidate in candidate_set.candidates)
        digest = sha256(f"{candidate_set.snapshot_id}|{joined}".encode()).hexdigest()[:16]
        return f"candidate-set-{digest}"

    def evaluate(
        self,
        candidate_set: CandidateSet,
        strategy: PlannerStrategy,
        outcomes: CandidateOutcomeSet,
        *,
        created_at: datetime,
    ) -> EvaluationResult:
        self._validate_atomic_inputs(candidate_set, strategy, outcomes, created_at)
        by_id = {item.candidate_id: item for item in outcomes.outcomes}
        valid_ids = [
            candidate.candidate_id
            for candidate in candidate_set.candidates
            if by_id[candidate.candidate_id].validity is CandidateValidity.VALID
        ]
        invalid = tuple(
            InvalidCandidateRecord(item.candidate_id, item.invalidity_reasons)
            for item in outcomes.outcomes
            if item.validity is CandidateValidity.INVALID
        )
        objective_order = tuple(
            item.objective
            for item in sorted(
                strategy.objectives,
                key=lambda item: (-item.weight.value, item.objective.value),
            )
        )
        objective_records: list[ObjectiveComparisonRecord] = []
        tie_records: list[TieBreakRecord] = []
        remaining = list(valid_ids)
        decisive_step: str | None = None

        if remaining:
            for objective in objective_order:
                weight = strategy.weight_for(objective).value
                objective_record, retained = self._compare_objective(
                    objective,
                    weight,
                    remaining,
                    by_id,
                )
                objective_records.append(objective_record)
                if weight > 0 and objective_record.available:
                    remaining = retained
                    if len(remaining) == 1:
                        decisive_step = f"objective:{objective.value}"
                        objective_records[-1] = self._mark_objective_decisive(
                            objective_record
                        )
                        break

        if len(remaining) > 1:
            remaining, tie_records, decisive_step = self._apply_tie_breaks(remaining, by_id)

        winner_id = remaining[0] if len(remaining) == 1 else None
        evaluation_id = self._evaluation_id(
            candidate_set,
            outcomes.candidate_set_reference,
            strategy.strategy_version,
        )
        evaluation_record = EvaluationRecord(
            evaluation_id=evaluation_id,
            schema_version=1,
            snapshot_id=candidate_set.snapshot_id,
            strategy_version=strategy.strategy_version,
            candidate_set_reference=outcomes.candidate_set_reference,
            evaluated_candidate_ids=tuple(
                candidate.candidate_id for candidate in candidate_set.candidates
            ),
            invalid_candidates=invalid,
            strategic_objective_order=objective_order,
            objective_comparisons=tuple(objective_records),
            tie_breaks=tuple(tie_records),
            decisive_step=decisive_step,
            winning_candidate_id=winner_id,
            created_at=created_at,
            implementation_version=IMPLEMENTATION_VERSION,
        )
        if winner_id is None:
            return EvaluationResult(
                status=EvaluationOutcomeStatus.NO_VALID_CANDIDATE,
                record=evaluation_record,
                winning_candidate=None,
                winning_energy_path=None,
            )
        candidate = next(
            item for item in candidate_set.candidates if item.candidate_id == winner_id
        )
        path = next(
            item
            for item in candidate_set.energy_paths
            if item.path_id == candidate.energy_path_id
        )
        return EvaluationResult(
            status=EvaluationOutcomeStatus.WINNER_SELECTED,
            record=evaluation_record,
            winning_candidate=candidate,
            winning_energy_path=path,
        )

    def _validate_atomic_inputs(
        self,
        candidate_set: CandidateSet,
        strategy: PlannerStrategy,
        outcomes: CandidateOutcomeSet,
        created_at: datetime,
    ) -> None:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Evaluation creation time must be timezone-aware.")
        if outcomes.snapshot_id != candidate_set.snapshot_id:
            raise ValueError("Candidate Outcome Set must match Candidate Set snapshot.")
        if outcomes.strategy_version != candidate_set.strategy_version:
            raise ValueError("Candidate Outcome Set must match Candidate Set strategy version.")
        if strategy.strategy_version != candidate_set.strategy_version:
            raise ValueError("Planner Strategy must match Candidate Set strategy version.")
        expected_reference = self.candidate_set_reference(candidate_set)
        if outcomes.candidate_set_reference != expected_reference:
            raise ValueError("Candidate Outcome Set reference must match Candidate Set.")
        candidate_ids = {item.candidate_id for item in candidate_set.candidates}
        outcome_ids = {item.candidate_id for item in outcomes.outcomes}
        if candidate_ids != outcome_ids:
            raise ValueError("Candidate IDs and Candidate Outcome IDs must match exactly.")
        self._validate_objective_contracts(outcomes.outcomes)

    @staticmethod
    def _validate_objective_contracts(outcomes: tuple[CandidateOutcome, ...]) -> None:
        contracts: dict[ObjectiveKind, tuple[ComparisonDirection, str]] = {}
        for outcome in outcomes:
            for item in outcome.objective_outcomes:
                contract = (item.direction, item.unit)
                existing = contracts.setdefault(item.objective, contract)
                if existing != contract:
                    raise ValueError("Objective direction and unit must match across Candidates.")

    def _compare_objective(
        self,
        objective: ObjectiveKind,
        weight: int,
        candidate_ids: list[str],
        outcomes: dict[str, CandidateOutcome],
    ) -> tuple[ObjectiveComparisonRecord, list[str]]:
        values = []
        direction: ComparisonDirection | None = None
        unit: str | None = None
        for candidate_id in candidate_ids:
            match = next(
                (
                    item
                    for item in outcomes[candidate_id].objective_outcomes
                    if item.objective is objective
                ),
                None,
            )
            if match is None:
                unavailable = tuple(
                    CandidateComparisonValue(item, None, RelativeResult.UNAVAILABLE)
                    for item in candidate_ids
                )
                return (
                    ObjectiveComparisonRecord(
                        objective=objective,
                        configured_weight=weight,
                        direction=None,
                        unit=None,
                        values=unavailable,
                        retained_candidate_ids=tuple(candidate_ids),
                        available=False,
                        decisive=False,
                    ),
                    candidate_ids,
                )
            values.append((candidate_id, match.value))
            direction = match.direction
            unit = match.unit
        assert direction is not None
        raw_values = [value for _, value in values]
        best = (
            max(raw_values)
            if direction is ComparisonDirection.HIGHER_IS_BETTER
            else min(raw_values)
        )
        retained = [candidate_id for candidate_id, value in values if value == best]
        compared = tuple(
            CandidateComparisonValue(
                candidate_id,
                value,
                RelativeResult.BETTER
                if value == best and len(retained) == 1
                else (RelativeResult.EQUAL if value == best else RelativeResult.WORSE),
            )
            for candidate_id, value in values
        )
        return (
            ObjectiveComparisonRecord(
                objective=objective,
                configured_weight=weight,
                direction=direction,
                unit=unit,
                values=compared,
                retained_candidate_ids=tuple(retained),
                available=True,
                decisive=False,
            ),
            retained,
        )

    @staticmethod
    def _mark_objective_decisive(
        record: ObjectiveComparisonRecord,
    ) -> ObjectiveComparisonRecord:
        return ObjectiveComparisonRecord(
            objective=record.objective,
            configured_weight=record.configured_weight,
            direction=record.direction,
            unit=record.unit,
            values=record.values,
            retained_candidate_ids=record.retained_candidate_ids,
            available=record.available,
            decisive=True,
        )

    def _apply_tie_breaks(
        self,
        candidate_ids: list[str],
        outcomes: dict[str, CandidateOutcome],
    ) -> tuple[list[str], list[TieBreakRecord], str | None]:
        records: list[TieBreakRecord] = []
        remaining = candidate_ids
        getter_type = Callable[[CandidateOutcome], float | int | None]
        steps: tuple[tuple[TieBreakKind, bool, getter_type], ...] = (
            (TieBreakKind.CONFIDENCE, True, lambda item: item.confidence),
            (TieBreakKind.RECOVERABILITY, True, lambda item: item.recoverability),
            (
                TieBreakKind.EXECUTION_COMPLEXITY,
                False,
                lambda item: item.execution_complexity,
            ),
            (
                TieBreakKind.EXPECTED_SWITCHING_COUNT,
                False,
                lambda item: item.expected_switching_count,
            ),
        )
        for kind, higher, getter in steps:
            raw = [(candidate_id, getter(outcomes[candidate_id])) for candidate_id in remaining]
            if any(value is None for _, value in raw):
                records.append(
                    TieBreakRecord(
                        kind=kind,
                        values=tuple(
                            CandidateComparisonValue(item, value, RelativeResult.UNAVAILABLE)
                            for item, value in raw
                        ),
                        retained_candidate_ids=tuple(remaining),
                        available=False,
                        decisive=False,
                    )
                )
                continue
            values = [value for _, value in raw]
            best = max(values) if higher else min(values)
            retained = [item for item, value in raw if value == best]
            decisive = len(retained) == 1
            records.append(
                TieBreakRecord(
                    kind=kind,
                    values=tuple(
                        CandidateComparisonValue(
                            item,
                            value,
                            RelativeResult.BETTER
                            if value == best and decisive
                            else (
                                RelativeResult.EQUAL
                                if value == best
                                else RelativeResult.WORSE
                            ),
                        )
                        for item, value in raw
                    ),
                    retained_candidate_ids=tuple(retained),
                    available=True,
                    decisive=decisive,
                )
            )
            remaining = retained
            if decisive:
                return remaining, records, f"tie_break:{kind.value}"
        winner = min(remaining)
        records.append(
            TieBreakRecord(
                kind=TieBreakKind.CANDIDATE_IDENTIFIER,
                values=tuple(
                    CandidateComparisonValue(
                        item,
                        item,
                        RelativeResult.BETTER if item == winner else RelativeResult.WORSE,
                    )
                    for item in remaining
                ),
                retained_candidate_ids=(winner,),
                available=True,
                decisive=True,
            )
        )
        return [winner], records, "tie_break:candidate_identifier"

    @staticmethod
    def _evaluation_id(
        candidate_set: CandidateSet,
        candidate_set_reference: str,
        strategy_version: int,
    ) -> str:
        source = (
            f"{candidate_set.snapshot_id}|{candidate_set_reference}|"
            f"{strategy_version}|{IMPLEMENTATION_VERSION}"
        )
        return f"evaluation-{sha256(source.encode()).hexdigest()[:16]}"
