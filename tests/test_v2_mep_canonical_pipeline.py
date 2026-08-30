from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

from test_independent_daily_reference_adapter import _conversion, _snapshot

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import StorageRoundTripEfficiencyEvidence
from picot.v2.household_planning_regime import HouseholdPlanningRegime
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.mep_canonical_pipeline import (
    _commitment_target_reached,
    _complete_acquisition_revision,
    _defer_charge_revision,
    _measured_pv_basis_covers_remaining_acquisition,
)
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
    CommittedPlanSegment,
)
from picot.v2.projection import project
from picot.v2.web_ui import DASHBOARD_HTML, build_web_view


def _pipeline(tmp_path, *, switching_margin_eur: float = 0.05):
    store = ActivePlanCommitmentStore(tmp_path / "commitments.json")
    pipeline = CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(_conversion()),
        commitment_store=store,
        plan_switching_margin_eur=switching_margin_eur,
    )
    return pipeline, store


def _pv_admission_fixture(*, promoted_to_central: bool) -> tuple[object, object, object]:
    starts_at = datetime.fromisoformat("2026-08-30T10:00:00+00:00")
    ends_at = starts_at + timedelta(hours=1)
    due_segment = SimpleNamespace(
        segment_id="charge",
        order=1,
        execution_scope_id="battery",
        starts_at=starts_at,
        ends_at=ends_at,
        primitive=ExecutionPrimitive.CHARGE_AT_POWER,
    )
    central_wh = 2000.0
    lower_wh = central_wh if promoted_to_central else 400.0
    snapshot = SimpleNamespace(
        captured_at=starts_at,
        storage_mode_capability_evidence=SimpleNamespace(
            current_vendor_mode="Nul op de meter"
        ),
        current_storage_states=(SimpleNamespace(
            execution_scope_id="battery",
            capability_id="storage",
            current_stored_energy_wh=7000.0,
            usable_capacity_wh=8160.0,
        ),),
        storage_physical_limits=(SimpleNamespace(
            execution_scope_id="battery",
            capability_id="storage",
            maximum_soc=1.0,
        ),),
        pv_energy_timeline=SimpleNamespace(intervals=(SimpleNamespace(
            starts_at=starts_at,
            ends_at=ends_at,
            forecast_lower_energy_wh=lower_wh,
            forecast_central_energy_wh=central_wh,
        ),)),
        household_load_forecast=SimpleNamespace(intervals=(SimpleNamespace(
            starts_at=starts_at,
            ends_at=ends_at,
            expected_energy_wh=300.0,
        ),)),
        storage_round_trip_efficiency=SimpleNamespace(
            status="available",
            round_trip_efficiency=0.83,
        ),
    )
    return snapshot, SimpleNamespace(segments=(due_segment,)), due_segment


def test_measured_pv_promotion_keeps_nom_when_target_is_covered() -> None:
    snapshot, path, due_segment = _pv_admission_fixture(
        promoted_to_central=True
    )

    assert _measured_pv_basis_covers_remaining_acquisition(
        snapshot=snapshot,
        path=path,
        due_segment=due_segment,
    )


def test_lagging_actual_pv_does_not_block_planned_grid_charge() -> None:
    snapshot, path, due_segment = _pv_admission_fixture(
        promoted_to_central=False
    )

    assert not _measured_pv_basis_covers_remaining_acquisition(
        snapshot=snapshot,
        path=path,
        due_segment=due_segment,
    )


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


