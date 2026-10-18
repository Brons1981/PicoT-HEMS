from dataclasses import replace
from datetime import timedelta

import pytest
from test_v2_canonical_execution_runtime import _live_run

from picot.domain.execution_primitive import ExecutionPrimitive as P
from picot.domain.external_load_policy import ExternalLoadPolicy
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
    CommittedPlanSegment,
)


def policy(snapshot, *, controlled=False, power=2300):
    return ExternalLoadPolicy(
        "energy-devices:ev-session",
        "1",
        snapshot.captured_at,
        power,
        False,
        "home-battery",
        physical_evidence_available=True,
        exclusion_control_available=controlled,
    )


def runtime():
    calls = []
    return CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append((request, mapping))
            or CanonicalDispatchOutcome("dispatched", "ev-guard-command")
        )
    ), calls


@pytest.mark.parametrize(
    "requested,controlled,expected",
    [
        (P.BALANCE_BIDIRECTIONAL, False, P.BALANCE_CHARGE_ONLY),
        (P.BALANCE_DISCHARGE_ONLY, False, P.STANDBY),
        (P.DISCHARGE_AT_POWER, False, P.STANDBY),
        (P.DISCHARGE_AT_POWER, True, P.STANDBY),
        (P.BALANCE_BIDIRECTIONAL, True, P.BALANCE_BIDIRECTIONAL),
        (P.BALANCE_DISCHARGE_ONLY, True, P.BALANCE_DISCHARGE_ONLY),
        (P.CHARGE_AT_POWER, False, P.CHARGE_AT_POWER),
    ],
)
@pytest.mark.parametrize("fallback", [False, True])
def test_real_dispatch_path_isolates_ev(requested, controlled, expected, fallback):
    run = _live_run()
    run = replace(
        run,
        planning_input=replace(
            run.planning_input,
            external_load_policy=policy(run.planning_input, controlled=controlled),
        ),
        primitive_boundary=replace(
            run.primitive_boundary,
            planned_primitive=requested,
            current_vendor_mode="Nul op de meter",
        ),
        execution_record=replace(
            run.execution_record, status="live_fallback_ready" if fallback else "live_plan_ready"
        ),
    )
    executor, calls = runtime()
    result = executor.apply(run)
    assert result.primitive_boundary.planned_primitive is expected
    if calls:
        assert calls[0][0].primitive is expected
    else:
        assert result.vendor_result.status == "already_active"


