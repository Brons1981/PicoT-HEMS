"""Selected market revision evidence, without economics or execution authority."""

from dataclasses import dataclass

from picot.domain.evaluation import EvaluationRecord
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.market_plan_binding import MarketPlanBinding


@dataclass(frozen=True, slots=True)
class MarketPlanRevision:
    previous_binding: MarketPlanBinding
    previous_active_plan_id: str
    evaluation_record: EvaluationRecord
    winning_energy_path_id: str
    new_binding: MarketPlanBinding | None
    reason: str

    def __post_init__(self) -> None:
        if not all(v.strip() for v in (
            self.previous_active_plan_id, self.winning_energy_path_id, self.reason,
        )):
            raise ValueError("market revision requires explicit selected lineage")
        record = self.evaluation_record
        if (record.winning_candidate_id is None
                or record.winning_candidate_id not in record.evaluated_candidate_ids
                or any(i.candidate_id == record.winning_candidate_id
                       for i in record.invalid_candidates)):
            raise ValueError("market revision requires a valid evaluated winner")
        if self.new_binding is not None and (
            self.new_binding.assignment_id != self.previous_binding.assignment_id
            or self.new_binding.execution_scope_id != self.previous_binding.execution_scope_id
            or self.new_binding.expected_export_wh != self.previous_binding.expected_export_wh
            or self.new_binding.cancelled_export_wh < self.previous_binding.cancelled_export_wh
            or self.new_binding.elapsed_planned_export_wh
            < self.previous_binding.elapsed_planned_export_wh
        ):
            raise ValueError("market revision cannot replace its identity or replenish export")

    def validate_plan(self, plan: ExecutionPlan) -> None:
        record = self.evaluation_record
        if (record.evaluation_id, record.snapshot_id, record.strategy_version,
            record.winning_candidate_id, record.created_at, self.winning_energy_path_id) != (
                plan.evaluation_id, plan.snapshot_id, plan.strategy_version,
                plan.winning_candidate_id, plan.created_at, plan.winning_energy_path_id,
        ) or self.previous_binding.execution_scope_id != plan.execution_scope_id:
            raise ValueError("market revision must match the canonical winning plan")
        if self.new_binding is not None and (
            self.new_binding.plan_id != plan.plan_id
            or self.new_binding.snapshot_id != plan.snapshot_id
        ):
            raise ValueError("market revision binding must match the winning plan")
