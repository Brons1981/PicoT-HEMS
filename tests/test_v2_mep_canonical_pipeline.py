from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from test_independent_daily_reference_adapter import _conversion, _snapshot

import picot.planner.mep_candidate_outcomes as mep_candidate_outcomes
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import StorageRoundTripEfficiencyEvidence
from picot.v2.household_planning_regime import HouseholdPlanningRegime
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.mep_canonical_pipeline import (
    _commitment_target_reached,
    _complete_acquisition_revision,
    _defer_charge_revision,
    _measured_pv_basis_covers_remaining_acquisition,
    _pv_charge_progress_evidence,
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


def _pv_admission_fixture(
    *,
    promoted_to_central: bool,
    lower_wh: float | None = None,
    captured_at_offset: timedelta = timedelta(0),
    current_stored_energy_wh: float = 7000.0,
) -> tuple[object, object, object]:
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
    conservative_wh = (
        lower_wh if lower_wh is not None else central_wh if promoted_to_central else 400.0
    )
    snapshot = SimpleNamespace(
        captured_at=starts_at + captured_at_offset,
        storage_mode_capability_evidence=SimpleNamespace(current_vendor_mode="Nul op de meter"),
        current_storage_states=(
            SimpleNamespace(
                execution_scope_id="battery",
                capability_id="storage",
                current_stored_energy_wh=current_stored_energy_wh,
                usable_capacity_wh=8160.0,
            ),
        ),
        storage_physical_limits=(
            SimpleNamespace(
                execution_scope_id="battery",
                capability_id="storage",
                maximum_soc=1.0,
                maximum_charge_input_power_w=2400.0,
            ),
        ),
        pv_energy_timeline=SimpleNamespace(
            intervals=(
                SimpleNamespace(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    forecast_lower_energy_wh=conservative_wh,
                    forecast_central_energy_wh=central_wh,
                ),
            )
        ),
        household_load_forecast=SimpleNamespace(
            intervals=(
                SimpleNamespace(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    expected_energy_wh=300.0,
                ),
            )
        ),
        storage_round_trip_efficiency=SimpleNamespace(
            status="available",
            round_trip_efficiency=0.83,
        ),
    )
    return snapshot, SimpleNamespace(segments=(due_segment,)), due_segment


def test_measured_pv_promotion_keeps_nom_when_target_is_covered() -> None:
    snapshot, path, due_segment = _pv_admission_fixture(promoted_to_central=True)

    assert _measured_pv_basis_covers_remaining_acquisition(
        snapshot=snapshot,
        path=path,
        due_segment=due_segment,
    )


def test_lagging_actual_pv_does_not_block_planned_grid_charge() -> None:
    snapshot, path, due_segment = _pv_admission_fixture(promoted_to_central=False)

    assert not _measured_pv_basis_covers_remaining_acquisition(
        snapshot=snapshot,
        path=path,
        due_segment=due_segment,
    )


def test_missing_pv_measurements_fail_safe_to_planned_grid_charge() -> None:
    snapshot, path, due_segment = _pv_admission_fixture(promoted_to_central=True)
    snapshot.pv_energy_timeline = None

    evidence = _pv_charge_progress_evidence(
        snapshot=snapshot,
        path=path,
        due_segment=due_segment,
    )

    assert evidence.decision == "keep_grid_charge"
    assert evidence.reason == "future_pv_or_household_forecast_unavailable"


def test_conservative_pv_can_defer_grid_without_full_forecast_promotion() -> None:
    """Dev.217 uses actual SoC plus the lower PV lane, not exact lane equality."""

    snapshot, path, due_segment = _pv_admission_fixture(
        promoted_to_central=False,
        lower_wh=1800.0,
    )

    evidence = _pv_charge_progress_evidence(
        snapshot=snapshot,
        path=path,
        due_segment=due_segment,
    )

    assert evidence.decision == "defer_grid_charge"
    assert evidence.reason == "conservative_pv_can_cover_remaining_target"
    assert evidence.remaining_target_energy_wh == pytest.approx(1160.0)
    assert evidence.conservative_pv_to_storage_wh == pytest.approx(1245.0)
    assert evidence.required_grid_input_energy_wh == pytest.approx(1397.590361)
    assert evidence.latest_safe_grid_charge_starts_at is not None


def test_grid_charge_is_not_deferred_after_latest_safe_start() -> None:
    snapshot, path, due_segment = _pv_admission_fixture(
        promoted_to_central=True,
        captured_at_offset=timedelta(minutes=30),
        current_stored_energy_wh=7500.0,
    )

    evidence = _pv_charge_progress_evidence(
        snapshot=snapshot,
        path=path,
        due_segment=due_segment,
    )

    assert evidence.decision == "keep_grid_charge"
    assert evidence.reason == "latest_safe_grid_start_reached"


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
    assert (
        tuple(item.source_path_segment_id for item in execution_plan.segments)
        == winning_path.segment_ids
    )
    assert execution_plan.evaluation_id == run.evaluation.evaluation_id
    assert execution_plan.valid_from == snapshot.captured_at
    assert all(
        execution_segment.segment_id.startswith("execution-segment-")
        and execution_segment.starts_at == path_segment.starts_at
        and execution_segment.ends_at == path_segment.ends_at
        and execution_segment.primitive is path_segment.primitive
        and execution_segment.capability_id == path_segment.capability_id
        and execution_segment.purpose == path_segment.purpose
        and execution_segment.evidence_ids == path_segment.evidence_ids
        and execution_segment.requested_power_w == path_segment.requested_power_w
        and execution_segment.charge_source_policy
        is path_segment.charge_source_policy
        for execution_segment, path_segment in zip(
            execution_plan.segments,
            winning_path.segments,
            strict=True,
        )
    )
    commitment = store.load(snapshot.current_storage_states[0].execution_scope_id)
    assert commitment is not None
    assert commitment.planner_id == "mep"
    assert commitment.plan_id == execution_plan.plan_id
    assert commitment.schedule_id is not None
    assert commitment.selection_reason == run.evaluation.decisive_step
    assert len(commitment.segments) == len(winning_path.segments)
    assert commitment.starts_at == commitment.segments[0].starts_at
    assert commitment.primitive == commitment.segments[0].primitive
    assert commitment.segments[0].starts_at == winning_path.segments[0].starts_at
    assert commitment.segments[-1].ends_at == winning_path.segments[-1].ends_at
    assert commitment.selected_at == snapshot.captured_at
    assert commitment.household_load_intervals
    assert commitment.storage_energy_checkpoints
    assert all(
        checkpoint.lower_energy_wh <= checkpoint.central_energy_wh <= checkpoint.upper_energy_wh
        for checkpoint in commitment.storage_energy_checkpoints
    )


def test_low_pv_snapshot_publishes_valid_pv_first_residual_grid_candidate(
    tmp_path,
) -> None:
    """Dev.214: MEP offers PV capture before only the residual grid recovery."""

    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.5)
    pipeline, _store = _pipeline(tmp_path)

    run = pipeline.run(planning_input=snapshot)

    valid_ids = {
        outcome.candidate_id
        for outcome in run.outcomes.outcomes
        if outcome.validity == "valid"
        and outcome.daily_target_reached
        and outcome.household_reserve_respected
    }
    hybrid_paths = tuple(
        path
        for candidate in run.candidate_set.candidates
        for path in run.candidate_set.energy_paths
        if candidate.energy_path_id == path.path_id
        and candidate.family == "priority_first"
        and candidate.candidate_id in valid_ids
        and {segment.primitive for segment in path.segments}.issuperset(
            {
                ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                ExecutionPrimitive.CHARGE_AT_POWER,
            }
        )
    )
    assert hybrid_paths
    pv_first = next(
        path
        for path in hybrid_paths
        if any(
            segment.starts_at == snapshot.captured_at
            and segment.ends_at == snapshot.captured_at + timedelta(hours=1)
            and segment.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            for segment in path.segments
        )
    )
    hybrid_grid_seconds = sum(
        (segment.ends_at - segment.starts_at).total_seconds()
        for segment in pv_first.segments
        if segment.primitive is ExecutionPrimitive.CHARGE_AT_POWER
    )
    assert hybrid_grid_seconds == timedelta(minutes=75).total_seconds()


