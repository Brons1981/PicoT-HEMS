"""Deterministic Winning Energy Path conversion defined by ADR-033."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from picot.domain.energy_path import PathSegment
from picot.domain.evaluation import EvaluationOutcomeStatus, EvaluationResult
from picot.domain.execution_plan import (
    ExecutionPlan,
    ExecutionPlanLifecycle,
    ExecutionPlanSegment,
    ExecutionPlanSet,
)

IMPLEMENTATION_VERSION = "execution-plan-builder-v1"


class ExecutionPlanBuilder:
    """Convert one successful Evaluation Result without changing its energy intent."""

    def build(
        self,
        evaluation_result: EvaluationResult,
        *,
        created_at: datetime,
        fallback_policy_id: str,
    ) -> ExecutionPlanSet:
        self._validate_input(evaluation_result, created_at, fallback_policy_id)

        candidate = evaluation_result.winning_candidate
        path = evaluation_result.winning_energy_path
        assert candidate is not None
        assert path is not None

        grouped: dict[str, list[PathSegment]] = {}
        for segment in path.segments:
            grouped.setdefault(segment.execution_scope_id, []).append(segment)

        plans = tuple(
            self._build_plan(
                evaluation_result,
                scope_id,
                grouped[scope_id],
                created_at,
                fallback_policy_id,
            )
            for scope_id in sorted(grouped)
        )
        plan_set_id = self._stable_id(
            "plan-set",
            path.snapshot_id,
            evaluation_result.record.evaluation_id,
            candidate.candidate_id,
            path.path_id,
            IMPLEMENTATION_VERSION,
        )
        return ExecutionPlanSet(
            plan_set_id=plan_set_id,
            schema_version=1,
            snapshot_id=path.snapshot_id,
            strategy_version=path.strategy_version,
            evaluation_id=evaluation_result.record.evaluation_id,
            winning_candidate_id=candidate.candidate_id,
            winning_energy_path_id=path.path_id,
            created_at=created_at,
            plans=plans,
            implementation_version=IMPLEMENTATION_VERSION,
        )

    @staticmethod
    def _validate_input(
        evaluation_result: EvaluationResult,
        created_at: datetime,
        fallback_policy_id: str,
    ) -> None:
        if evaluation_result.status is not EvaluationOutcomeStatus.WINNER_SELECTED:
            raise ValueError("Execution Plans require a winner-selected Evaluation Result.")
        candidate = evaluation_result.winning_candidate
        path = evaluation_result.winning_energy_path
        if candidate is None or path is None:
            raise ValueError("Execution Plans require Winning Candidate and Energy Path.")
        record = evaluation_result.record
        if record.winning_candidate_id != candidate.candidate_id:
            raise ValueError("Evaluation Record must reference the Winning Candidate.")
        if candidate.energy_path_id != path.path_id:
            raise ValueError("Winning Candidate must reference the Winning Energy Path.")
        if record.snapshot_id != path.snapshot_id:
            raise ValueError("Evaluation Record and Winning Energy Path snapshot must match.")
        if record.strategy_version != path.strategy_version:
            raise ValueError("Evaluation Record and Winning Energy Path strategy must match.")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Execution Plan creation time must be timezone-aware.")
        if created_at > path.horizon_end:
            raise ValueError("Execution Plan creation time may not exceed path horizon.")
        if not fallback_policy_id.strip():
            raise ValueError("Fallback policy ID must not be empty.")
        if any(segment.capability_id not in path.capability_ids for segment in path.segments):
            raise ValueError("Every Path Segment capability must be referenced by the path.")

    def _build_plan(
        self,
        evaluation_result: EvaluationResult,
        scope_id: str,
        source_segments: list[PathSegment],
        created_at: datetime,
        fallback_policy_id: str,
    ) -> ExecutionPlan:
        candidate = evaluation_result.winning_candidate
        path = evaluation_result.winning_energy_path
        assert candidate is not None
        assert path is not None

        ordered = sorted(
            source_segments,
            key=lambda item: (item.starts_at, item.segment_id),
        )
        plan_id = self._stable_id(
            "plan",
            path.snapshot_id,
            evaluation_result.record.evaluation_id,
            candidate.candidate_id,
            path.path_id,
            scope_id,
        )
        segments = tuple(
            ExecutionPlanSegment(
                segment_id=self._stable_id(
                    "execution-segment",
                    plan_id,
                    source.segment_id,
                ),
                source_path_segment_id=source.segment_id,
                order=index,
                starts_at=source.starts_at,
                ends_at=source.ends_at,
                primitive=source.primitive,
                capability_id=source.capability_id,
                purpose=source.purpose,
                evidence_ids=source.evidence_ids,
                requested_power_w=source.requested_power_w,
                soc_constraint=source.soc_constraint,
                energy_profile_id=source.energy_profile_id,
            )
            for index, source in enumerate(ordered, start=1)
        )
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version=1,
            revision=1,
            created_at=created_at,
            valid_from=path.horizon_start,
            valid_until=path.horizon_end,
            snapshot_id=path.snapshot_id,
            strategy_version=path.strategy_version,
            evaluation_id=evaluation_result.record.evaluation_id,
            winning_candidate_id=candidate.candidate_id,
            winning_energy_path_id=path.path_id,
            execution_scope_id=scope_id,
            mapping_version=path.mapping_version,
            lifecycle=ExecutionPlanLifecycle.PROPOSED,
            fallback_policy_id=fallback_policy_id,
            segments=segments,
        )

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = sha256("|".join(parts).encode()).hexdigest()[:16]
        return f"{prefix}-{digest}"
