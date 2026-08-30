from dataclasses import replace
from datetime import UTC, datetime, timedelta

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import (
    CurrentStorageState,
    PlanningInputSnapshot,
    PriceForecastPoint,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.live_runtime import _planning_input_signature, _should_run_cycle
from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    CommittedPlanSegment,
)
from picot.v2.planning_input import CanonicalInputFact, PlanningInputBundle

BASE = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _bundle(
    *,
    captured_at: datetime,
    price: float = 0.20,
    grid_power: float = 500.0,
) -> PlanningInputBundle:
    point = PriceForecastPoint(
        point_id="price-1",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=1),
        value_eur_per_kwh=price,
        confidence=1.0,
        evidence_id="evidence-price",
    )
    snapshot = PlanningInputSnapshot(
        run_id=f"run-{captured_at.isoformat()}",
        snapshot_id=f"snapshot-{captured_at.isoformat()}",
        captured_at=captured_at,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:no-objectives:v1",
        horizon_end=BASE + timedelta(hours=1),
        price_points=(point,),
    )
    fact = CanonicalInputFact(
        fact_id=f"fact-{captured_at.isoformat()}",
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        category="p1",
        semantic_role="grid_power",
        value=grid_power,
        unit="W",
        observed_at=BASE,
        availability="available",
        evidence_id="evidence-grid",
        mapping_version="mapping-grid",
    )
    return PlanningInputBundle(
        snapshot=snapshot,
        evidence=(),
        facts=(fact,),
        assembly_started_at=captured_at,
        assembly_finished_at=captured_at,
    )


def _with_pv_energy(
    bundle: PlanningInputBundle,
    *,
    pv_energy_wh: float,
) -> PlanningInputBundle:
    lineage = bundle.snapshot.snapshot_id
    starts_at = BASE + timedelta(hours=2)
    interval = PVEnergyTimelineInterval(
        interval_id=f"pv-energy-interval-{lineage}",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        pv_energy_wh=pv_energy_wh,
        evidence_type="FORECAST",
        confidence=0.8587,
        actual_evidence_ids=(),
        forecast_evidence_ids=(f"evidence-solcast-{lineage}",),
        conversion_method_version=(
            "solcast-detailed-forecast-average-kw-30m:v1"
        ),
    )
    timeline = PVEnergyTimeline(
        timeline_id=f"pv-energy-timeline-{lineage}",
        run_id=bundle.snapshot.run_id,
        snapshot_id=bundle.snapshot.snapshot_id,
        intervals=(interval,),
    )
    return replace(
        bundle,
        snapshot=replace(
            bundle.snapshot,
            pv_energy_timeline=timeline,
        ),
    )


def _with_active_commitment(
    bundle: PlanningInputBundle,
    *,
    current_energy_wh: float,
) -> PlanningInputBundle:
    commitment = ActivePlanCommitment(
        execution_scope_id="home-battery",
        plan_id="plan-stable",
        plan_revision=1,
        primitive="balance_bidirectional",
        source_policy="pv_only",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=1),
        target_energy_wh=1000.0,
    )
    storage = CurrentStorageState(
        storage_state_id="storage-home",
        execution_scope_id="home-battery",
        capability_id="storage-capability",
        current_soc=current_energy_wh / 1000.0,
        usable_capacity_wh=1000.0,
        measured_at=BASE,
        confidence=1.0,
        evidence_ids=("storage-evidence",),
    )
    return replace(
        bundle,
        snapshot=replace(
            bundle.snapshot,
            current_storage_states=(storage,),
            active_plan_commitments=(commitment,),
        ),
    )


def test_identical_source_content_has_same_signature_across_fresh_snapshots() -> None:
    first = _bundle(captured_at=BASE)
    second = _bundle(captured_at=BASE + timedelta(minutes=1))

    assert first.snapshot.run_id != second.snapshot.run_id
    assert _planning_input_signature(first) == _planning_input_signature(second)


def test_identical_pv_timeline_content_has_same_signature_across_fresh_snapshots(
) -> None:
    first = _with_pv_energy(
        _bundle(captured_at=BASE),
        pv_energy_wh=1382.3,
    )
    second = _with_pv_energy(
        _bundle(captured_at=BASE + timedelta(minutes=1)),
        pv_energy_wh=1382.3,
    )

    assert first.snapshot.pv_energy_timeline is not None
    assert second.snapshot.pv_energy_timeline is not None
    assert (
        first.snapshot.pv_energy_timeline.timeline_id
        != second.snapshot.pv_energy_timeline.timeline_id
    )
    assert _planning_input_signature(first) == _planning_input_signature(second)


def test_changed_pv_energy_timeline_changes_signature() -> None:
    first = _with_pv_energy(
        _bundle(captured_at=BASE),
        pv_energy_wh=1382.3,
    )
    second = _with_pv_energy(
        _bundle(captured_at=BASE + timedelta(minutes=1)),
        pv_energy_wh=1393.75,
    )

    assert _planning_input_signature(first) != _planning_input_signature(second)


def test_changed_price_forecast_changes_signature() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    second = _bundle(captured_at=BASE + timedelta(minutes=1), price=0.10)

    assert _planning_input_signature(first) != _planning_input_signature(second)


def test_changed_canonical_fact_changes_signature() -> None:
    first = _bundle(captured_at=BASE, grid_power=500.0)
    second = _bundle(captured_at=BASE + timedelta(minutes=1), grid_power=700.0)

    assert _planning_input_signature(first) != _planning_input_signature(second)


