"""The execution reserve stops discharge without rewriting the approved plan."""
from dataclasses import replace

import pytest
from test_v2_canonical_execution_runtime import _live_run

from picot.domain.energy_path import SocConstraint
from picot.domain.execution_primitive import ExecutionPrimitive as P
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime


def discharge_run(soc, primitive=P.BALANCE_DISCHARGE_ONLY):
    run = _live_run()
    plan = run.execution_plan_set.plans[0]
    segment = replace(plan.segments[0], primitive=primitive, soc_constraint=SocConstraint(0.1, 1),
                      requested_power_w=1200 if primitive is P.DISCHARGE_AT_POWER else None)
    return replace(
        run,
        planning_input=replace(run.planning_input, current_storage_states=tuple(
            replace(s, current_soc=soc) for s in run.planning_input.current_storage_states)),
        execution_plan_set=replace(run.execution_plan_set, plans=(replace(
            plan, segments=(segment, *plan.segments[1:])),)),
        primitive_boundary=replace(run.primitive_boundary, planned_primitive=primitive),
    )


@pytest.mark.parametrize("primitive", [P.BALANCE_DISCHARGE_ONLY, P.DISCHARGE_AT_POWER])
@pytest.mark.parametrize("soc", [0.01, 0.1])
def test_apply_waits_at_reserve_without_plan_change(soc, primitive):
    run = discharge_run(soc, primitive)
    calls = []
    runtime = CanonicalExecutionRuntime(lambda *args: calls.append(args))
    result = runtime.apply(run)
    assert result.vendor_result.status == "already_active"  # Standby already observed.
    assert result.primitive_boundary.planned_primitive is P.STANDBY
    assert result.primitive_boundary.execution_reason == "execution_soc_minimum_reached"
    assert not result.primitive_boundary.blockers
    assert result.execution_plan_set == run.execution_plan_set
    assert not calls


def test_missing_standby_mapping_remains_a_real_blocker():
    run = discharge_run(0.1)
    evidence = run.planning_input.storage_mode_capability_evidence
    run = replace(run, planning_input=replace(run.planning_input,
        storage_mode_capability_evidence=replace(evidence, mappings=tuple(
            m for m in evidence.mappings if P.STANDBY not in m.primitives))))
    calls = []
    result = CanonicalExecutionRuntime(lambda *args: calls.append(args)).apply(run)
    assert "primitive_vendor_mapping_unavailable" in result.primitive_boundary.blockers
    assert not calls


def test_above_reserve_keeps_discharge_and_missing_soc_is_not_a_wait():
    run = discharge_run(0.11)
    calls = []
    result = CanonicalExecutionRuntime(lambda *args: (
        calls.append(args) or CanonicalDispatchOutcome("dispatched", "test")
    )).apply(run)
    assert result.primitive_boundary.planned_primitive is P.BALANCE_DISCHARGE_ONLY
    assert calls[0][0].primitive is P.BALANCE_DISCHARGE_ONLY
    missing = replace(run, planning_input=replace(run.planning_input, current_storage_states=()))
    calls.clear()
    result = CanonicalExecutionRuntime(lambda *args: calls.append(args)).apply(missing)
    assert "execution_soc_unavailable" in result.primitive_boundary.blockers
    assert not calls
