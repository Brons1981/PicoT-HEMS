from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.energy_contract import EnergyContractSnapshot, EnergyTariffInterval
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.delegated_storage_evaluation_engine import (
    DelegatedStorageEvaluationEngine,
)
from picot.v2.canonical_reference_observer import CanonicalReferenceObserver
from picot.v2.contracts import (
    CurrentStorageState,
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PlanningInputSnapshot,
    PriceForecastPoint,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.household_planning_regime import (
    AdaptiveHouseholdObjectivePolicy,
    UserObjectiveProfile,
    derive_household_planning_regime,
)
from picot.v2.pipeline import (
    CanonicalPipeline,
    _average_price_for_window,
    _balance_for_pv_forecast_basis,
)
from picot.v2.plan_commitment_store import ActivePlanCommitment
from picot.v2.projection import project
from picot.v2.pv_forecast_assumptions import derive_pv_forecast_basis_assumptions
from picot.v2.web_ui import _build_plan_explanation

BASE = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
WINDOW_END = BASE + timedelta(hours=1)
HORIZON_END = BASE + timedelta(hours=2)
RUN_ID = "run-delegated-pipeline-test"
SNAPSHOT_ID = "snapshot-delegated-pipeline-test"
CAPABILITY_ID = "storage-capability-home-battery"


def _snapshot() -> PlanningInputSnapshot:
    capability = LogicalCapabilitySnapshot(
        capability_id=CAPABILITY_ID,
        execution_scope_id="home-battery",
        supported_primitives=(ExecutionPrimitive.BALANCE_CHARGE_ONLY,),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=BASE,
        confidence=1.0,
        source_mapping_id="storage-mode-options:v1",
        adapter_contract_version="1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
    )
    storage = CurrentStorageState(
        storage_state_id="storage-home",
        execution_scope_id="home-battery",
        capability_id=CAPABILITY_ID,
        current_soc=1000.0 / 1200.0,
        usable_capacity_wh=1200.0,
        measured_at=BASE,
        confidence=0.9,
        evidence_ids=("storage-evidence",),
    )
    pv_intervals = (
        PVEnergyTimelineInterval(
            interval_id="pv-window",
            starts_at=BASE,
            ends_at=WINDOW_END,
            pv_energy_wh=800.0,
            evidence_type="FORECAST",
            confidence=0.8,
            actual_evidence_ids=(),
            forecast_evidence_ids=("pv-window-evidence",),
            conversion_method_version="forecast-energy:v1",
        ),
        PVEnergyTimelineInterval(
            interval_id="pv-after",
            starts_at=WINDOW_END,
            ends_at=HORIZON_END,
            pv_energy_wh=0.0,
            evidence_type="FORECAST",
            confidence=0.8,
            actual_evidence_ids=(),
            forecast_evidence_ids=("pv-after-evidence",),
            conversion_method_version="forecast-energy:v1",
        ),
    )
    load_intervals = (
        HouseholdLoadForecastInterval(
            interval_id="load-window",
            starts_at=BASE,
            ends_at=WINDOW_END,
            expected_energy_wh=200.0,
            confidence=0.7,
            source_reference="load-window-evidence",
            method_version="test-load:v1",
        ),
        HouseholdLoadForecastInterval(
            interval_id="load-after",
            starts_at=WINDOW_END,
            ends_at=HORIZON_END,
            expected_energy_wh=200.0,
            confidence=0.7,
            source_reference="load-after-evidence",
            method_version="test-load:v1",
        ),
    )
    return PlanningInputSnapshot(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        captured_at=BASE,
        picot_version="test",
        architecture_baseline_commit="test",
        pipeline_contract_version=1,
        strategy_id="strategy:test",
        horizon_end=HORIZON_END,
        current_storage_states=(storage,),
        pv_energy_timeline=PVEnergyTimeline(
            timeline_id="pv-timeline",
            run_id=RUN_ID,
            snapshot_id=SNAPSHOT_ID,
            intervals=pv_intervals,
        ),
        household_load_forecast=HouseholdLoadForecast(
            forecast_id="load-forecast",
            run_id=RUN_ID,
            snapshot_id=SNAPSHOT_ID,
            intervals=load_intervals,
            fallback_active=False,
            fallback_reason=None,
        ),
        capability_snapshot_set=CapabilitySnapshotSet(
            snapshot_id=SNAPSHOT_ID,
            mapping_version=1,
            captured_at=BASE,
            capabilities=(capability,),
        ),
    )


def test_canonical_pipeline_exposes_baseline_timed_candidate_and_outcome() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())

    assert [candidate.family for candidate in run.candidate_set.candidates] == [
        "reserve_first",
        "pv_charge_only",
    ]
    assert [path.family for path in run.candidate_set.energy_paths] == [
        "reserve_first",
        "pv_charge_only",
    ]
    assert len(run.outcomes.outcomes) == 1
    outcome = run.outcomes.outcomes[0]
    assert outcome.pv_storage_contribution_wh == pytest.approx(200.0)
    assert outcome.grid_storage_contribution_wh == pytest.approx(0.0)
    assert outcome.storage_energy_at_window_end_wh == pytest.approx(1200.0)
    assert outcome.storage_energy_at_requirement_wh == pytest.approx(1200.0)
    assert outcome.requirement_satisfied is True