def test_hybrid_parent_publishes_valid_complete_market_path(tmp_path) -> None:
    """Dev.215: market trade extends PV capture plus residual grid recovery."""

    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.2)
    split = snapshot.captured_at + timedelta(hours=12)
    horizon_end = snapshot.captured_at + timedelta(hours=24)
    source = snapshot.price_points[0]
    priced = replace(
        snapshot,
        storage_round_trip_efficiency=StorageRoundTripEfficiencyEvidence(
            status="available",
            round_trip_efficiency=0.83,
            observed_at=snapshot.captured_at,
            source_entity_id="sensor.test_storage_rte",
            evidence_id="test-storage-rte",
            method_version="test-storage-rte:v1",
        ),
        price_points=(
            replace(source, point_id="cheap", ends_at=split, value_eur_per_kwh=0.05),
            replace(
                source,
                point_id="expensive",
                starts_at=split,
                ends_at=horizon_end,
                value_eur_per_kwh=2.00,
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

    valid_ids = {
        outcome.candidate_id
        for outcome in run.outcomes.outcomes
        if outcome.validity == "valid"
        and outcome.daily_target_reached
        and outcome.household_reserve_respected
    }
    complete_market_paths = tuple(
        path
        for candidate in run.candidate_set.candidates
        for path in run.candidate_set.energy_paths
        if candidate.energy_path_id == path.path_id
        and candidate.family == "market_route"
        and candidate.candidate_id in valid_ids
        and {segment.primitive for segment in path.segments}.issuperset(
            {
                ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                ExecutionPrimitive.CHARGE_AT_POWER,
                ExecutionPrimitive.DISCHARGE_AT_POWER,
            }
        )
    )

    assert complete_market_paths


def test_dashboard_presents_mep_execution_plan_with_comparable_outcomes(
    tmp_path,
) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, _store = _pipeline(tmp_path)

    run = pipeline.run(planning_input=snapshot)
    view = build_web_view(run, project(run))

    assert run.outcomes.candidate_ids == tuple(
        outcome.candidate_id for outcome in run.outcomes.outcomes
    )
    assert len(run.outcomes.outcomes) == len(run.candidate_set.candidates)
    assert all(
        outcome.comparison_horizon_start == snapshot.captured_at
        for outcome in run.outcomes.outcomes
    )
    plans = view["planning_status"]["execution_plans"]
    chosen_plan = view["planning_status"]["chosen_plan"]
    assert len(plans) == 1
    assert plans[0]["plan_id"] == run.execution_plan_set.plans[0].plan_id
    assert plans[0]["execution_scope_id"] == (run.execution_plan_set.plans[0].execution_scope_id)
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
    assert chosen_plan["execution_scope_id"] == (run.execution_plan_set.plans[0].execution_scope_id)
    assert chosen_plan["initial_storage_energy_wh"] == (
        snapshot.current_storage_states[0].current_stored_energy_wh
    )
    assert chosen_plan["charge_window_starts_at"] == (charge_segments[0].starts_at.isoformat())
    assert chosen_plan["charge_window_ends_at"] == (charge_segments[-1].ends_at.isoformat())
    assert "renderBatteryEnergyPlan(" in DASHBOARD_HTML
    assert "view.planning_status?.execution_plans" in DASHBOARD_HTML
    assert "selectedExecutionPlanWindows(view)" in DASHBOARD_HTML
    assert "primitivePlanKind" in DASHBOARD_HTML
    winning_path = next(
        path
        for path in run.candidate_set.energy_paths
        if path.path_id == run.evaluation.winning_energy_path_id
    )
    expected_soc_timeline = [{
        "at": snapshot.captured_at.isoformat(),
        "soc_percent": 51.0,
        "primitive": "actual",
    }]
    for state in winning_path.projected_states:
        if state.at <= snapshot.captured_at or state.battery_soc is None:
            continue
        segment = next(
            item
            for item in winning_path.segments
            if item.starts_at < state.at <= item.ends_at
        )
        expected_soc_timeline.append({
            "at": state.at.isoformat(),
            "soc_percent": round(state.battery_soc * 100, 2),
            "primitive": segment.primitive.value,
        })
    assert view["planning_status"]["soc_timeline"] == expected_soc_timeline


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

    market_candidate_ids = {
        candidate.candidate_id
        for candidate in run.candidate_set.candidates
        if candidate.family == "market_route"
    }
    market_paths = tuple(
        path
        for path in run.candidate_set.energy_paths
        if any(
            candidate.energy_path_id == path.path_id
            and candidate.candidate_id in market_candidate_ids
            for candidate in run.candidate_set.candidates
        )
    )
    assert market_paths
    assert all(path.projected_states for path in market_paths)
    assert all(
        state.storage_energy_wh
        == pytest.approx(
            state.battery_soc
            * snapshot.current_storage_states[0].usable_capacity_wh
        )
        for path in market_paths
        for state in path.projected_states
        if state.battery_soc is not None and state.storage_energy_wh is not None
    )
    charge_index = next(
        (path, index)
        for path in market_paths
        for index, segment in enumerate(path.segments)
        if segment.primitive.value == "charge_at_power"
        and segment.starts_at >= midday_pv.intervals[13].ends_at
        and segment.ends_at <= cheap_window_end - timedelta(minutes=15)
    )
    path, charge_index = charge_index
    segments = path.segments
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

    valid_market_outcomes = tuple(
        outcome
        for outcome in run.outcomes.outcomes
        if outcome.candidate_id in market_candidate_ids and outcome.validity == "valid"
    )
    assert valid_market_outcomes
    assert all(outcome.daily_target_reached for outcome in valid_market_outcomes)
    assert all(
        outcome.daily_target_reached_at <= outcome.daily_target_required_by
        for outcome in valid_market_outcomes
        if outcome.daily_target_reached_at is not None
    )
    assert all(
        outcome.household_reserve_respected for outcome in valid_market_outcomes
    )


def test_mep_separates_daily_maximum_target_from_household_reserve(
    tmp_path,
) -> None:
    """ADR-037: 100% remains the target; reserve is a separate hard outcome."""

    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.60)
    pipeline, _store = _pipeline(tmp_path)

    run = pipeline.run(planning_input=snapshot)

    requirement = run.candidate_set.storage_requirements[0]
    assert requirement.requirement_kind == "daily_storage_target"
    assert requirement.satisfaction_mode == "reached_by"
    assert requirement.required_soc == 1.0
    valid_outcomes = tuple(
        outcome for outcome in run.outcomes.outcomes if outcome.validity == "valid"
    )
    assert valid_outcomes
    assert all(outcome.daily_target_reached for outcome in valid_outcomes)
    assert all(outcome.household_reserve_respected for outcome in valid_outcomes)


def test_rolling_horizon_compares_fresh_challengers_without_rewriting_them(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path)
    pipeline.run(planning_input=snapshot)
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    commitment = store.load(scope_id)
    assert commitment is not None
    assert commitment.ends_at == commitment.segments[-1].ends_at
    extended_horizon = commitment.ends_at + timedelta(hours=6)
    assert snapshot.household_load_forecast is not None
    assert snapshot.pv_energy_timeline is not None
    household_template = snapshot.household_load_forecast.intervals[-1]
    pv_template = snapshot.pv_energy_timeline.intervals[-1]
    extra_household = tuple(
        replace(
            household_template,
            interval_id=f"household-next-day-{index}",
            starts_at=commitment.ends_at + index * timedelta(minutes=15),
            ends_at=commitment.ends_at + (index + 1) * timedelta(minutes=15),
        )
        for index in range(24)
    )
    extra_pv = tuple(
        replace(
            pv_template,
            interval_id=f"pv-next-day-{index}",
            starts_at=commitment.ends_at + index * timedelta(minutes=15),
            ends_at=commitment.ends_at + (index + 1) * timedelta(minutes=15),
        )
        for index in range(24)
    )
    extended_snapshot = replace(
        snapshot,
        horizon_end=extended_horizon,
        price_points=(
            replace(snapshot.price_points[0], ends_at=extended_horizon),
        ),
        household_load_forecast=replace(
            snapshot.household_load_forecast,
            intervals=(*snapshot.household_load_forecast.intervals, *extra_household),
        ),
        pv_energy_timeline=replace(
            snapshot.pv_energy_timeline,
            intervals=(*snapshot.pv_energy_timeline.intervals, *extra_pv),
        ),
    )
    simulation_calls = 0
    original_simulation = mep_candidate_outcomes._simulate_committed

    def counting_simulation(**kwargs):
        nonlocal simulation_calls
        simulation_calls += 1
        return original_simulation(**kwargs)

    monkeypatch.setattr(
        mep_candidate_outcomes,
        "_simulate_committed",
        counting_simulation,
    )

    continued = pipeline.run(
        planning_input=replace(
            extended_snapshot,
            active_plan_commitments=(commitment,),
        )
    )

    assert commitment.ends_at < extended_horizon
    assert continued.execution_plan_set.plans[0].valid_until == extended_horizon
    challenger_paths = tuple(
        path
        for candidate in continued.candidate_set.candidates
        for path in continued.candidate_set.energy_paths
        if candidate.energy_path_id == path.path_id
        and candidate.candidate_id != continued.evaluation.incumbent_candidate_id
    )
    assert challenger_paths
    assert any(
        segment.primitive is ExecutionPrimitive.CHARGE_AT_POWER
        and segment.starts_at < commitment.ends_at
        for path in challenger_paths
        for segment in path.segments
    )
    # V2ADR-062: challengers already originate from the same fresh snapshot and
    # remaining horizon. Only the incumbent requires one fresh simulation.
    assert simulation_calls == 1

    view = build_web_view(continued, project(continued))
    chosen_plan = view["planning_status"]["chosen_plan"]
    assert chosen_plan["valid_until"] == extended_horizon.isoformat()


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


def test_export_first_commitment_preserves_later_recovery_charge() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.98)
    starts_at = snapshot.captured_at
    export_end = starts_at + timedelta(hours=2)
    recovery_start = starts_at + timedelta(hours=14)
    recovery_end = recovery_start + timedelta(hours=2, minutes=15)
    commitment = ActivePlanCommitment(
        execution_scope_id="battery",
        plan_id="export-then-recovery",
        plan_revision=1,
        primitive=ExecutionPrimitive.DISCHARGE_AT_POWER.value,
        source_policy="not_applicable",
        starts_at=starts_at,
        ends_at=recovery_end + timedelta(hours=2, minutes=15),
        # A discharge-first commitment stores the safe post-export target.
        target_energy_wh=2448.0,
        segments=(
            CommittedPlanSegment(
                starts_at=starts_at,
                ends_at=export_end,
                primitive=ExecutionPrimitive.DISCHARGE_AT_POWER.value,
                source_policy=None,
            ),
            CommittedPlanSegment(
                starts_at=export_end,
                ends_at=recovery_start,
                primitive=ExecutionPrimitive.BALANCE_DISCHARGE_ONLY.value,
                source_policy=None,
            ),
            CommittedPlanSegment(
                starts_at=recovery_start,
                ends_at=recovery_end,
                primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
                source_policy="pv_preferred_grid_allowed",
            ),
            CommittedPlanSegment(
                starts_at=recovery_end,
                ends_at=recovery_end + timedelta(hours=2, minutes=15),
                primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value,
                source_policy="pv_only",
            ),
        ),
    )

    completed = _complete_acquisition_revision(
        snapshot=snapshot,
        commitment=commitment,
    )

    assert completed is None
    assert any(
        segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value
        for segment in commitment.segments
    )


def test_completed_acquisition_coalesces_adjacent_nom_segments() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=1.0)
    starts_at = snapshot.captured_at
    export_start = starts_at + timedelta(hours=4)
    commitment = ActivePlanCommitment(
        execution_scope_id="battery",
        plan_id="nom-charge-nom-export",
        plan_revision=1,
        primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value,
        source_policy="pv_only",
        starts_at=starts_at,
        ends_at=export_start + timedelta(minutes=30),
        target_energy_wh=8160.0,
        segments=(
            CommittedPlanSegment(
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=15),
                primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value,
                source_policy="pv_only",
            ),
            CommittedPlanSegment(
                starts_at=starts_at + timedelta(minutes=15),
                ends_at=starts_at + timedelta(minutes=45),
                primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
                source_policy="pv_preferred_grid_allowed",
            ),
            CommittedPlanSegment(
                starts_at=starts_at + timedelta(minutes=45),
                ends_at=export_start,
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

    completed = _complete_acquisition_revision(
        snapshot=snapshot,
        commitment=commitment,
    )

    assert completed is not None
    assert len(completed.segments) == 2
    assert completed.segments[0].starts_at == starts_at
    assert completed.segments[0].ends_at == export_start
    assert completed.segments[0].primitive == (ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value)


def test_completed_pre_export_acquisition_preserves_post_export_recovery() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=1.0)
    starts_at = snapshot.captured_at
    export_start = starts_at + timedelta(hours=4)
    export_end = export_start + timedelta(minutes=30)
    commitment = ActivePlanCommitment(
        execution_scope_id="battery",
        plan_id="acquire-export-recover",
        plan_revision=1,
        primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
        source_policy="pv_preferred_grid_allowed",
        starts_at=starts_at,
        ends_at=export_end + timedelta(hours=2),
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
                ends_at=export_end,
                primitive=ExecutionPrimitive.DISCHARGE_AT_POWER.value,
                source_policy=None,
            ),
            CommittedPlanSegment(
                starts_at=export_end,
                ends_at=export_end + timedelta(hours=2),
                primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
                source_policy="pv_preferred_grid_allowed",
            ),
        ),
    )

    completed = _complete_acquisition_revision(
        snapshot=snapshot,
        commitment=commitment,
    )

    assert completed is not None
    remaining_charges = tuple(
        segment
        for segment in completed.segments
        if segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value
    )
    assert len(remaining_charges) == 1
    assert remaining_charges[0].starts_at == export_end


