"""One delivery day's valid correction must not require another day's revision."""

import pytest
import test_daily_main_horizon_retention as retained_tests
from test_daily_main_horizon_retention import recover, stored
from test_daily_main_route_optimisation import fresh

from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


@pytest.fixture(scope="module")
def two_days(tmp_path_factory):
    return retained_tests.two_days.__wrapped__(tmp_path_factory)


def scenario(two_days, tmp_path):
    store = stored(tmp_path, two_days)
    store.bind_daily_main_plan(
        plan=two_days["second_set"].plans[0], window=two_days["second_window"], activate=True
    )
    source = recover(fresh(two_days["source"], pv_factor=0, soc=0.1, tag="both-short"), store)
    adapter = IndependentDailyReferenceAdapter()
    triggers = adapter.main_route_shortfalls(
        snapshot=source, conversion_model=two_days["conversion"]
    )
    assert len(triggers) == 2
    return store, source, adapter, triggers


def test_current_day_has_feasible_correction_despite_next_day_shortfall(two_days, tmp_path):
    store, source, adapter, triggers = scenario(two_days, tmp_path)
    today, tomorrow = store.load_daily_assignments()
    trigger = next(t for t in triggers if t.assignment_id == today.assignment_id)
    windows = adapter.main_charge_windows(
        snapshot=source,
        assignment=today,
        conversion_model=two_days["conversion"],
        optimisation_trigger=trigger,
    )
    assert windows.windows, windows.reason
    for window in windows.windows:
        assert today.starts_at <= window.reached_at <= today.ends_at
        assert window.target_storage_energy_wh == 8160
        assert all(s.assignment_id == tomorrow.assignment_id for s in window.retained_main_segments)
    assert store.load_daily_assignments() == (today, tomorrow)


def test_two_polls_revise_one_owner_at_a_time_and_survive_restart(two_days, tmp_path, monkeypatch):
    store, source, adapter, _ = scenario(two_days, tmp_path)
    today, tomorrow = store.load_daily_assignments()
    runtime = MarketDailyPlannerRuntime(two_days["conversion"])

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy generator must not select daily routes")

    monkeypatch.setattr(runtime, "generate", forbidden)
    original_monitor = IndependentDailyReferenceAdapter.main_route_shortfalls

    def reversed_monitor(self, **kwargs):
        return tuple(reversed(original_monitor(self, **kwargs)))

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_route_shortfalls", reversed_monitor)
    pipeline = CanonicalPipeline(market_daily_planner_runtime=runtime, commitment_store=store)
    first = pipeline.run(planning_input=source)
    assert first.evaluation.status == "winner_selected", first.evaluation.reason
    revised_today, retained_tomorrow = store.load_daily_assignments()
    from picot.v2.projection import project

    card = next(
        c
        for c in project(first).cards
        if c.entity_id == "sensor.picot_v2_pipeline_04_evaluation_engine"
    )
    observed = card.attributes["daily_main_input_shortfalls"]
    assert len(observed) == 2
    assert [t["assignment_id"] for t in observed if t["selected_for_revision"]] == [
        today.assignment_id
    ]
    assert len(first.evaluation.daily_main_input_shortfalls) == 2
    assert first.evaluation.daily_main_shortfall.assignment_id == today.assignment_id
    assert revised_today.assignment_id == today.assignment_id
    assert revised_today.revision == today.revision + 1
    assert retained_tomorrow == tomorrow
    assert revised_today.completed_at is None
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    next_source = recover(fresh(source, tag="after-restart"), store)
    outstanding = adapter.main_route_shortfalls(
        snapshot=next_source, conversion_model=two_days["conversion"]
    )
    assert [t.assignment_id for t in outstanding] == [tomorrow.assignment_id]
    pipeline = CanonicalPipeline(market_daily_planner_runtime=runtime, commitment_store=store)
    second = pipeline.run(planning_input=next_source)
    assert second.evaluation.status == "winner_selected", second.evaluation.reason
    final_today, final_tomorrow = store.load_daily_assignments()
    assert final_today == revised_today
    assert final_tomorrow.assignment_id == tomorrow.assignment_id
    assert final_tomorrow.revision == tomorrow.revision + 1
    assert final_tomorrow.completed_at is None
    assert (
        adapter.main_route_shortfalls(
            snapshot=recover(next_source, store), conversion_model=two_days["conversion"]
        )
        == ()
    )

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", forbidden)
    before = store._path.read_bytes()
    retained = pipeline.run(planning_input=recover(next_source, store))
    assert retained.evaluation.status == "plan_retained"
    assert store._path.read_bytes() == before