def test_reference_observer_is_blocked_without_required_contract_evidence() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())

    assert run.reference_simulations.candidate_set_id == run.candidate_set.candidate_set_id
    assert tuple(
        item.candidate_id for item in run.reference_simulations.observations
    ) == tuple(item.candidate_id for item in run.candidate_set.candidates)
    assert all(
        item.status == "blocked"
        and item.blockers == (
            "energy_contract_snapshot_missing",
            "storage_conversion_model_missing",
        )
        for item in run.reference_simulations.observations
    )
    assert run.evaluation.winning_candidate_id == run.outcomes.outcomes[0].candidate_id


def test_reference_observer_simulates_supported_baseline_without_affecting_winner() -> None:
    source = _snapshot()
    assert source.horizon_end is not None
    assert source.pv_energy_timeline is not None
    tariffs = tuple(
        EnergyTariffInterval.basic(
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            import_eur_per_kwh=0.25,
            export_eur_per_kwh=0.10,
            evidence_ids=(f"tariff:{item.interval_id}",),
        )
        for item in source.pv_energy_timeline.intervals
    )
    snapshot = replace(
        source,
        energy_contract_snapshot=EnergyContractSnapshot(
            contract_snapshot_id="contract-snapshot-1",
            captured_at=BASE,
            valid_from=BASE,
            valid_until=source.horizon_end,
            settlement_timezone="Europe/Amsterdam",
            settlement_rule_id="dynamic-quarter-hour:v1",
            contract_version="contract:v1",
            permits_grid_import=True,
            permits_grid_export=True,
            permits_battery_export=False,
            intervals=tariffs,
        ),
        storage_conversion_model=StorageConversionModel(
            model_id="conversion-model-1",
            charge_efficiency=0.90,
            discharge_efficiency=0.90,
            evidence_ids=("storage-efficiency:1",),
            method_version="fixed-directional-efficiency:v1",
        ),
    )

    run = CanonicalPipeline().run(planning_input=snapshot)
    baseline = next(
        item
        for item in run.reference_simulations.observations
        if item.candidate_id == run.candidate_set.candidates[0].candidate_id
    )
    delegated = next(
        item
        for item in run.reference_simulations.observations
        if item.candidate_id == run.candidate_set.candidates[1].candidate_id
    )

    assert baseline.status == "ready"
    assert baseline.ledger is not None
    assert baseline.reference_grid_import_wh == pytest.approx(200.0)
    assert baseline.reference_grid_export_wh == pytest.approx(600.0)
    assert delegated.status == "blocked"
    assert delegated.blockers == ("unsupported_primitive:balance_charge_only",)
    assert run.evaluation.winning_candidate_id == run.candidate_set.candidates[1].candidate_id