def test_missing_measurement_cannot_resume_discharge_until_fresh_zero():
    source = _live_run().planning_input
    executor, _ = runtime()
    active = replace(source, external_load_policy=policy(source))
    assert executor._ev_primitive(active, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY
    missing = replace(source, external_load_policy=None)
    assert executor._ev_primitive(missing, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY
    zero = replace(source, external_load_policy=policy(source, power=0))
    assert (
        executor._ev_primitive(zero, "home-battery", P.BALANCE_DISCHARGE_ONLY)
        is P.BALANCE_DISCHARGE_ONLY
    )


def test_committed_boundary_uses_same_guard():
    source = _live_run().planning_input
    commitment = ActivePlanCommitment(
        execution_scope_id="home-battery",
        plan_id="ev-boundary",
        plan_revision=1,
        primitive="balance_discharge_only",
        source_policy="not_applicable",
        starts_at=source.captured_at,
        ends_at=source.captured_at + timedelta(hours=1),
        target_energy_wh=100,
        segments=(
            CommittedPlanSegment(
                source.captured_at,
                source.captured_at + timedelta(hours=1),
                "balance_discharge_only",
                None,
            ),
        ),
    )
    evidence = source.storage_mode_capability_evidence
    source = replace(
        source,
        external_load_policy=policy(source),
        active_plan_commitments=(commitment,),
        storage_mode_capability_evidence=replace(evidence, current_vendor_mode="Nul op de meter"),
    )
    executor, calls = runtime()
    result = executor.advance_committed_boundary(source, execution_enabled=True)
    assert result.status == "dispatched"
    assert result.reason == "ev_storage_support_prohibited"
    assert calls[0][0].primitive is P.STANDBY


def test_no_charge_only_mapping_falls_back_to_standby():
    source = _live_run().planning_input
    evidence = source.storage_mode_capability_evidence
    source = replace(
        source,
        external_load_policy=policy(source),
        storage_mode_capability_evidence=replace(
            evidence,
            mappings=tuple(
                m for m in evidence.mappings if P.BALANCE_CHARGE_ONLY not in m.primitives
            ),
        ),
    )
    executor, _ = runtime()
    assert executor._ev_primitive(source, "home-battery", P.BALANCE_BIDIRECTIONAL) is P.STANDBY


@pytest.mark.parametrize("state", ["planned", "active", "interrupted"])
def test_active_window_without_measurements_is_guarded_after_restart(state):
    source = _live_run().planning_input
    demand = replace(
        policy(source, power=0),
        physical_evidence_available=False,
        session_id="pending-ev",
        session_state=state,
        planned_start=source.captured_at,
        expected_duration_seconds=3600,
        remaining_energy_wh=2300,
        expected_power_w=2300,
    )
    source = replace(source, external_load_policy=demand)
    executor, _ = runtime()
    assert executor._ev_primitive(source, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY


def test_future_ev_window_does_not_block_household_support():
    source = _live_run().planning_input
    demand = replace(
        policy(source, power=0),
        physical_evidence_available=False,
        session_id="future-ev",
        session_state="planned",
        planned_start=source.captured_at + timedelta(hours=1),
        expected_duration_seconds=3600,
        remaining_energy_wh=2300,
        expected_power_w=2300,
    )
    source = replace(source, external_load_policy=demand)
    executor, _ = runtime()
    assert (
        executor._ev_primitive(source, "home-battery", P.BALANCE_BIDIRECTIONAL)
        is P.BALANCE_BIDIRECTIONAL
    )


def test_stale_control_authority_cannot_allow_nom():
    source = _live_run().planning_input
    source = replace(
        source,
        external_load_policy=replace(
            policy(source, controlled=True), measured_at=source.captured_at - timedelta(seconds=4)
        ),
    )
    executor, _ = runtime()
    assert (
        executor._ev_primitive(source, "home-battery", P.BALANCE_BIDIRECTIONAL)
        is P.BALANCE_CHARGE_ONLY
    )


def test_ev_exclusion_survives_restart_and_plan_clear(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / "commitments.json")
    source = _live_run().planning_input
    executor = CanonicalExecutionRuntime(dispatch=lambda *args: None, commitment_store=store)
    active = replace(source, external_load_policy=policy(source))
    assert executor._ev_primitive(active, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY
    store.clear_all()
    restored = CanonicalExecutionRuntime(
        dispatch=lambda *args: None,
        commitment_store=ActivePlanCommitmentStore(tmp_path / "commitments.json"),
    )
    missing = replace(source, external_load_policy=None)
    assert restored._ev_primitive(missing, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY
    zero = replace(source, external_load_policy=policy(source, power=0))
    restored._ev_primitive(zero, "home-battery", P.BALANCE_DISCHARGE_ONLY)
    assert store.load_ev_exclusion_scopes() == set()
    again = CanonicalExecutionRuntime(dispatch=lambda *args: None, commitment_store=store)
    assert (
        again._ev_primitive(missing, "home-battery", P.BALANCE_DISCHARGE_ONLY)
        is P.BALANCE_DISCHARGE_ONLY
    )


def test_failed_guard_persistence_is_retried_before_dispatch(tmp_path, monkeypatch):
    store = ActivePlanCommitmentStore(tmp_path / "commitments.json")
    source = _live_run().planning_input
    executor = CanonicalExecutionRuntime(dispatch=lambda *args: None, commitment_store=store)
    original = store.save_ev_exclusion_scopes
    attempts = []

    def save(scopes):
        attempts.append(set(scopes))
        if len(attempts) == 1:
            raise OSError("disk unavailable")
        original(scopes)

    monkeypatch.setattr(store, "save_ev_exclusion_scopes", save)
    active = replace(source, external_load_policy=policy(source))
    with pytest.raises(OSError, match="disk unavailable"):
        executor._ev_primitive(active, "home-battery", P.BALANCE_DISCHARGE_ONLY)
    missing = replace(source, external_load_policy=None)
    assert executor._ev_primitive(missing, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY
    assert len(attempts) == 2
    assert store.load_ev_exclusion_scopes() == {"home-battery"}


@pytest.mark.parametrize("missing_soc", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
def test_ev_stop_dispatches_at_full_or_unknown_soc(missing_soc, fallback):
    run = _live_run()
    source = run.planning_input
    states = (
        ()
        if missing_soc
        else tuple(replace(s, current_soc=1.0) for s in source.current_storage_states)
    )
    run = replace(
        run,
        planning_input=replace(
            source, current_storage_states=states, external_load_policy=policy(source)
        ),
        primitive_boundary=replace(
            run.primitive_boundary,
            planned_primitive=P.BALANCE_BIDIRECTIONAL,
            current_vendor_mode="Nul op de meter",
        ),
        execution_record=replace(
            run.execution_record, status="live_fallback_ready" if fallback else "live_plan_ready"
        ),
    )
    executor, calls = runtime()
    result = executor.apply(run)
    assert result.vendor_result.status == "dispatched"
    assert calls[0][0].primitive is P.STANDBY
    assert calls[0][1].fixed_value == "Standby"


def test_idle_ev_power_releases_after_fresh_confirmation_and_stays_released():
    source = _live_run().planning_input
    executor, _ = runtime()
    active = replace(source, external_load_policy=policy(source))
    assert executor._ev_primitive(active, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY
    for seconds, expected in [
        (0, P.STANDBY),
        (29, P.STANDBY),
        (30, P.BALANCE_DISCHARGE_ONLY),
        (60, P.BALANCE_DISCHARGE_ONLY),
    ]:
        current = replace(
            source,
            captured_at=source.captured_at + timedelta(seconds=seconds),
            storage_mode_capability_evidence=None,
            capability_snapshot_set=None,
        )
        current = replace(current, external_load_policy=policy(current, power=2.2))
        assert executor._ev_primitive(current, "home-battery", P.BALANCE_DISCHARGE_ONLY) is expected
    current = replace(current, external_load_policy=policy(current, power=6))
    assert executor._ev_primitive(current, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY


@pytest.mark.parametrize("interruption", ["missing", "stale", "unseparated", "charging", "gap"])
def test_idle_confirmation_restarts_after_evidence_interruption(interruption):
    source = _live_run().planning_input
    executor, _ = runtime()
    idle = replace(source, external_load_policy=policy(source, power=2.2))
    assert executor._ev_primitive(idle, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY
    later = replace(
        source,
        captured_at=source.captured_at + timedelta(seconds=20),
        storage_mode_capability_evidence=None,
        capability_snapshot_set=None,
    )
    demand = policy(later, power=2.2)
    if interruption == "missing":
        demand = None
    elif interruption == "stale":
        demand = replace(demand, measured_at=source.captured_at)
    elif interruption == "unseparated":
        demand = replace(demand, physical_evidence_available=False)
    elif interruption == "charging":
        demand = replace(demand, power_w=2300)
    if interruption != "gap":
        executor._ev_primitive(
            replace(later, external_load_policy=demand), "home-battery", P.BALANCE_DISCHARGE_ONLY
        )
    seconds = 200 if interruption == "gap" else 30
    later = replace(
        source,
        captured_at=source.captured_at + timedelta(seconds=seconds),
        storage_mode_capability_evidence=None,
        capability_snapshot_set=None,
    )
    later = replace(later, external_load_policy=policy(later, power=2.2))
    assert executor._ev_primitive(later, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY


def test_idle_confirmation_accepts_normal_slow_poll_and_persists_release(tmp_path):
    source = _live_run().planning_input
    store = ActivePlanCommitmentStore(tmp_path / "idle.json")
    store.save_ev_exclusion_scopes({"home-battery"})
    executor = CanonicalExecutionRuntime(dispatch=lambda *args: None, commitment_store=store)
    for seconds in [0, 120]:
        current = replace(
            source,
            captured_at=source.captured_at + timedelta(seconds=seconds),
            storage_mode_capability_evidence=None,
            capability_snapshot_set=None,
        )
        current = replace(current, external_load_policy=policy(current, power=5))
        result = executor._ev_primitive(current, "home-battery", P.BALANCE_DISCHARGE_ONLY)
    assert result is P.BALANCE_DISCHARGE_ONLY
    assert store.load_ev_exclusion_scopes() == set()


def test_repeated_idle_snapshot_cannot_accumulate_confirmation_time():
    source = _live_run().planning_input
    executor, _ = runtime()
    idle = replace(source, external_load_policy=policy(source, power=2.2))
    for _ in range(40):
        assert executor._ev_primitive(idle, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY


@pytest.mark.parametrize("age", [-1, 16])
def test_nonfresh_zero_cannot_release_existing_exclusion(age):
    source = _live_run().planning_input
    executor, _ = runtime()
    active = replace(source, external_load_policy=policy(source))
    executor._ev_primitive(active, "home-battery", P.BALANCE_DISCHARGE_ONLY)
    zero = replace(
        source,
        external_load_policy=replace(
            policy(source, power=0), measured_at=source.captured_at - timedelta(seconds=age)
        ),
    )
    assert executor._ev_primitive(zero, "home-battery", P.BALANCE_DISCHARGE_ONLY) is P.STANDBY
