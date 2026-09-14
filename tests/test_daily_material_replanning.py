"""Native daily commitments reach Monitor without generating replacement plans."""
from dataclasses import replace
from datetime import timedelta

from test_daily_main_active_pipeline import setup
from test_daily_main_charge_windows import inputs

from picot.domain.runtime import RuntimeObservationKind
from picot.v2.daily_charge_assignment import DailyMainShortfallTrigger
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.material_replanning import MaterialReplanningObservationProducer
from picot.v2.planning_input import PlanningInputBundle


def bundle(snapshot):
    return PlanningInputBundle(snapshot, (), (), snapshot.captured_at, snapshot.captured_at)


def prepared(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    snapshot = recover()
    producer = MaterialReplanningObservationProducer(
        history=HouseholdLoadHistoryStore(tmp_path / "load.json"),
        conversion_model=lambda snapshot: inputs()["conversion_model"],
    )
    return store, snapshot, producer


def test_daily_binding_observed_without_legacy_commitment_then_healthy_route_is_inert(
    tmp_path, monkeypatch,
):
    store, snapshot, producer = prepared(tmp_path, monkeypatch)
    assert not snapshot.active_plan_commitments
    before = store._path.read_bytes()
    first = producer.observe(bundle(snapshot))
    assert first[0].kind is RuntimeObservationKind.COMMITMENT_CHANGED

    def forbidden(*args, **kwargs):
        raise AssertionError("observation must not search replacement windows")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", forbidden)
    assert producer.observe(bundle(snapshot)) == ()
    assert store._path.read_bytes() == before


def test_daily_shortfall_uses_accepted_repair_proof_each_poll(tmp_path, monkeypatch):
    store, snapshot, producer = prepared(tmp_path, monkeypatch)
    producer.observe(bundle(snapshot))
    owner = next(a for a in snapshot.daily_charge_context.assignments if a.route_plan_id)
    storage = snapshot.current_storage_states[0]
    trigger = DailyMainShortfallTrigger(
        owner.assignment_id, owner.route_plan_id, owner.revision,
        snapshot.daily_charge_context.active_main_plan_ids[0], snapshot.snapshot_id,
        snapshot.captured_at, storage.usable_capacity_wh - 20, storage.usable_capacity_wh,
    )
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_route_shortfalls",
                        lambda *args, **kwargs: (trigger,))
    checks = []
    def deferred(*args, **kwargs):
        checks.append(kwargs["trigger"])
        return False
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_repair_required", deferred)
    assert producer.observe(bundle(snapshot)) == ()
    assert producer.observe(bundle(snapshot)) == ()
    assert len(checks) == 2  # poll reevaluation is never hidden by legacy buckets
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_repair_required",
                        lambda *args, **kwargs: True)
    observation = producer.observe(bundle(snapshot))[0]
    assert observation.material_transition
    assert observation.kind is RuntimeObservationKind.STORAGE_STATE_CHANGED
    assert owner.assignment_id in observation.evidence_ids


def test_completion_change_observed_but_poll_timestamp_alone_is_not(tmp_path, monkeypatch):
    _, snapshot, producer = prepared(tmp_path, monkeypatch)
    producer.observe(bundle(snapshot))
    at = snapshot.captured_at + timedelta(seconds=1)
    later = replace(snapshot, captured_at=at,
                    capability_snapshot_set=replace(
                        snapshot.capability_snapshot_set, captured_at=at),
                    daily_charge_context=replace(snapshot.daily_charge_context,
                        restored_at=at))
    assert producer.observe(bundle(later)) == ()
    context = later.daily_charge_context
    # Completion is represented in the durable owner; the producer neither
    # creates completion nor uses a high SOC as a substitute for that record.
    owner = context.assignments[0]
    segment = owner.main_segments[0]
    completed = replace(owner, completed_at=segment.starts_at,
                        completion_evidence_id="actual-full",
                        completion_segment_id=segment.segment_id)
    changed = replace(later, daily_charge_context=replace(context,
                      assignments=(completed, *context.assignments[1:])))
    assert producer.observe(bundle(changed))[0].kind is RuntimeObservationKind.COMMITMENT_CHANGED