def test_reference_observer_normalises_coarse_energy_to_tariff_intervals() -> None:
    source = _snapshot()
    assert source.horizon_end is not None
    assert source.pv_energy_timeline is not None
    tariffs = tuple(
        EnergyTariffInterval.basic(
            starts_at=starts_at,
            ends_at=ends_at,
            import_eur_per_kwh=0.25,
            export_eur_per_kwh=0.10,
            evidence_ids=(f"tariff:{item.interval_id}:{index}",),
        )
        for item in source.pv_energy_timeline.intervals
        for index, (starts_at, ends_at) in enumerate(
            (
                (item.starts_at, item.starts_at + (item.ends_at - item.starts_at) / 2),
                (item.starts_at + (item.ends_at - item.starts_at) / 2, item.ends_at),
            )
        )
    )
    snapshot = replace(
        source,
        energy_contract_snapshot=EnergyContractSnapshot(
            contract_snapshot_id="contract-snapshot-split",
            captured_at=BASE,
            valid_from=BASE,
            valid_until=source.horizon_end,
            settlement_timezone="Europe/Amsterdam",
            settlement_rule_id="split-reference:test",
            contract_version="contract:v1",
            permits_grid_import=True,
            permits_grid_export=True,
            permits_battery_export=False,
            intervals=tariffs,
        ),
        storage_conversion_model=StorageConversionModel(
            model_id="conversion-model-1",
            charge_efficiency=0.90,
            discharge_efficiency=0.90,
            evidence_ids=("storage-efficiency:1",),
            method_version="fixed-directional-efficiency:v1",
        ),
    )

    run = CanonicalPipeline().run(planning_input=snapshot)
    baseline = run.reference_simulations.observations[0]

    assert baseline.status == "ready"
    assert baseline.ledger is not None
    assert len(baseline.ledger.intervals) == len(tariffs)
    assert baseline.reference_grid_import_wh == pytest.approx(200.0)
    assert baseline.reference_grid_export_wh == pytest.approx(600.0)
    assert sum(item.usable_pv_wh for item in baseline.ledger.intervals) == pytest.approx(
        800.0
    )
    assert sum(
        item.household_demand_wh for item in baseline.ledger.intervals
    ) == pytest.approx(400.0)


def test_reference_interval_normalisation_fails_closed_on_evidence_gap() -> None:
    with pytest.raises(ValueError, match="must fully cover"):
        CanonicalReferenceObserver._allocate_energy(
            starts_at=BASE,
            ends_at=BASE + timedelta(minutes=30),
            sources=(
                (
                    BASE,
                    BASE + timedelta(minutes=15),
                    100.0,
                    0.8,
                ),
            ),
        )


def test_reference_observer_failure_cannot_stop_or_change_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingObserver:
        def observe(self, **_: object) -> None:
            raise RuntimeError("observer must remain isolated")

    monkeypatch.setattr(
        "picot.v2.pipeline.CanonicalReferenceObserver",
        FailingObserver,
    )

    run = CanonicalPipeline().run(planning_input=_snapshot())

    assert run.reference_simulations.observations == ()
    assert run.reference_simulations.global_blockers == (
        "observer_failure:RuntimeError",
    )
    assert run.evaluation.winning_candidate_id == run.candidate_set.candidates[1].candidate_id
    assert run.execution_plan_set.winning_energy_path_id == (
        run.evaluation.winning_energy_path_id
    )


def test_projection_exposes_timed_candidate_window() -> None:
    projection = project(CanonicalPipeline().run(planning_input=_snapshot()))
    candidate_card = projection.cards[2]

    assert candidate_card.attributes["timed_storage_candidate_count"] == 1
    timed = candidate_card.attributes["timed_storage_candidates"][0]
    assert timed["family"] == "pv_charge_only"
    assert timed["primitive"] == "balance_charge_only"
    assert timed["charge_source_policy"] == "pv_only"
    assert timed["starts_at"] == BASE.isoformat()
    assert timed["ends_at"] == WINDOW_END.isoformat()
    assert timed["pv_storage_contribution_kwh"] == pytest.approx(0.2)
    assert timed["grid_storage_contribution_kwh"] == pytest.approx(0.0)
    assert timed["storage_energy_at_requirement_kwh"] == pytest.approx(1.2)
    assert timed["confidence"] == pytest.approx(0.7)


def test_evaluation_selects_requirement_satisfying_path_deterministically() -> None:
    first = CanonicalPipeline().run(planning_input=_snapshot())
    second = CanonicalPipeline().run(planning_input=_snapshot())

    delegated = next(
        candidate
        for candidate in first.candidate_set.candidates
        if candidate.family == "pv_charge_only"
    )
    assert first.evaluation.status == "winner_selected"
    assert first.evaluation.evaluated_candidate_ids == tuple(
        candidate.candidate_id for candidate in first.candidate_set.candidates
    )
    assert first.evaluation.winning_candidate_id == delegated.candidate_id
    assert first.evaluation.winning_energy_path_id == delegated.energy_path_id
    assert first.evaluation.decisive_step == (
        "hard_constraint:storage_requirement_satisfied"
    )
    assert first.evaluation.reason == (
        "pv_charge_only satisfies the storage requirement using PV-only energy"
    )
    assert first.evaluation == second.evaluation