def test_later_required_repair_does_not_skip_deferred_earlier_owner(
    two_days, tmp_path, monkeypatch,
):
    store, source, _, _ = scenario(two_days, tmp_path)
    today, tomorrow = store.load_daily_assignments()
    # Exercise the admission seam: current day is deferred by its recovery proof,
    # but tomorrow needs repair. Candidate physics must still protect both days.
    monkeypatch.setattr(
        IndependentDailyReferenceAdapter, "main_repair_required",
        lambda self, **kw: kw["trigger"].assignment_id == tomorrow.assignment_id,
    )
    pipeline = CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(two_days["conversion"]),
        commitment_store=store,
    )
    result = pipeline.run(planning_input=source)
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    assert result.evaluation.daily_main_shortfall.assignment_id == today.assignment_id
    revised, retained = store.load_daily_assignments()
    assert revised.revision == today.revision + 1
    assert retained == tomorrow
    assert revised.completed_at is None
    # A restarted pipeline gets tomorrow's turn only after today's repaired
    # route is physically feasible; it cannot overwrite today's new commitment.
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    result = CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(two_days["conversion"]),
        commitment_store=restarted,
    ).run(planning_input=recover(source, restarted))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    assert result.evaluation.daily_main_shortfall.assignment_id == tomorrow.assignment_id
    assert restarted.load_daily_assignments()[0] == revised


def test_all_recoverable_shortfalls_remain_deferred(two_days, tmp_path, monkeypatch):
    store, source, _, _ = scenario(two_days, tmp_path)
    before = store._path.read_bytes()
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_repair_required",
                        lambda *args, **kwargs: False)
    result = CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(two_days["conversion"]),
        commitment_store=store,
    ).run(planning_input=source)
    assert result.evaluation.status == "plan_retained"
    assert result.evaluation.daily_main_shortfall is None
    assert store._path.read_bytes() == before


@pytest.mark.parametrize("required", [(False, False), (False, True), (True, False), (True, True)])
def test_monitor_and_pipeline_share_chronological_repair_admission(
    two_days, tmp_path, monkeypatch, required,
):
    from picot.v2.household_load_history import HouseholdLoadHistoryStore
    from picot.v2.material_replanning import MaterialReplanningObservationProducer
    from picot.v2.planning_input import PlanningInputBundle

    store, source, adapter, triggers = scenario(two_days, tmp_path)
    today, tomorrow = store.load_daily_assignments()
    decisions = dict(zip((today.assignment_id, tomorrow.assignment_id), required, strict=True))
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_repair_required",
                        lambda self, **kw: decisions[kw["trigger"].assignment_id])
    selected = adapter.main_repair_sequence(
        snapshot=source, triggers=tuple(reversed(triggers)),
        conversion_model=two_days["conversion"],
    )
    assert [t.assignment_id for t in selected] == (
        [today.assignment_id, tomorrow.assignment_id] if any(required) else []
    )
    producer = MaterialReplanningObservationProducer(
        history=HouseholdLoadHistoryStore(tmp_path / "house.json"),
        conversion_model=lambda snapshot: two_days["conversion"],
    )
    bundle = PlanningInputBundle(source, (), (), source.captured_at, source.captured_at)
    producer.observe(bundle)  # initialise durable identity, not a planning decision
    observed = producer.observe(bundle)
    if any(required):
        assert today.assignment_id in observed[0].evidence_ids
        assert tomorrow.assignment_id not in observed[0].evidence_ids
    else:
        assert observed == ()