def test_strategy_change_and_capability_loss_are_not_hidden_by_healthy_route(tmp_path, monkeypatch):
    from picot.domain.capability_snapshot import CapabilityAvailability

    _, snapshot, producer = prepared(tmp_path, monkeypatch)
    producer.observe(bundle(snapshot))
    strategy = replace(snapshot, strategy_id="new-explicit-strategy")
    assert producer.observe(bundle(strategy))[0].kind is RuntimeObservationKind.STRATEGY_CHANGED
    caps = strategy.capability_snapshot_set
    unavailable = replace(strategy, capability_snapshot_set=replace(caps,
        capabilities=(replace(caps.capabilities[0],
            availability=CapabilityAvailability.UNAVAILABLE), *caps.capabilities[1:])))
    observed = producer.observe(bundle(unavailable))
    assert observed[0].material_transition
    assert observed[0].kind is RuntimeObservationKind.CAPABILITY_MAPPING_CHANGED


def test_daily_poll_gate_retains_healthy_route_and_recaptures_material_input(tmp_path, monkeypatch):
    from picot.runtime.runtime_monitor import RuntimeMonitorSession
    from picot.v2.live_runtime import _poll_live_cycle

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    original = recover()
    producer = MaterialReplanningObservationProducer(
        history=HouseholdLoadHistoryStore(tmp_path / "load.json"),
        conversion_model=lambda snapshot: inputs()["conversion_model"],
    )
    monitor = RuntimeMonitorSession()
    executed = []
    def execute(current):
        executed.append(current)
        return pipeline.run(planning_input=current.snapshot)
    def at(seconds, strategy=None):
        now = original.captured_at + timedelta(seconds=seconds)
        snapshot = replace(original, captured_at=now,
            strategy_id=strategy or original.strategy_id,
            daily_charge_context=replace(original.daily_charge_context, restored_at=now),
            capability_snapshot_set=replace(original.capability_snapshot_set, captured_at=now))
        return bundle(snapshot)

    captures = [at(0), at(1)]
    signature = _poll_live_cycle(
        previous_signature=None, load_bundle=lambda: captures.pop(0), execute=execute,
        runtime_monitor=monitor, runtime_observations=producer.observe,
        runtime_now=lambda: original.captured_at + timedelta(seconds=1),
    )
    assert not captures and len(executed) == 1
    before = store._path.read_bytes()
    # Ordinary poll and normal time progression: physical proof runs but no
    # admitted planning run, no new plan and only one capture.
    captures = [at(7)]
    signature = _poll_live_cycle(
        previous_signature=signature, load_bundle=lambda: captures.pop(0), execute=execute,
        runtime_monitor=monitor, runtime_observations=producer.observe,
    )
    assert not captures and len(executed) == 1
    assert store._path.read_bytes() == before
    # Explicit strategy transition must pass Monitor and use a second capture.
    fresh = at(9, "new-explicit-strategy")
    captures = [at(8, "new-explicit-strategy"), fresh]
    _poll_live_cycle(
        previous_signature=signature, load_bundle=lambda: captures.pop(0), execute=execute,
        runtime_monitor=monitor, runtime_observations=producer.observe,
        runtime_now=lambda: original.captured_at + timedelta(seconds=9),
    )
    assert not captures and len(executed) == 2
    assert executed[-1] is fresh


def test_regime_evidence_refresh_does_not_become_user_rule_change(tmp_path, monkeypatch):
    from picot.v2.household_planning_regime import HouseholdPlanningRegime

    _, snapshot, producer = prepared(tmp_path, monkeypatch)
    regime = HouseholdPlanningRegime(
        regime_id="r1", profile_id="user", profile_version=1,
        regime="cost_optimization_first", objective_order=("financial_result",),
        reason="same_priority", forecast_confidence=1.0,
        cumulative_forecast_energy_wh=100, cumulative_actual_energy_wh=100,
        deviation_energy_wh=0, deviation_percent=0,
        underperformance_duration_seconds=0, evidence_ids=("pv-1",),
    )
    snapshot = replace(snapshot, household_planning_regime=regime)
    producer.observe(bundle(snapshot))
    refreshed = replace(snapshot, household_planning_regime=replace(regime,
        regime_id="r2", evidence_ids=("pv-2",), cumulative_actual_energy_wh=101,
        cumulative_forecast_energy_wh=101))
    assert producer.observe(bundle(refreshed)) == ()