def test_uncommitted_active_window_does_not_outrank_cheaper_future_window() -> None:
    """Being executable now is not an Evaluation objective by itself."""

    source = _snapshot()
    current_end = BASE + timedelta(minutes=30)
    future_start = BASE + timedelta(minutes=30)
    future_end = BASE + timedelta(hours=1)
    priced = replace(
        source,
        price_points=(
            PriceForecastPoint(
                point_id="price-current",
                starts_at=BASE,
                ends_at=current_end,
                value_eur_per_kwh=0.40,
                confidence=1.0,
                evidence_id="price-current-evidence",
            ),
            PriceForecastPoint(
                point_id="price-future",
                starts_at=future_start,
                ends_at=future_end,
                value_eur_per_kwh=0.10,
                confidence=1.0,
                evidence_id="price-future-evidence",
            ),
        ),
    )
    baseline = CanonicalPipeline().run(planning_input=source)
    outcome = baseline.outcomes.outcomes[0]
    current = replace(
        outcome,
        outcome_id="outcome-current",
        candidate_id="candidate-current",
        charge_window_starts_at=BASE,
        charge_window_ends_at=current_end,
    )
    future = replace(
        outcome,
        outcome_id="outcome-future",
        candidate_id="candidate-future",
        charge_window_starts_at=future_start,
        charge_window_ends_at=future_end,
    )

    winner = DelegatedStorageEvaluationEngine().evaluate(
        snapshot=priced,
        candidate_set=baseline.candidate_set,
        actionable_outcomes=(current, future),
    ).winning_outcome

    assert winner == future


def test_feasible_challenger_replaces_infeasible_committed_window() -> None:
    source = _snapshot()
    run = CanonicalPipeline().run(planning_input=source)
    incumbent_candidate = next(
        item for item in run.candidate_set.candidates if item.family == "pv_charge_only"
    )
    incumbent_path = next(
        item
        for item in run.candidate_set.energy_paths
        if item.path_id == incumbent_candidate.energy_path_id
    )
    incumbent_outcome = run.outcomes.outcomes[0]
    segment = incumbent_path.segments[0]
    snapshot = replace(
        source,
        active_plan_commitments=(
            ActivePlanCommitment(
                segment.execution_scope_id,
                "plan-infeasible-late-window",
                1,
                segment.primitive.value,
                "pv_only",
                segment.starts_at,
                segment.ends_at,
                1200.0,
            ),
        ),
    )
    challenger_path = replace(
        incumbent_path,
        path_id=f"{incumbent_path.path_id}-challenger",
        segments=(
            replace(
                segment,
                segment_id=f"{segment.segment_id}-challenger",
                starts_at=segment.starts_at + timedelta(minutes=1),
            ),
        ),
        segment_ids=(f"{segment.segment_id}-challenger",),
    )
    challenger_candidate = replace(
        incumbent_candidate,
        candidate_id=f"{incumbent_candidate.candidate_id}-challenger",
        energy_path_id=challenger_path.path_id,
    )
    challenger_outcome = replace(
        incumbent_outcome,
        outcome_id=f"{incumbent_outcome.outcome_id}-challenger",
        candidate_id=challenger_candidate.candidate_id,
        energy_path_id=challenger_path.path_id,
        charge_window_starts_at=segment.starts_at + timedelta(minutes=1),
        requirement_satisfied=True,
    )
    infeasible_incumbent = replace(
        incumbent_outcome,
        storage_energy_at_requirement_wh=(
            incumbent_outcome.required_energy_wh - 1.0
        ),
        requirement_satisfied=False,
        recoverability=0.0,
        reserve_satisfied=False,
    )
    result = DelegatedStorageEvaluationEngine().evaluate(
        snapshot=snapshot,
        candidate_set=replace(
            run.candidate_set,
            candidates=(incumbent_candidate, challenger_candidate),
            energy_paths=(incumbent_path, challenger_path),
        ),
        actionable_outcomes=(
            infeasible_incumbent,
            challenger_outcome,
        ),
    )

    assert result.winning_outcome == challenger_outcome
    assert result.incumbent_retained is False
    assert result.decisive_step is None


