"""Display-only fresh committed-route expectation from the canonical simulator."""
from __future__ import annotations

from typing import Any

from picot.domain.execution_plan import ExecutionPlan
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def committed_soc_expectation(
    snapshot: PlanningInputSnapshot, plan: ExecutionPlan, conversion_model: StorageConversionModel,
) -> dict[str, Any]:
    """Never changes candidates, winning paths, monitor baselines or plan persistence."""
    at = snapshot.captured_at.isoformat()
    patch: dict[str, Any] = {
        'captured_at': at,
        'chosen_plan': {
            'plan_id': plan.plan_id, 'candidate_id': plan.winning_candidate_id,
            'energy_path_id': plan.winning_energy_path_id,
            'valid_from': plan.valid_from.isoformat(), 'valid_until': plan.valid_until.isoformat(),
        },
        'soc_timeline': [], 'soc_projection_captured_at': at,
        'soc_projection_retained': False,
        'soc_expectation': {'status': 'unavailable', 'plan_id': plan.plan_id,
                            'snapshot_id': snapshot.snapshot_id, 'run_id': snapshot.run_id},
    }
    try:
        projection, schedule = IndependentDailyReferenceAdapter().committed_plan_projection(
            snapshot=snapshot, plan=plan, conversion_model=conversion_model,
        )
        storage = next(s for s in snapshot.current_storage_states
                       if s.execution_scope_id == plan.execution_scope_id)
        patch['soc_timeline'] = [
            {'at': at, 'soc_percent': round(storage.current_soc * 100, 2), 'primitive': 'actual'},
            *({'at': interval.ends_at.isoformat(),
               'soc_percent': round(interval.storage_energy_at_end_wh /
                                    storage.usable_capacity_wh * 100, 2),
               'primitive': intent.intent.value}
              for interval, intent in zip(projection.intervals, schedule.intervals, strict=True)),
        ]
        patch['soc_expectation'].update(
            status='available', schedule_id=schedule.schedule_id,
            basis_method=projection.basis_method, measured_at=storage.measured_at.isoformat(),
        )
    except (ValueError, StopIteration) as exc:
        patch['soc_expectation']['reason'] = str(exc) or type(exc).__name__
    return patch