def test_dashboard_presents_mep_execution_plan_without_legacy_outcomes(
    tmp_path,
) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, _store = _pipeline(tmp_path)

    run = pipeline.run(planning_input=snapshot)
    view = build_web_view(run, project(run))

    assert run.outcomes.outcomes == ()
    plans = view["planning_status"]["execution_plans"]
    chosen_plan = view["planning_status"]["chosen_plan"]
    assert len(plans) == 1
    assert plans[0]["plan_id"] == run.execution_plan_set.plans[0].plan_id
    assert plans[0]["execution_scope_id"] == (
        run.execution_plan_set.plans[0].execution_scope_id
    )
    assert plans[0]["segments"] == [
        {
            "starts_at": segment.starts_at.isoformat(),
            "ends_at": segment.ends_at.isoformat(),
            "primitive": segment.primitive.value,
            "purpose": segment.purpose,
            "requested_power_w": segment.requested_power_w,
            "charge_source_policy": (
                segment.charge_source_policy.value
                if segment.charge_source_policy is not None
                else None
            ),
        }
        for segment in run.execution_plan_set.plans[0].segments
    ]
    assert any(
        datetime.fromisoformat(segment["starts_at"]) > snapshot.captured_at
        for segment in plans[0]["segments"]
    )
    charge_segments = [
        segment
        for segment in run.execution_plan_set.plans[0].segments
        if segment.primitive.value == "charge_at_power"
    ]
    assert chosen_plan["plan_id"] == run.execution_plan_set.plans[0].plan_id
    assert chosen_plan["execution_scope_id"] == (
        run.execution_plan_set.plans[0].execution_scope_id
    )
    assert chosen_plan["initial_storage_energy_wh"] == (
        snapshot.current_storage_states[0].current_stored_energy_wh
    )
    assert chosen_plan["charge_window_starts_at"] == (
        charge_segments[0].starts_at.isoformat()
    )
    assert chosen_plan["charge_window_ends_at"] == (
        charge_segments[-1].ends_at.isoformat()
    )
    assert "renderBatteryEnergyPlan(" in DASHBOARD_HTML
    assert "view.planning_status?.execution_plans" in DASHBOARD_HTML
    assert "selectedExecutionPlanWindows(view)" in DASHBOARD_HTML
    assert "primitivePlanKind" in DASHBOARD_HTML
    assert view["planning_status"]["soc_timeline"][0] == {
        "at": snapshot.captured_at.isoformat(),
        "soc_percent": 51.0,
        "primitive": "actual",
    }
    assert len(view["planning_status"]["soc_timeline"]) > 1


def test_canonical_market_plan_preserves_nom_around_exact_grid_subwindow(
    tmp_path,
) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.2)
    cheap_window_end = snapshot.captured_at + timedelta(hours=12)
    horizon_end = snapshot.captured_at + timedelta(hours=24)
    source = snapshot.price_points[0]
    assert snapshot.pv_energy_timeline is not None
    midday_pv = replace(
        snapshot.pv_energy_timeline,
        intervals=tuple(
            replace(
                interval,
                pv_energy_wh=1000.0 if 10 <= index < 14 else 0.0,
                forecast_lower_energy_wh=800.0 if 10 <= index < 14 else 0.0,
                forecast_central_energy_wh=1000.0 if 10 <= index < 14 else 0.0,
                forecast_upper_energy_wh=1200.0 if 10 <= index < 14 else 0.0,
            )
            for index, interval in enumerate(snapshot.pv_energy_timeline.intervals)
        ),
    )
    priced = replace(
        snapshot,
        pv_energy_timeline=midday_pv,
        storage_round_trip_efficiency=StorageRoundTripEfficiencyEvidence(
            status="available",
            round_trip_efficiency=0.83,
            observed_at=snapshot.captured_at,
            source_entity_id="sensor.test_storage_rte",
            evidence_id="test-storage-rte",
            method_version="test-storage-rte:v1",
        ),
        price_points=(
            replace(
                source,
                point_id="broad-cheap-window",
                ends_at=cheap_window_end,
                value_eur_per_kwh=0.05,
            ),
            replace(
                source,
                point_id="later-export-window",
                starts_at=cheap_window_end,
                ends_at=horizon_end,
                value_eur_per_kwh=0.55,
            ),
        ),
    )
    pipeline, _store = _pipeline(tmp_path)

    run = pipeline.run(
        planning_input=priced,
        price_opportunity_config=PriceOpportunityConfig(
            low_price_margin_eur_per_kwh=0.10,
            high_price_margin_eur_per_kwh=0.10,
            config_version="test-price-opportunities:v1",
            market_timezone="UTC",
        ),
    )

    segments = run.execution_plan_set.plans[0].segments
    charge_index = next(
        index
        for index, segment in enumerate(segments)
        if segment.primitive.value == "charge_at_power"
    )
    charge = segments[charge_index]
    pv_peak_starts_at = midday_pv.intervals[10].starts_at
    pv_peak_ends_at = midday_pv.intervals[13].ends_at
    assert charge.starts_at > snapshot.captured_at
    assert segments[charge_index - 1].starts_at <= pv_peak_starts_at
    assert pv_peak_ends_at <= segments[charge_index - 1].ends_at
    assert charge.ends_at <= cheap_window_end - timedelta(minutes=15)
    assert charge.ends_at - charge.starts_at < timedelta(hours=12)
    assert charge.requested_power_w == 2400.0
    assert charge.charge_source_policy is not None
    assert charge.charge_source_policy.value == "pv_preferred_grid_allowed"
    assert segments[charge_index - 1].primitive.value == "balance_bidirectional"
    assert segments[charge_index + 1].primitive.value == "balance_bidirectional"
    assert segments[charge_index + 1].ends_at == cheap_window_end