def test_active_commitment_is_retained_with_stable_plan_identity() -> None:
    first = CanonicalPipeline().run(
        planning_input=_snapshot(),
        control_change_allowed=True,
    )
    active_plan = first.execution_plan_set.plans[0]
    captured_at = BASE + timedelta(minutes=15)
    source = _snapshot()
    snapshot = replace(
        source,
        captured_at=captured_at,
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            captured_at=captured_at,
        ),
        active_plan_commitments=(
            ActivePlanCommitment(
                execution_scope_id=active_plan.execution_scope_id,
                plan_id=active_plan.plan_id,
                plan_revision=1,
                primitive=active_plan.planned_primitive.value,
                source_policy="pv_only",
                starts_at=active_plan.valid_from,
                ends_at=active_plan.valid_until,
                target_energy_wh=1200.0,
            ),
        ),
    )

    continued = CanonicalPipeline().run(
        planning_input=snapshot,
        control_change_allowed=True,
    )

    assert continued.evaluation.decisive_step == (
        "stability:active_plan_commitment_retained"
    )
    assert continued.evaluation.reason == (
        "active plan commitment retained while storage acquisition continues"
    )
    assert continued.execution_plan_set.plans[0].plan_id == active_plan.plan_id


def test_infeasible_active_commitment_is_not_retained_by_stability() -> None:
    first = CanonicalPipeline().run(
        planning_input=_snapshot(),
        control_change_allowed=True,
    )
    active_plan = first.execution_plan_set.plans[0]
    captured_at = BASE + timedelta(minutes=15)
    source = _snapshot()
    assert source.pv_energy_timeline is not None
    depleted_timeline = replace(
        source.pv_energy_timeline,
        intervals=(
            replace(
                source.pv_energy_timeline.intervals[0],
                pv_energy_wh=100.0,
            ),
            source.pv_energy_timeline.intervals[1],
        ),
    )
    snapshot = replace(
        source,
        captured_at=captured_at,
        pv_energy_timeline=depleted_timeline,
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            captured_at=captured_at,
        ),
        active_plan_commitments=(
            ActivePlanCommitment(
                active_plan.execution_scope_id,
                active_plan.plan_id,
                1,
                active_plan.planned_primitive.value,
                "pv_only",
                active_plan.valid_from,
                active_plan.valid_until,
                1200.0,
            ),
        ),
    )

    continued = CanonicalPipeline().run(
        planning_input=snapshot,
        control_change_allowed=True,
    )

    assert continued.evaluation.decisive_step == (
        "objective:maximize_storage_progress_without_grid"
    )
    assert continued.execution_plan_set.plans[0].plan_id != active_plan.plan_id


def test_scheduled_commitment_uses_projected_household_energy_at_window_start() -> None:
    source = _snapshot()
    assert source.pv_energy_timeline is not None
    scheduled_start = BASE + timedelta(hours=1)
    snapshot = replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=(
                replace(
                    source.pv_energy_timeline.intervals[0],
                    pv_energy_wh=0.0,
                ),
                replace(
                    source.pv_energy_timeline.intervals[1],
                    pv_energy_wh=800.0,
                ),
            ),
        ),
        active_plan_commitments=(
            ActivePlanCommitment(
                "home-battery",
                "plan-future-household",
                1,
                "balance_charge_only",
                "pv_only",
                scheduled_start,
                HORIZON_END,
                1200.0,
            ),
        ),
    )

    run = CanonicalPipeline().run(
        planning_input=snapshot,
        control_change_allowed=True,
    )
    winner = next(
        item
        for item in run.outcomes.outcomes
        if item.candidate_id == run.evaluation.winning_candidate_id
    )

    assert winner.storage_energy_at_window_start_wh == pytest.approx(800.0)
    assert winner.projected_storage_use_before_window_wh == pytest.approx(200.0)
    assert winner.required_storage_addition_wh == pytest.approx(400.0)
    assert winner.pv_storage_contribution_wh == pytest.approx(400.0)
    assert winner.requirement_satisfied is False
    assert run.evaluation.decisive_step == (
        "objective:maximize_storage_progress_without_grid"
    )
    assert run.execution_plan_set.plans[0].plan_id != "plan-future-household"


