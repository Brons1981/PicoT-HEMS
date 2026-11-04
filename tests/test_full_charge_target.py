"""A full charge target is normal completion, not an execution fault."""
from dataclasses import replace

import pytest
from test_soc_reserve_wait import discharge_run

from picot.domain.energy_path import SocConstraint
from picot.domain.execution_primitive import ExecutionPrimitive as P
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime


@pytest.mark.parametrize("primitive", [P.CHARGE_AT_POWER, P.BALANCE_CHARGE_ONLY])
def test_full_target_maps_to_nom_without_changing_plan(primitive):
    run = discharge_run(1.0, primitive)
    calls = []
    runtime = CanonicalExecutionRuntime(lambda *args: (
        calls.append(args) or CanonicalDispatchOutcome("dispatched", "nom")))
    result = runtime.apply(run)
    assert result.primitive_boundary.execution_reason == "execution_charge_target_reached"
    assert result.primitive_boundary.planned_primitive is P.BALANCE_BIDIRECTIONAL
    assert result.vendor_result.status == "dispatched"
    assert result.vendor_result.failure_reason is None
    assert result.execution_plan_set == run.execution_plan_set
    assert calls[0][0].primitive is P.BALANCE_BIDIRECTIONAL
    assert calls[0][0].requested_power_w is None


def test_lower_charge_ceiling_is_not_replaced_by_unbounded_nom():
    run = discharge_run(0.95, P.CHARGE_AT_POWER)
    plan = run.execution_plan_set.plans[0]
    segment = replace(plan.segments[0], soc_constraint=SocConstraint(0.1, 0.9))
    run = replace(run, execution_plan_set=replace(run.execution_plan_set,
        plans=(replace(plan, segments=(segment, *plan.segments[1:])),)))
    calls = []
    result = CanonicalExecutionRuntime(lambda *args: calls.append(args)).apply(run)
    assert result.vendor_result.failure_reason == "execution_soc_above_segment_maximum"
    assert calls == []


def test_missing_soc_cannot_claim_full_target():
    run = discharge_run(1.0, P.CHARGE_AT_POWER)
    run = replace(run, planning_input=replace(run.planning_input, current_storage_states=()))
    calls = []
    result = CanonicalExecutionRuntime(lambda *args: calls.append(args)).apply(run)
    assert result.vendor_result.failure_reason == "execution_soc_unavailable"
    assert calls == []


def test_full_target_nom_replacement_still_respects_ev_isolation():
    from test_ev_storage_execution_guard import policy

    run = discharge_run(1.0, P.CHARGE_AT_POWER)
    run = replace(run, planning_input=replace(run.planning_input,
        external_load_policy=policy(run.planning_input)))
    calls = []
    result = CanonicalExecutionRuntime(lambda *args: calls.append(args)).apply(run)
    assert result.primitive_boundary.planned_primitive is P.STANDBY
    assert result.primitive_boundary.execution_reason == "ev_storage_support_prohibited"
    assert result.vendor_result.status == "already_active"
    assert not calls


def test_full_target_requires_verified_nom_mapping():
    run = discharge_run(1.0, P.CHARGE_AT_POWER)
    evidence = run.planning_input.storage_mode_capability_evidence
    run = replace(run, planning_input=replace(run.planning_input,
        storage_mode_capability_evidence=replace(evidence, mappings=tuple(
            mapping for mapping in evidence.mappings
            if P.BALANCE_BIDIRECTIONAL not in mapping.primitives))))
    calls = []
    result = CanonicalExecutionRuntime(lambda *args: calls.append(args)).apply(run)
    assert "primitive_vendor_mapping_unavailable" in result.primitive_boundary.blockers
    assert not calls