def test_active_commitment_treats_ordinary_soc_and_power_as_progress() -> None:
    first = _with_active_commitment(
        _bundle(captured_at=BASE, grid_power=500.0),
        current_energy_wh=500.0,
    )
    second = _with_active_commitment(
        _bundle(
            captured_at=BASE + timedelta(minutes=1),
            grid_power=900.0,
        ),
        current_energy_wh=750.0,
    )

    assert _planning_input_signature(first) == _planning_input_signature(second)


def test_active_commitment_target_completion_is_material() -> None:
    first = _with_active_commitment(
        _bundle(captured_at=BASE),
        current_energy_wh=999.0,
    )
    completed = _with_active_commitment(
        _bundle(captured_at=BASE + timedelta(minutes=1)),
        current_energy_wh=1000.0,
    )

    assert _planning_input_signature(first) != _planning_input_signature(completed)


def test_scheduled_commitment_start_is_a_material_execution_boundary() -> None:
    scheduled_start = BASE + timedelta(minutes=30)
    first = _with_active_commitment(
        _bundle(captured_at=BASE),
        current_energy_wh=500.0,
    )
    at_start = _with_active_commitment(
        _bundle(captured_at=scheduled_start),
        current_energy_wh=500.0,
    )
    first_commitment = replace(
        first.snapshot.active_plan_commitments[0],
        starts_at=scheduled_start,
        ends_at=scheduled_start + timedelta(hours=1),
    )
    second_commitment = replace(
        at_start.snapshot.active_plan_commitments[0],
        starts_at=scheduled_start,
        ends_at=scheduled_start + timedelta(hours=1),
    )
    first = replace(
        first,
        snapshot=replace(
            first.snapshot,
            active_plan_commitments=(first_commitment,),
        ),
    )
    at_start = replace(
        at_start,
        snapshot=replace(
            at_start.snapshot,
            active_plan_commitments=(second_commitment,),
        ),
    )

    assert _planning_input_signature(first) != _planning_input_signature(at_start)


def test_active_commitment_segment_change_is_a_material_execution_boundary() -> None:
    boundary = BASE + timedelta(minutes=30)
    before = _with_active_commitment(
        _bundle(captured_at=boundary - timedelta(seconds=1)),
        current_energy_wh=500.0,
    )
    after = _with_active_commitment(
        _bundle(captured_at=boundary),
        current_energy_wh=500.0,
    )
    segments = (
        CommittedPlanSegment(
            starts_at=BASE,
            ends_at=boundary,
            primitive="discharge_at_power",
            source_policy=None,
        ),
        CommittedPlanSegment(
            starts_at=boundary,
            ends_at=BASE + timedelta(hours=1),
            primitive="balance_discharge_only",
            source_policy=None,
        ),
    )
    before_commitment = replace(
        before.snapshot.active_plan_commitments[0],
        primitive="discharge_at_power",
        segments=segments,
    )
    after_commitment = replace(
        after.snapshot.active_plan_commitments[0],
        primitive="discharge_at_power",
        segments=segments,
    )
    before = replace(
        before,
        snapshot=replace(
            before.snapshot,
            active_plan_commitments=(before_commitment,),
        ),
    )
    after = replace(
        after,
        snapshot=replace(
            after.snapshot,
            active_plan_commitments=(after_commitment,),
        ),
    )
    later = replace(
        after,
        snapshot=replace(
            after.snapshot,
            run_id="run-after-boundary",
            snapshot_id="snapshot-after-boundary",
            captured_at=boundary + timedelta(minutes=1),
        ),
    )

    assert _planning_input_signature(before) != _planning_input_signature(after)
    assert _should_run_cycle(_planning_input_signature(before), after)
    assert _planning_input_signature(after) == _planning_input_signature(later)


def test_incident_replay_soc_progress_and_power_variation_keep_one_plan() -> None:
    # Regression for the 2026-08-21 sequence that previously alternated NOM
    # and smart discharge while SOC progressed normally from 88% to 92%.
    samples = (
        (0, 88.0, -615.539),
        (12, 90.0, -45.421),
        (16, 90.0, -687.607),
        (22, 90.0, -48.264),
        (54, 92.0, -41.501),
        (58, 92.0, -49.526),
    )
    signatures = {
        _planning_input_signature(
            _with_active_commitment(
                _bundle(
                    captured_at=BASE + timedelta(minutes=minute),
                    grid_power=grid_power,
                ),
                current_energy_wh=soc_percent * 10.0,
            )
        )
        for minute, soc_percent, grid_power in samples
    }

    assert len(signatures) == 1


def test_first_cycle_always_runs() -> None:
    bundle = _bundle(captured_at=BASE)

    assert _should_run_cycle(None, bundle)


def test_identical_content_skips_new_pipeline_run() -> None:
    first = _bundle(captured_at=BASE)
    second = _bundle(captured_at=BASE + timedelta(minutes=1))
    previous_signature = _planning_input_signature(first)

    assert not _should_run_cycle(previous_signature, second)


def test_changed_content_requests_new_pipeline_run() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    second = _bundle(captured_at=BASE + timedelta(minutes=1), price=0.10)
    previous_signature = _planning_input_signature(first)

    assert _should_run_cycle(previous_signature, second)