def test_executable_window_uses_duration_weighted_quarter_prices() -> None:
    source = _snapshot()
    quarter = timedelta(minutes=15)
    prices = tuple(
        PriceForecastPoint(
            point_id=f"price-{index}",
            starts_at=BASE + quarter * index,
            ends_at=BASE + quarter * (index + 1),
            value_eur_per_kwh=value,
            confidence=1.0,
            evidence_id="price-evidence",
        )
        for index, value in enumerate((0.40, 0.30, 0.20, 0.10))
    )
    snapshot = replace(source, price_points=prices)

    assert _average_price_for_window(
        snapshot,
        BASE,
        BASE + timedelta(hours=1),
    ) == pytest.approx(0.25)
    assert _average_price_for_window(
        snapshot,
        BASE + timedelta(minutes=30),
        BASE + timedelta(hours=1),
    ) == pytest.approx(0.15)


def test_executable_window_requires_complete_price_coverage() -> None:
    source = _snapshot()
    snapshot = replace(
        source,
        price_points=(
            PriceForecastPoint(
                point_id="price-partial",
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=15),
                value_eur_per_kwh=0.10,
                confidence=1.0,
                evidence_id="price-evidence",
            ),
        ),
    )

    assert _average_price_for_window(
        snapshot,
        BASE,
        BASE + timedelta(minutes=30),
    ) == float("inf")


def test_equal_price_low_confidence_prefers_local_midday() -> None:
    source = _snapshot()
    local_timezone = ZoneInfo("Europe/Amsterdam")
    local_day = datetime(2026, 8, 22, tzinfo=local_timezone)
    earlier_start = local_day.replace(hour=12, minute=30)
    earlier_end = local_day.replace(hour=14, minute=30)
    later_start = local_day.replace(hour=14, minute=30)
    later_end = local_day.replace(hour=16, minute=30)
    profile = UserObjectiveProfile(
        profile_id="profile:test",
        version=1,
        cost_optimization_weight=80,
        self_consumption_weight=70,
        reserve_availability_weight=60,
        trading_enabled=False,
        adaptive_priority_enabled=True,
    )

    def snapshot_with_confidence(confidence: float) -> PlanningInputSnapshot:
        regime = derive_household_planning_regime(
            profile=profile,
            policy=AdaptiveHouseholdObjectivePolicy(
                recovery_confidence_threshold=0.60,
            ),
            forecast_confidence=confidence,
            cumulative_forecast_energy_wh=1000.0,
            cumulative_actual_energy_wh=1000.0,
            underperformance_duration_seconds=0,
            evidence_ids=("pv-confidence",),
        )
        return replace(
            source,
            household_planning_regime=regime,
            price_points=(
                PriceForecastPoint(
                    "price-equal",
                    earlier_start,
                    later_end,
                    0.20,
                    1.0,
                    "price-evidence",
                ),
            ),
            pv_energy_timeline=replace(
                source.pv_energy_timeline,
                intervals=(
                    replace(
                        source.pv_energy_timeline.intervals[0],
                        interval_id="pv-day",
                        starts_at=local_day.replace(hour=9, minute=30),
                        ends_at=local_day.replace(hour=15),
                        pv_energy_wh=200.0,
                    ),
                    replace(
                        source.pv_energy_timeline.intervals[1],
                        interval_id="pv-evening-tail",
                        starts_at=local_day.replace(hour=15),
                        ends_at=local_day.replace(hour=21),
                        pv_energy_wh=1000.0,
                    ),
                ),
            ),
        )

    baseline = CanonicalPipeline().run(planning_input=source)
    outcome = baseline.outcomes.outcomes[0]
    earlier = replace(
        outcome,
        outcome_id="outcome-earlier",
        candidate_id="candidate-earlier",
        charge_window_starts_at=earlier_start,
        charge_window_ends_at=earlier_end,
    )
    later = replace(
        outcome,
        outcome_id="outcome-later",
        candidate_id="candidate-later",
        charge_window_starts_at=later_start,
        charge_window_ends_at=later_end,
    )
    engine = DelegatedStorageEvaluationEngine()
    low_snapshot = snapshot_with_confidence(0.36)
    high_snapshot = snapshot_with_confidence(0.80)
    low_winner = engine.evaluate(
        snapshot=low_snapshot,
        candidate_set=baseline.candidate_set,
        actionable_outcomes=(later, earlier),
    ).winning_outcome
    high_winner = engine.evaluate(
        snapshot=high_snapshot,
        candidate_set=baseline.candidate_set,
        actionable_outcomes=(later, earlier),
    ).winning_outcome

    assert low_snapshot.household_planning_regime is not None
    assert low_snapshot.household_planning_regime.pv_timing_confident is False
    assert low_winner is not None
    assert low_winner.charge_window_starts_at == earlier_start
    assert high_snapshot.household_planning_regime is not None
    assert high_snapshot.household_planning_regime.pv_timing_confident is True
    assert high_winner is not None
    assert high_winner.charge_window_starts_at == later_start