def test_measured_progress_revision_moves_charge_to_last_safe_slot() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.90)
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
    expected_duration = timedelta(hours=(816.0 / 0.8) / 2400.0)
    assert shifted_charge.starts_at == shifted_charge.ends_at - expected_duration
    assert revised.segments[0].primitive == (ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value)
    assert revised.segments[-1].primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value


def test_market_planner_generates_and_evaluation_selects() -> None:
    planner_source = __import__(
        "picot.planner.market_daily_planner",
        fromlist=["MarketDailyPlanner"],
    ).__loader__.get_source("picot.planner.market_daily_planner")
    evaluation_source = __import__(
        "picot.planner.market_daily_evaluation_engine",
        fromlist=["MarketDailyEvaluationEngine"],
    ).__loader__.get_source("picot.planner.market_daily_evaluation_engine")

    assert "def _current_decision" not in planner_source
    assert "best_observation_ids" not in planner_source
    assert "class MarketDailyEvaluationEngine" in evaluation_source
    assert "def current_decision" in evaluation_source


def test_incumbent_with_incomplete_path_is_invalid_and_replaced(
    tmp_path,
) -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    pipeline, store = _pipeline(tmp_path)
    first = pipeline.run(planning_input=snapshot)
    scope_id = snapshot.current_storage_states[0].execution_scope_id
    commitment = store.load(scope_id)
    assert commitment is not None
    incomplete = replace(
        commitment,
        segments=commitment.segments[1:],
    )
    store.save(incomplete)

    continued = pipeline.run(
        planning_input=replace(snapshot, active_plan_commitments=(incomplete,))
    )

    replacement = store.load(scope_id)
    assert replacement is not None
    assert replacement.plan_id != first.execution_plan_set.plans[0].plan_id
    assert replacement.plan_revision == incomplete.plan_revision + 1
    assert replacement.replaced_plan_id == incomplete.plan_id
    incumbent_outcome = next(
        outcome for outcome in continued.outcomes.outcomes if outcome.incumbent
    )
    assert incumbent_outcome.validity == "invalid"
    assert "committed_schedule_gap" in incumbent_outcome.invalidity_reasons


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
        worst_case_financial_result_eur=(commitment.worst_case_financial_result_eur - 0.01),
    )
    store.save(incumbent)

    continued = pipeline.run(planning_input=replace(snapshot, active_plan_commitments=(incumbent,)))

    assert continued.execution_plan_set.plans[0].plan_id == commitment.plan_id
    assert store.load(scope_id) == incumbent
    assert continued.evaluation.decisive_step == ("commitment:equivalent_incumbent_retained")


