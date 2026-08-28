from dataclasses import replace
from datetime import timedelta

from test_independent_daily_reference_adapter import _conversion, _snapshot

from picot.v2.household_planning_regime import HouseholdPlanningRegime
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def _pipeline(tmp_path, *, switching_margin_eur: float = 0.05):
    store = ActivePlanCommitmentStore(tmp_path / "commitments.json")
    pipeline = CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(_conversion()),
        commitment_store=store,
        plan_switching_margin_eur=switching_margin_eur,
    )
    return pipeline, store


def test_mep_winner_flows_through_canonical_path_and_plan_store(tmp_path) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path)

    run = pipeline.run(planning_input=snapshot)

    winning_path = next(
        item
        for item in run.candidate_set.energy_paths
        if item.path_id == run.evaluation.winning_energy_path_id
    )
    execution_plan = run.execution_plan_set.plans[0]
    assert tuple(
        item.source_path_segment_id for item in execution_plan.segments
    ) == winning_path.segment_ids
    commitment = store.load(snapshot.current_storage_states[0].execution_scope_id)
    assert commitment is not None
    assert commitment.planner_id == "mep"
    assert commitment.plan_id == execution_plan.plan_id
    assert commitment.schedule_id is not None
    assert commitment.selection_reason == (
        "objective:mep_physical_and_market_evaluation"
    )
    assert len(commitment.segments) == len(winning_path.segments)
    assert commitment.segments[0].starts_at == winning_path.segments[0].starts_at
    assert commitment.segments[-1].ends_at == winning_path.segments[-1].ends_at


def test_canonical_commitment_survives_next_mep_calculation(tmp_path) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path)
    first = pipeline.run(planning_input=snapshot)
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    commitment = store.load(scope_id)
    assert commitment is not None

    continued = pipeline.run(
        planning_input=replace(
            snapshot,
            active_plan_commitments=(commitment,),
        )
    )

    assert continued.evaluation.decisive_step == (
        "stability:canonical_plan_commitment_retained"
    )
    assert continued.execution_plan_set.plans[0].plan_id == (
        first.execution_plan_set.plans[0].plan_id
    )
    assert store.load(scope_id) == commitment


def test_market_planner_generates_and_evaluation_selects() -> None:
    planner_source = (
        __import__(
            "picot.planner.market_daily_planner",
            fromlist=["MarketDailyPlanner"],
        )
        .__loader__
        .get_source("picot.planner.market_daily_planner")
    )
    evaluation_source = (
        __import__(
            "picot.planner.market_daily_evaluation_engine",
            fromlist=["MarketDailyEvaluationEngine"],
        )
        .__loader__
        .get_source("picot.planner.market_daily_evaluation_engine")
    )

    assert "def _current_decision" not in planner_source
    assert "best_observation_ids" not in planner_source
    assert "class MarketDailyEvaluationEngine" in evaluation_source
    assert "def current_decision" in evaluation_source


def test_scheduled_incumbent_that_misses_required_deadline_is_replaced(
    tmp_path,
) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path)
    first = pipeline.run(planning_input=snapshot)
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    commitment = store.load(scope_id)
    assert commitment is not None
    assert snapshot.horizon_end is not None
    requirement_deadline = snapshot.horizon_end
    late = replace(
        commitment,
        starts_at=requirement_deadline + timedelta(minutes=15),
        ends_at=requirement_deadline + timedelta(hours=1),
    )
    store.save(late)

    continued = pipeline.run(
        planning_input=replace(snapshot, active_plan_commitments=(late,))
    )

    replacement = store.load(scope_id)
    assert replacement is not None
    assert replacement.plan_id != first.execution_plan_set.plans[0].plan_id
    assert replacement.plan_revision == late.plan_revision + 1
    assert replacement.replaced_plan_id == late.plan_id
    assert replacement.selection_reason == (
        "necessity:incumbent_misses_required_by"
    )
    assert continued.evaluation.decisive_step == (
        "necessity:incumbent_misses_required_by"
    )


def test_immaterial_challenger_retains_scheduled_incumbent(tmp_path) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path)
    pipeline.run(planning_input=snapshot)
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    commitment = store.load(scope_id)
    assert commitment is not None
    assert commitment.worst_case_financial_result_eur is not None
    incumbent = replace(
        commitment,
        starts_at=snapshot.captured_at + timedelta(minutes=15),
        worst_case_financial_result_eur=(
            commitment.worst_case_financial_result_eur - 0.01
        ),
    )
    store.save(incumbent)

    continued = pipeline.run(
        planning_input=replace(snapshot, active_plan_commitments=(incumbent,))
    )

    assert continued.execution_plan_set.plans[0].plan_id == commitment.plan_id
    assert store.load(scope_id) == incumbent
    assert continued.evaluation.decisive_step == (
        "stability:canonical_plan_commitment_retained"
    )


def test_materially_better_challenger_replaces_scheduled_incumbent(tmp_path) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path)
    pipeline.run(planning_input=snapshot)
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    commitment = store.load(scope_id)
    assert commitment is not None
    incumbent = replace(
        commitment,
        starts_at=snapshot.captured_at + timedelta(minutes=15),
        worst_case_financial_result_eur=-10.0,
    )
    store.save(incumbent)

    continued = pipeline.run(
        planning_input=replace(snapshot, active_plan_commitments=(incumbent,))
    )

    replacement = store.load(scope_id)
    assert replacement is not None
    assert replacement.plan_id != incumbent.plan_id
    assert replacement.plan_revision == incumbent.plan_revision + 1
    assert continued.evaluation.decisive_step == (
        "material_change:challenger_improves_total_objective"
    )


def test_configured_switching_margin_is_used_by_evaluation(tmp_path) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path, switching_margin_eur=0.005)
    pipeline.run(planning_input=snapshot)
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    commitment = store.load(scope_id)
    assert commitment is not None
    assert commitment.worst_case_financial_result_eur is not None
    incumbent = replace(
        commitment,
        starts_at=snapshot.captured_at + timedelta(minutes=15),
        worst_case_financial_result_eur=(
            commitment.worst_case_financial_result_eur - 0.01
        ),
    )
    store.save(incumbent)

    continued = pipeline.run(
        planning_input=replace(snapshot, active_plan_commitments=(incumbent,))
    )

    assert continued.evaluation.decisive_step == (
        "material_change:challenger_improves_total_objective"
    )


def test_legacy_cp_storage_deadline_cannot_block_mep(tmp_path) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.41)
    deadline = snapshot.captured_at + timedelta(minutes=49)
    regime = HouseholdPlanningRegime(
        regime_id="regime-deadline",
        profile_id="profile",
        profile_version=1,
        regime="cost_optimization_first",
        objective_order=(
            "cost_optimization",
            "self_consumption",
            "reserve_availability",
        ),
        reason="test_deadline",
        forecast_confidence=0.8,
        cumulative_forecast_energy_wh=2000.0,
        cumulative_actual_energy_wh=2000.0,
        deviation_energy_wh=0.0,
        deviation_percent=0.0,
        underperformance_duration_seconds=0,
        evidence_ids=("deadline-evidence",),
        storage_target_required_by=deadline.isoformat(),
    )
    pipeline = CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(_conversion()),
        commitment_store=ActivePlanCommitmentStore(tmp_path / "commitments.json"),
    )

    run = pipeline.run(
        planning_input=replace(snapshot, household_planning_regime=regime)
    )

    assert run.candidate_set.derivation_status == "ready"
    assert run.evaluation.status == "winner_selected"
    assert run.execution_plan_set.plans