def test_lower_forecast_basis_replaces_central_pv_energy_explicitly() -> None:
    source = _snapshot()
    ranged = replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=tuple(
                replace(
                    interval,
                    forecast_lower_energy_wh=interval.pv_energy_wh * 0.5,
                    forecast_central_energy_wh=interval.pv_energy_wh,
                    forecast_upper_energy_wh=interval.pv_energy_wh * 1.25,
                    forecast_range_status="available",
                    forecast_range_source_fields=(
                        "pv_estimate10",
                        "pv_estimate",
                        "pv_estimate90",
                    ),
                    forecast_range_method_version="solcast-range:test",
                )
                for interval in source.pv_energy_timeline.intervals
            ),
        ),
    )
    central_run = CanonicalPipeline().run(planning_input=source)
    central_balance = central_run.candidate_set.projected_balances[0]
    assumptions = derive_pv_forecast_basis_assumptions(ranged)
    lower = next(item for item in assumptions.assumptions if item.basis == "lower")

    projected = _balance_for_pv_forecast_basis(central_balance, lower)

    assert [item.expected_usable_pv_energy_wh for item in projected.intervals] == [
        400.0,
        0.0,
    ]


def test_winning_delegated_path_becomes_unchanged_observer_plan() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())
    winning_path = next(
        path
        for path in run.candidate_set.energy_paths
        if path.path_id == run.evaluation.winning_energy_path_id
    )

    assert run.execution_plan_set.winning_energy_path_id == winning_path.path_id
    assert len(run.execution_plan_set.plans) == 1
    plan = run.execution_plan_set.plans[0]
    assert plan.execution_scope_id == "home-battery"
    assert plan.observer_only is True
    assert plan.winning_candidate_id == run.evaluation.winning_candidate_id
    assert plan.winning_energy_path_id == winning_path.path_id
    assert len(plan.segments) == len(winning_path.segments)
    for plan_segment, path_segment in zip(
        plan.segments,
        winning_path.segments,
        strict=True,
    ):
        assert plan_segment.source_path_segment_id == path_segment.segment_id
        assert plan_segment.starts_at == path_segment.starts_at
        assert plan_segment.ends_at == path_segment.ends_at
        assert plan_segment.primitive == path_segment.primitive
        assert plan_segment.capability_id == path_segment.capability_id
        assert plan_segment.requested_power_w is None
        assert (
            plan_segment.charge_source_policy
            == path_segment.charge_source_policy
        )

    assert run.execution_record.status == "observer_only_plan_ready"
    assert run.primitive_boundary.request_id is None
    assert run.primitive_boundary.status == "not_emitted"
    assert run.adapter_boundary.translation_id is None
    assert run.adapter_boundary.status == "not_invoked"
    assert run.vendor_result.command_id is None
    assert run.vendor_result.status == "not_dispatched"


def test_projection_explains_winner_and_observer_only_plan() -> None:
    projection = project(CanonicalPipeline().run(planning_input=_snapshot()))
    evaluation_card = projection.cards[3]
    plan_card = projection.cards[4]

    assert evaluation_card.state == "winner_selected"
    assert evaluation_card.attributes["decisive_step"] == (
        "hard_constraint:storage_requirement_satisfied"
    )
    assert evaluation_card.attributes["winning_family"] == "pv_charge_only"
    assert evaluation_card.attributes["reason"] == (
        "pv_charge_only satisfies the storage requirement using PV-only energy"
    )
    assert plan_card.state == "observer_only"
    assert plan_card.attributes["plan_count"] == 1
    planned = plan_card.attributes["plans"][0]
    assert planned["execution_scope_id"] == "home-battery"
    assert planned["observer_only"] is True
    assert planned["segment_count"] == 1
    assert planned["segments"][0]["primitive"] == "balance_charge_only"
    assert planned["segments"][0]["charge_source_policy"] == "pv_only"
    assert planned["segments"][0]["requested_power_w"] is None