def test_historical_financial_result_cannot_replace_fresh_incumbent(tmp_path) -> None:
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

    continued = pipeline.run(planning_input=replace(snapshot, active_plan_commitments=(incumbent,)))

    assert store.load(scope_id) == incumbent
    assert continued.execution_plan_set.plans[0].plan_id == incumbent.plan_id
    assert continued.evaluation.decisive_step == ("commitment:equivalent_incumbent_retained")


def test_household_requirement_invalidates_late_incumbent_before_evaluation(
    tmp_path,
) -> None:
    """ADR-037/V2ADR-062: commitment cannot hide a fresh physical deadline."""

    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.30)
    assert snapshot.pv_energy_timeline is not None
    source = snapshot.price_points[0]
    late_charge_start = snapshot.captured_at + timedelta(hours=12)
    late_charge_end = late_charge_start + timedelta(hours=3)
    horizon_end = snapshot.captured_at + timedelta(hours=24)
    dark = replace(
        snapshot,
        pv_energy_timeline=replace(
            snapshot.pv_energy_timeline,
            intervals=tuple(
                replace(
                    item,
                    pv_energy_wh=0.0,
                    forecast_lower_energy_wh=0.0,
                    forecast_central_energy_wh=0.0,
                    forecast_upper_energy_wh=0.0,
                )
                for item in snapshot.pv_energy_timeline.intervals
            ),
        ),
        price_points=(
            replace(
                source,
                point_id="current-cheap",
                ends_at=snapshot.captured_at + timedelta(hours=3),
                value_eur_per_kwh=0.13,
            ),
            replace(
                source,
                point_id="expensive-before-late-charge",
                starts_at=snapshot.captured_at + timedelta(hours=3),
                ends_at=late_charge_start,
                value_eur_per_kwh=0.40,
            ),
            replace(
                source,
                point_id="later-cheap",
                starts_at=late_charge_start,
                ends_at=horizon_end,
                value_eur_per_kwh=0.10,
            ),
        ),
    )
    incumbent = ActivePlanCommitment(
        execution_scope_id="battery",
        plan_id="late-incumbent",
        plan_revision=1,
        primitive=ExecutionPrimitive.BALANCE_DISCHARGE_ONLY.value,
        source_policy="not_applicable",
        starts_at=dark.captured_at,
        ends_at=horizon_end,
        target_energy_wh=8160.0,
        segments=(
            CommittedPlanSegment(
                starts_at=dark.captured_at,
                ends_at=late_charge_start,
                primitive=ExecutionPrimitive.BALANCE_DISCHARGE_ONLY.value,
                source_policy=None,
            ),
            CommittedPlanSegment(
                starts_at=late_charge_start,
                ends_at=late_charge_end,
                primitive=ExecutionPrimitive.CHARGE_AT_POWER.value,
                source_policy="pv_preferred_grid_allowed",
            ),
            CommittedPlanSegment(
                starts_at=late_charge_end,
                ends_at=horizon_end,
                primitive=ExecutionPrimitive.BALANCE_DISCHARGE_ONLY.value,
                source_policy=None,
            ),
        ),
    )
    planning_input = replace(dark, active_plan_commitments=(incumbent,))
    pipeline, store = _pipeline(tmp_path)

    run = pipeline.run(planning_input=planning_input)

    assert len(run.candidate_set.storage_requirements) == 1
    requirement = run.candidate_set.storage_requirements[0]
    assert requirement.required_by < late_charge_start
    incumbent_outcome = next(item for item in run.outcomes.outcomes if item.incumbent)
    assert incumbent_outcome.validity == "invalid"
    assert incumbent_outcome.daily_target_reached is False
    assert incumbent_outcome.daily_target_reached_at is None
    assert "daily_storage_target_not_reached_by_deadline" in (
        incumbent_outcome.invalidity_reasons
    )
    assert run.evaluation.commitment_decision == "replaced"
    assert run.evaluation.winning_candidate_id != incumbent_outcome.candidate_id
    replacement = store.load("battery")
    assert replacement is not None
    assert replacement.plan_id != incumbent.plan_id
    assert any(
        segment.primitive is ExecutionPrimitive.CHARGE_AT_POWER
        and segment.starts_at == dark.captured_at
        and segment.ends_at <= requirement.required_by
        for segment in run.execution_plan_set.plans[0].segments
    )