def test_canonical_commitment_survives_next_mep_calculation(tmp_path) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path)
    first = pipeline.run(planning_input=snapshot)
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    commitment = store.load(scope_id)
    assert commitment is not None
    assert commitment.ends_at == commitment.segments[-1].ends_at

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

    view = build_web_view(continued, project(continued))
    chosen_plan = view["planning_status"]["chosen_plan"]
    assert chosen_plan["plan_revision"] == commitment.plan_revision
    assert chosen_plan["required_energy_wh"] == commitment.target_energy_wh
    assert chosen_plan["source_policy"] == commitment.source_policy
    assert chosen_plan["average_charge_window_price_eur_per_kwh"] == (
        commitment.average_charge_window_price_eur_per_kwh
    )
    assert chosen_plan["worst_case_financial_result_eur"] == (
        commitment.worst_case_financial_result_eur
    )
    assert chosen_plan["minimum_storage_energy_at_horizon_end_wh"] == (
        commitment.minimum_storage_energy_at_horizon_end_wh
    )
    assert chosen_plan["reserve_respected_across_scenarios"] == (
        commitment.reserve_respected_across_scenarios
    )
    assert chosen_plan["target_held_across_scenarios"] == (
        commitment.target_held_across_scenarios
    )


def test_charge_target_does_not_clear_later_export_commitment() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=1.0)
    starts_at = snapshot.captured_at
    export_start = starts_at + timedelta(hours=4)
    commitment = ActivePlanCommitment(
        execution_scope_id="battery",
        plan_id="market-plan",
        plan_revision=1,
        primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
        source_policy="pv_preferred_grid_allowed",
        starts_at=starts_at,
        ends_at=export_start + timedelta(minutes=30),
        target_energy_wh=8160.0,
        segments=(
            CommittedPlanSegment(
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
                source_policy="pv_preferred_grid_allowed",
            ),
            CommittedPlanSegment(
                starts_at=export_start,
                ends_at=export_start + timedelta(minutes=30),
                primitive=ExecutionPrimitive.DISCHARGE_AT_POWER.value,
                source_policy=None,
            ),
        ),
    )

    assert not _commitment_target_reached(snapshot, commitment)

    completed = _complete_acquisition_revision(
        snapshot=snapshot,
        commitment=commitment,
    )

    assert completed is not None
    assert completed.plan_revision == 2
    assert all(
        segment.primitive != ExecutionPrimitive.CHARGE_AT_POWER.value
        for segment in completed.segments
    )
    assert any(
        segment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value
        for segment in completed.segments
    )


def test_measured_progress_revision_moves_charge_to_last_safe_slot() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.87)
    starts_at = snapshot.captured_at
    nom_end = starts_at + timedelta(hours=5)
    export_start = nom_end + timedelta(hours=1)
    commitment = ActivePlanCommitment(
        execution_scope_id="battery",
        plan_id="market-plan",
        plan_revision=1,
        primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
        source_policy="pv_preferred_grid_allowed",
        starts_at=starts_at,
        ends_at=export_start + timedelta(minutes=30),
        target_energy_wh=8160.0,
        segments=(
            CommittedPlanSegment(
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
                source_policy="pv_preferred_grid_allowed",
            ),
            CommittedPlanSegment(
                starts_at=starts_at + timedelta(minutes=30),
                ends_at=nom_end,
                primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value,
                source_policy="pv_only",
            ),
            CommittedPlanSegment(
                starts_at=export_start,
                ends_at=export_start + timedelta(minutes=30),
                primitive=ExecutionPrimitive.DISCHARGE_AT_POWER.value,
                source_policy=None,
            ),
        ),
    )

    revised = _defer_charge_revision(
        snapshot=snapshot,
        commitment=commitment,
    )

    assert revised is not None
    assert revised.plan_revision == 2
    shifted_charge = next(
        segment
        for segment in revised.segments
        if segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value
    )
    assert shifted_charge.ends_at == nom_end - timedelta(minutes=15)
    assert shifted_charge.starts_at == shifted_charge.ends_at - timedelta(minutes=30)
    assert revised.segments[0].primitive == (
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value
    )
    assert revised.segments[-1].primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value


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
