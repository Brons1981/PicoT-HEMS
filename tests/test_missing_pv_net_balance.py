"""API outage regression: independent net evidence, never fabricated PV."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_pv_route_optimisation import grid_wh, observed, source_with_later_cheap_window

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.household_load_guard import HouseholdLoadGuardAssessment
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.planning_input import PlanningInputBundle, SourceEvidence


def bundle(snapshot, *, grid=-438.431, charge=1898, discharge=0, pv=None):
    at = snapshot.captured_at
    values = {
        "grid_power": grid,
        "storage_power_signed": charge - discharge,
        "storage_power_from_house": charge,
        "storage_power_to_house": discharge,
        "pv_power": pv,
    }
    evidence = tuple(SourceEvidence(
        f"{role}:{at.isoformat()}", "test", role, f"sensor.{role}",
        str(value) if value is not None else "unavailable", "W", at,
        "available" if value is not None else "unavailable", "mapping:1",
    ) for role, value in values.items())
    return PlanningInputBundle(snapshot, evidence, (), at, at)


def proof(snapshot):
    from picot.v2.net_balance import NetBalanceObserver

    observer = NetBalanceObserver()
    for minute in range(6):
        at = snapshot.captured_at - timedelta(minutes=5 - minute)
        sample = replace(snapshot, captured_at=at, daily_charge_context=None,
                         capability_snapshot_set=replace(snapshot.capability_snapshot_set,
                                                         captured_at=at),
                         current_storage_states=tuple(replace(s, measured_at=at)
                                                      for s in snapshot.current_storage_states))
        enriched = observer.observe(bundle(sample))
    return replace(snapshot, net_balance_surplus=enriched.snapshot.net_balance_surplus)


@pytest.mark.parametrize("during_charge", [False, True])
def test_missing_pv_can_reduce_grid_through_canonical_pipeline(
    tmp_path, monkeypatch, during_charge,
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    previous_plan = first.execution_plan_set.plans[0]
    grid = next(s for s in previous_plan.segments
                if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER)
    minutes = (int((grid.starts_at - source.captured_at).total_seconds() / 60) + 5
               if during_charge else 60)
    observation = observed(source, soc=0.90, gap=True, minutes=minutes)
    observation = replace(observation, household_load_guard=HouseholdLoadGuardAssessment(
        False, "unknown", 0, observation.captured_at, None,
    ))
    # Without independent evidence the old conservative behaviour is preserved.
    retained = pipeline.run(planning_input=recover(observation))
    assert retained.execution_plan_set.plans[0].plan_id == first.execution_plan_set.plans[0].plan_id
    result = pipeline.run(planning_input=recover(proof(observation)))
    assert result.evaluation.daily_pv_surplus_trigger is not None
    assert result.evaluation.daily_pv_comparison.actual_wh is None
    assert result.evaluation.daily_pv_comparison.status == "partial"
    trigger = result.evaluation.daily_pv_surplus_trigger
    assert trigger.actual_wh is None and trigger.central_wh is None
    assert trigger.revision_reason.value == "net_balance_allows_grid_reduction"
    assert trigger.target_wh == 8160
    plan = result.execution_plan_set.plans[0]
    assert grid_wh(plan, observation.captured_at) < grid_wh(
        first.execution_plan_set.plans[0], observation.captured_at,
    )
    assert result.candidate_set.candidates and result.outcomes
    assert plan.winning_candidate_id == result.evaluation.winning_candidate_id
    owner = store.load_daily_assignments()[0]
    assert owner.completed_at is None
    assert owner.revision_reason.value == "net_balance_allows_grid_reduction"
    path = next(p for p in result.candidate_set.energy_paths
                if p.path_id == plan.winning_energy_path_id)
    freed = []
    for old in previous_plan.segments:
        if old.primitive is not ExecutionPrimitive.CHARGE_AT_POWER:
            continue
        for segment in plan.segments:
            if (segment.starts_at < old.ends_at and old.starts_at < segment.ends_at
                    and segment.primitive is not ExecutionPrimitive.CHARGE_AT_POWER):
                freed.append(segment)
                assert segment.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
                assert any(s.starts_at <= segment.starts_at and segment.ends_at <= s.ends_at
                           and s.primitive is segment.primitive for s in path.segments)
    assert freed
    assert trigger.comparison_evidence_id in store.load_daily_pv_comparison(
        owner.assignment_id,
    ).assessed_evidence_ids

    def forbidden(*args, **kwargs):
        raise AssertionError("Already assessed net proof may not cause another price search")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "pv_surplus_trigger", forbidden)
    repeated = pipeline.run(planning_input=recover(proof(observation)))
    assert repeated.execution_plan_set.plans[0].plan_id == plan.plan_id


def test_observation_requires_five_minutes_and_preserves_missing_pv():
    from picot.v2.net_balance import NetBalanceObserver

    observer = NetBalanceObserver()
    source = source_with_later_cheap_window()
    for minute in range(6):
        sample = observed(source, soc=0.86, minutes=60 + minute, gap=True)
        enriched = observer.observe(bundle(sample))
        assert enriched.household_load_observation is None
        assert enriched.snapshot.pv_energy_timeline == sample.pv_energy_timeline
        assert (enriched.snapshot.net_balance_surplus is not None) == (minute == 5)
    evidence = enriched.snapshot.net_balance_surplus
    assert evidence.minimum_surplus_w == pytest.approx(2336.431)
    assert observer.observe(bundle(sample)).snapshot.net_balance_surplus == evidence
    repeated = observer.observe(bundle(observed(source, soc=0.86, minutes=66, gap=True)))
    assert repeated.snapshot.net_balance_surplus.evidence_id == evidence.evidence_id
    assert NetBalanceObserver().observe(bundle(sample)).snapshot.net_balance_surplus is None


def test_same_sample_cannot_build_duration():
    from picot.v2.net_balance import NetBalanceObserver

    observer = NetBalanceObserver()
    sample = bundle(observed(source_with_later_cheap_window(), gap=True))
    for _ in range(20):
        assert observer.observe(sample).snapshot.net_balance_surplus is None


@pytest.mark.parametrize("failure", ["stale", "gap", "duplicate", "unit", "nan", "missing",
                                     "inconsistent", "skew", "pv_returns", "soc_falls",
                                     "discharge_export", "net_import", "mapping"])
def test_invalid_or_insufficient_evidence_resets_window(failure):
    from picot.v2.net_balance import NetBalanceObserver

    observer = NetBalanceObserver()
    source = source_with_later_cheap_window()
    for minute in range(5):
        observer.observe(bundle(observed(source, soc=0.86, minutes=60 + minute, gap=True)))
    sample = observed(source, soc=0.85 if failure == "soc_falls" else 0.86,
                      minutes=70 if failure == "gap" else 65, gap=True)
    current = bundle(sample)
    items = list(current.evidence)
    if failure == "stale":
        items[0] = replace(items[0], observed_at=sample.captured_at - timedelta(minutes=4))
    elif failure == "duplicate":
        items.append(items[0])
    elif failure == "unit":
        items[0] = replace(items[0], raw_unit="kW")
    elif failure == "nan":
        items[0] = replace(items[0], raw_state="nan")
    elif failure == "missing":
        items.pop(0)
    elif failure == "inconsistent":
        items[1] = replace(items[1], raw_state="-1898")
    elif failure == "skew":
        items[0] = replace(items[0], observed_at=sample.captured_at - timedelta(seconds=90))
    elif failure == "mapping":
        items[0] = replace(items[0], mapping_version="mapping:2")
    elif failure == "pv_returns":
        items = list(bundle(sample, pv=2500).evidence)
    elif failure == "discharge_export":
        items = list(bundle(sample, grid=-1000, charge=0, discharge=1000).evidence)
    elif failure == "net_import":
        items = list(bundle(sample, grid=2000).evidence)
    enriched = observer.observe(replace(current, evidence=tuple(items)))
    assert enriched.snapshot.net_balance_surplus is None


@pytest.mark.parametrize("confirm_zero", [False, True])
def test_unchanged_directional_zero_needs_explicit_current_state_read(confirm_zero):
    from picot.v2.net_balance import NetBalanceObserver

    source = source_with_later_cheap_window()
    observer = NetBalanceObserver()
    for minute in range(6):
        current = bundle(observed(source, minutes=60 + minute, gap=True))
        at = current.snapshot.captured_at
        current = replace(current, evidence=tuple(
            replace(e, observed_at=at - timedelta(hours=4),
                    last_changed_at=at - timedelta(hours=4),
                    state_read_at=at if confirm_zero else None)
            if e.semantic_role == "storage_power_to_house" else e for e in current.evidence
        ))
        enriched = observer.observe(current)
    assert (enriched.snapshot.net_balance_surplus is not None) == confirm_zero


def test_net_evidence_does_not_release_active_load_or_infeasible_goal(tmp_path, monkeypatch):
    from test_daily_main_charge_windows import inputs
    from test_daily_main_route_optimisation import fresh

    from picot.v2.material_replanning import daily_grid_review_comparison

    _, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    grid = next(s for s in first.execution_plan_set.plans[0].segments
                if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER)
    minutes = int((grid.starts_at - source.captured_at).total_seconds() / 60) + 5
    snapshot = observed(source, soc=0.9, minutes=minutes, gap=True)
    adapter = IndependentDailyReferenceAdapter()
    for active in (True, False):
        current = snapshot if active else observed(
            fresh(source, pv_factor=0, tag="shortfall"), soc=0.1, minutes=minutes, gap=True,
        )
        current = replace(current, household_load_guard=HouseholdLoadGuardAssessment(
            active, "reliable" if active else "unknown", 2000 if active else 0,
            current.captured_at, current.captured_at if active else None,
        ))
        current = recover(proof(current))
        owner = current.daily_charge_context.assignments[0]
        comparison = daily_grid_review_comparison(current,
                                                  current.daily_charge_context.pv_comparison_states[0])
        assert adapter.pv_surplus_trigger(
            snapshot=current, assignment=owner, comparison=comparison,
            conversion_model=inputs()["conversion_model"],
        ) is None
        if not active:
            triggers = adapter.main_route_shortfalls(
                snapshot=current, conversion_model=inputs()["conversion_model"],
            )
            assert triggers
            assert adapter.main_repair_required(snapshot=current, trigger=triggers[0],
                                                conversion_model=inputs()["conversion_model"])


def test_material_monitor_uses_same_independent_proof(tmp_path, monkeypatch):
    from test_daily_main_charge_windows import inputs

    from picot.v2.household_load_history import HouseholdLoadHistoryStore
    from picot.v2.material_replanning import MaterialReplanningObservationProducer

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    pipeline.run(planning_input=recover(source))
    snapshot = recover(observed(source, soc=0.9, gap=True))
    producer = MaterialReplanningObservationProducer(
        history=HouseholdLoadHistoryStore(tmp_path / "load.json"),
        conversion_model=lambda _: inputs()["conversion_model"],
    )
    producer.observe(bundle(snapshot))  # Initial restored context is independently material.
    assert producer.observe(bundle(snapshot)) == ()
    before = store._path.read_bytes()
    signal = producer.observe(bundle(proof(snapshot)))
    assert signal[0].new_value == "net_balance_allows_grid_reduction"
    assert signal[0].material_transition
    assert store._path.read_bytes() == before