def test_identical_incumbent_and_challenger_use_equal_wear_adjusted_finance(
    tmp_path,
) -> None:
    """V2ADR-062: equal remaining paths use symmetric current outcomes."""

    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.20)
    source = snapshot.price_points[0]
    export_start = snapshot.captured_at + timedelta(hours=12)
    horizon_end = snapshot.captured_at + timedelta(hours=24)
    priced = replace(
        snapshot,
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
                point_id="cheap-acquisition",
                ends_at=export_start,
                value_eur_per_kwh=0.05,
            ),
            replace(
                source,
                point_id="valuable-export",
                starts_at=export_start,
                ends_at=horizon_end,
                value_eur_per_kwh=0.55,
            ),
        ),
    )
    pipeline, _store = _pipeline(tmp_path)
    config = PriceOpportunityConfig(
        low_price_margin_eur_per_kwh=0.10,
        high_price_margin_eur_per_kwh=0.10,
        config_version="test-price-opportunities:v1",
        market_timezone="UTC",
    )
    first = pipeline.run(planning_input=priced, price_opportunity_config=config)
    valid_ids = {
        item.candidate_id
        for item in first.outcomes.outcomes
        if item.validity == "valid"
    }
    market_candidate = next(
        candidate
        for candidate in first.candidate_set.candidates
        if candidate.family == "market_route"
        and candidate.candidate_id in valid_ids
        and any(
            segment.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER
            for path in first.candidate_set.energy_paths
            if path.path_id == candidate.energy_path_id
            for segment in path.segments
        )
    )
    market_path = next(
        path
        for path in first.candidate_set.energy_paths
        if path.path_id == market_candidate.energy_path_id
    )
    incumbent = ActivePlanCommitment(
        execution_scope_id="battery",
        plan_id="wear-symmetric-incumbent",
        plan_revision=1,
        primitive=market_path.segments[0].primitive.value,
        source_policy=(
            market_path.segments[0].charge_source_policy.value
            if market_path.segments[0].charge_source_policy is not None
            else "not_applicable"
        ),
        starts_at=market_path.segments[0].starts_at,
        ends_at=market_path.segments[-1].ends_at,
        target_energy_wh=8160.0,
        segments=tuple(
            CommittedPlanSegment(
                starts_at=segment.starts_at,
                ends_at=segment.ends_at,
                primitive=segment.primitive.value,
                source_policy=(
                    segment.charge_source_policy.value
                    if segment.charge_source_policy is not None
                    else None
                ),
                storage_export_target_wh=(
                    (segment.requested_power_w or 0.0)
                    * (segment.ends_at - segment.starts_at).total_seconds()
                    / 3600.0
                    if segment.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER
                    else None
                ),
            )
            for segment in market_path.segments
        ),
    )

    continued = pipeline.run(
        planning_input=replace(priced, active_plan_commitments=(incumbent,)),
        price_opportunity_config=config,
    )

    incumbent_candidate = next(
        item for item in continued.candidate_set.candidates if item.family == "committed"
    )
    incumbent_path = next(
        item
        for item in continued.candidate_set.energy_paths
        if item.path_id == incumbent_candidate.energy_path_id
    )

    def schedule_signature(path):
        return tuple(
            (
                segment.starts_at,
                segment.ends_at,
                segment.primitive,
                segment.requested_power_w,
                segment.charge_source_policy,
            )
            for segment in path.segments
        )

    matching_path = next(
        item
        for item in continued.candidate_set.energy_paths
        if item.family != "committed"
        and schedule_signature(item) == schedule_signature(incumbent_path)
    )
    matching_candidate = next(
        item
        for item in continued.candidate_set.candidates
        if item.energy_path_id == matching_path.path_id
    )
    incumbent_outcome = next(
        item
        for item in continued.outcomes.outcomes
        if item.candidate_id == incumbent_candidate.candidate_id
    )
    challenger_outcome = next(
        item
        for item in continued.outcomes.outcomes
        if item.candidate_id == matching_candidate.candidate_id
    )

    assert incumbent_outcome.worst_case_financial_result_eur == pytest.approx(
        challenger_outcome.worst_case_financial_result_eur,
        abs=1e-9,
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
        worst_case_financial_result_eur=(commitment.worst_case_financial_result_eur - 0.01),
    )
    store.save(incumbent)

    continued = pipeline.run(planning_input=replace(snapshot, active_plan_commitments=(incumbent,)))

    assert continued.evaluation.financial_equivalence_margin_eur == 0.005
    assert continued.evaluation.decisive_step == ("commitment:equivalent_incumbent_retained")


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

    run = pipeline.run(planning_input=replace(snapshot, household_planning_regime=regime))

    assert run.candidate_set.derivation_status == "ready"
    assert run.evaluation.status == "winner_selected"
    assert run.execution_plan_set.plans
