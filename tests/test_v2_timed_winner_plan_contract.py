from test_v2_delegated_storage_dry_run_integration import _run_with_mode

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.projection import project


def test_selected_zendure_winner_has_one_stable_timed_observer_plan() -> None:
    first = _run_with_mode()
    second = _run_with_mode()

    assert len(first.execution_plan_set.plans) == 1
    plan = first.execution_plan_set.plans[0]
    segment = plan.segments[0]

    assert plan.plan_id == second.execution_plan_set.plans[0].plan_id
    assert plan.execution_scope_id == "home-battery"
    assert plan.valid_from == segment.starts_at
    assert plan.valid_until == segment.ends_at
    assert plan.planned_primitive is ExecutionPrimitive.BALANCE_CHARGE_ONLY
    assert plan.lifecycle_status == "due_observer_only"
    assert plan.observer_only is True


def test_projection_exposes_plan_window_mode_and_final_safety_blocker() -> None:
    projection = project(_run_with_mode())
    plan_card = projection.cards[4]
    primitive_card = projection.cards[6]

    assert plan_card.state == "observer_only"
    assert plan_card.attributes["plan_count"] == 1
    planned = plan_card.attributes["plans"][0]
    assert planned["valid_from"] == planned["segments"][0]["starts_at"]
    assert planned["valid_until"] == planned["segments"][0]["ends_at"]
    assert planned["planned_primitive"] == "balance_charge_only"
    assert planned["planned_vendor_mode"] == "Alleen slim opladen"
    assert planned["lifecycle_status"] == "due_observer_only"

    assert primitive_card.state == "dry_run_blocked"
    assert primitive_card.attributes["blockers"][-1] == (
        "observer_only_authority"
    )