def test_zero_confidence_outcome_cannot_be_released_as_a_winner() -> None:
    source = _snapshot()
    assert source.household_load_forecast is not None
    snapshot = replace(
        source,
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=tuple(
                replace(interval, confidence=0.0)
                for interval in source.household_load_forecast.intervals
            ),
            fallback_active=True,
            fallback_reason="configured_power",
        ),
    )

    run = CanonicalPipeline().run(
        planning_input=snapshot,
        control_change_allowed=True,
    )

    outcome = run.outcomes.outcomes[0]
    assert outcome.requirement_satisfied is True
    assert outcome.pv_storage_contribution_wh > 0.0
    assert outcome.confidence == 0.0
    assert run.evaluation.status == "fallback_active"
    assert run.evaluation.winning_candidate_id != outcome.candidate_id
    assert run.evaluation.decisive_step == "fallback:no_actionable_candidate"
    assert run.execution_record.status != "live_plan_ready"


def test_partial_pv_progress_is_released_as_a_winner() -> None:
    source = _snapshot()
    first_pv = source.pv_energy_timeline.intervals[0]
    snapshot = replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=(
                replace(first_pv, pv_energy_wh=300.0),
                source.pv_energy_timeline.intervals[1],
            ),
        ),
    )

    run = CanonicalPipeline().run(planning_input=snapshot)

    outcome = run.outcomes.outcomes[0]
    assert outcome.requirement_satisfied is False
    assert outcome.pv_storage_contribution_wh == pytest.approx(100.0)
    assert outcome.confidence > 0.0
    assert run.evaluation.status == "winner_selected"
    assert run.evaluation.winning_candidate_id == outcome.candidate_id
    assert run.evaluation.reason == (
        "pv_charge_only maximizes storage progress using PV-only energy"
    )
    assert run.evaluation.decisive_step == (
        "objective:maximize_storage_progress_without_grid"
    )
    assert run.execution_record.status == "observer_only_plan_ready"
    explanation = _build_plan_explanation(run)
    partial = next(
        plan for plan in explanation["plans"] if plan["family"] == "pv_charge_only"
    )
    assert partial["selected"] is True


def test_evaluation_prefers_satisfied_active_path_over_earlier_partial_candidate() -> None:
    source = _snapshot()
    half_hour = timedelta(minutes=30)
    first_end = BASE + half_hour
    pv_intervals = (
        replace(
            source.pv_energy_timeline.intervals[0],
            interval_id="pv-first-half",
            ends_at=first_end,
            pv_energy_wh=250.0,
        ),
        replace(
            source.pv_energy_timeline.intervals[0],
            interval_id="pv-second-half",
            starts_at=first_end,
            pv_energy_wh=250.0,
        ),
        source.pv_energy_timeline.intervals[1],
    )
    load_intervals = (
        replace(
            source.household_load_forecast.intervals[0],
            interval_id="load-first-half",
            ends_at=first_end,
            expected_energy_wh=100.0,
        ),
        replace(
            source.household_load_forecast.intervals[0],
            interval_id="load-second-half",
            starts_at=first_end,
            expected_energy_wh=100.0,
        ),
        source.household_load_forecast.intervals[1],
    )
    snapshot = replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=pv_intervals,
        ),
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=load_intervals,
        ),
    )

    run = CanonicalPipeline().run(planning_input=snapshot)
    winner = next(
        outcome
        for outcome in run.outcomes.outcomes
        if outcome.candidate_id == run.evaluation.winning_candidate_id
    )

    assert winner.requirement_satisfied is True
    assert winner.charge_window_starts_at == BASE
    assert winner.storage_energy_at_requirement_wh == pytest.approx(1200.0)
    assert run.evaluation.decisive_step == (
        "hard_constraint:storage_requirement_satisfied"
    )
