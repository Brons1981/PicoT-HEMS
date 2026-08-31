from dataclasses import replace
from datetime import UTC, datetime, timedelta

from picot.domain.runtime import RuntimeObservationKind
from picot.runtime.runtime_monitor import RuntimeMonitorSession
from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import CurrentStorageState, PlanningInputSnapshot
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.live_runtime import _planning_input_signature, _poll_live_cycle
from picot.v2.material_replanning import MaterialReplanningObservationProducer
from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    CommittedHouseholdLoadInterval,
    CommittedStorageEnergyCheckpoint,
)
from picot.v2.planning_input import HouseholdLoadObservation, PlanningInputBundle

BASE = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
CAPACITY_WH = 8160.0


def _commitment() -> ActivePlanCommitment:
    return ActivePlanCommitment(
        execution_scope_id="home-battery",
        plan_id="plan-materiality",
        plan_revision=1,
        primitive="balance_discharge_only",
        source_policy="not_applicable",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=4),
        target_energy_wh=CAPACITY_WH,
        selected_at=BASE,
        household_load_intervals=(
            CommittedHouseholdLoadInterval(
                interval_id="load-1",
                starts_at=BASE,
                ends_at=BASE + timedelta(minutes=15),
                expected_energy_wh=50.0,
                confidence=1.0,
                source_reference="history:load-1",
                method_version="load-forecast:v1",
            ),
            CommittedHouseholdLoadInterval(
                interval_id="load-2",
                starts_at=BASE + timedelta(minutes=15),
                ends_at=BASE + timedelta(minutes=30),
                expected_energy_wh=50.0,
                confidence=1.0,
                source_reference="history:load-2",
                method_version="load-forecast:v1",
            ),
        ),
        storage_energy_checkpoints=(
            CommittedStorageEnergyCheckpoint(
                at=BASE + timedelta(minutes=15),
                lower_energy_wh=3900.0,
                central_energy_wh=4000.0,
                upper_energy_wh=4100.0,
            ),
            CommittedStorageEnergyCheckpoint(
                at=BASE + timedelta(minutes=30),
                lower_energy_wh=3800.0,
                central_energy_wh=3900.0,
                upper_energy_wh=4000.0,
            ),
        ),
    )


def _bundle(*, energy_wh: float) -> PlanningInputBundle:
    captured_at = BASE + timedelta(minutes=30, seconds=1)
    storage = CurrentStorageState(
        storage_state_id="storage-home",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home-battery",
        current_soc=energy_wh / CAPACITY_WH,
        usable_capacity_wh=CAPACITY_WH,
        measured_at=captured_at,
        confidence=1.0,
        evidence_ids=("evidence-storage",),
    )
    snapshot = PlanningInputSnapshot(
        run_id="run-materiality",
        snapshot_id="snapshot-materiality",
        captured_at=captured_at,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:no-objectives:v1",
        horizon_end=BASE + timedelta(hours=4),
        current_storage_states=(storage,),
        active_plan_commitments=(_commitment(),),
    )
    return PlanningInputBundle(
        snapshot=snapshot,
        evidence=(),
        facts=(),
        assembly_started_at=captured_at,
        assembly_finished_at=captured_at,
    )


def _append_half_hour(
    store: HouseholdLoadHistoryStore,
    *,
    power_w: float,
) -> None:
    for minute in (0, 5, 10, 14, 15, 20, 25, 29):
        store.append(
            HouseholdLoadObservation(
                power_w=power_w,
                sampled_at=BASE + timedelta(minutes=minute),
                evidence_ids=(f"household-{minute}",),
                method_version="complete-power-balance:v1",
            )
        )


def test_expected_soc_progress_inside_committed_corridor_is_non_material(
    tmp_path,
) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    _append_half_hour(history, power_w=200.0)
    producer = MaterialReplanningObservationProducer(history=history)

    observations = producer.observe(_bundle(energy_wh=3900.0))

    assert observations == ()


def test_four_percent_soc_difference_outside_corridor_is_non_material(
    tmp_path,
) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    _append_half_hour(history, power_w=200.0)
    producer = MaterialReplanningObservationProducer(history=history)

    observations = producer.observe(
        _bundle(energy_wh=3800.0 - CAPACITY_WH * 0.04)
    )

    assert observations == ()


def test_soc_outside_committed_corridor_by_five_percent_is_material(
    tmp_path,
) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    _append_half_hour(history, power_w=200.0)
    producer = MaterialReplanningObservationProducer(history=history)

    observations = producer.observe(
        _bundle(energy_wh=3800.0 - CAPACITY_WH * 0.05)
    )

    assert len(observations) == 1
    assert observations[0].kind is RuntimeObservationKind.STORAGE_STATE_CHANGED
    assert observations[0].source_reference == "committed-storage-trajectory"
    assert observations[0].material_transition is True


def test_household_variation_below_combined_threshold_is_non_material(
    tmp_path,
) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    _append_half_hour(history, power_w=800.0)
    producer = MaterialReplanningObservationProducer(history=history)

    observations = producer.observe(_bundle(energy_wh=3900.0))

    assert observations == ()


def test_cumulative_household_energy_deviation_is_material(tmp_path) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    _append_half_hour(history, power_w=1200.0)
    producer = MaterialReplanningObservationProducer(history=history)

    observations = producer.observe(_bundle(energy_wh=3900.0))

    assert len(observations) == 1
    assert observations[0].kind is RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED
    assert observations[0].source_reference == "committed-household-load"
    assert observations[0].material_transition is True


def test_incomplete_household_history_does_not_invent_materiality(tmp_path) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    history.append(
        HouseholdLoadObservation(
            power_w=3000.0,
            sampled_at=BASE + timedelta(minutes=10),
            evidence_ids=("household-single",),
            method_version="complete-power-balance:v1",
        )
    )
    producer = MaterialReplanningObservationProducer(history=history)

    observations = producer.observe(_bundle(energy_wh=3900.0))

    assert observations == ()


def test_same_material_bucket_is_emitted_once_per_plan_revision(tmp_path) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    _append_half_hour(history, power_w=1200.0)
    producer = MaterialReplanningObservationProducer(history=history)
    bundle = _bundle(energy_wh=3300.0)

    first = producer.observe(bundle)
    repeated = producer.observe(replace(bundle))

    assert {item.source_reference for item in first} == {
        "committed-household-load",
        "committed-storage-trajectory",
    }
    assert repeated == ()


def test_smaller_material_bucket_after_larger_one_is_not_reemitted(tmp_path) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    _append_half_hour(history, power_w=200.0)
    producer = MaterialReplanningObservationProducer(history=history)

    larger = producer.observe(_bundle(energy_wh=2900.0))
    smaller = producer.observe(_bundle(energy_wh=3300.0))

    assert len(larger) == 1
    assert larger[0].observation_id.endswith("bucket-2")
    assert smaller == ()


def test_material_producer_requests_second_atomic_snapshot_and_run(tmp_path) -> None:
    history = HouseholdLoadHistoryStore(tmp_path / "household.jsonl")
    _append_half_hour(history, power_w=1200.0)
    producer = MaterialReplanningObservationProducer(history=history)
    observed = _bundle(energy_wh=3900.0)
    fresh_at = observed.snapshot.captured_at + timedelta(seconds=1)
    fresh = replace(
        observed,
        snapshot=replace(
            observed.snapshot,
            run_id="run-materiality-fresh",
            snapshot_id="snapshot-materiality-fresh",
            captured_at=fresh_at,
            current_storage_states=(
                replace(
                    observed.snapshot.current_storage_states[0],
                    measured_at=fresh_at,
                ),
            ),
        ),
        assembly_started_at=fresh_at,
        assembly_finished_at=fresh_at,
    )
    loaded = [observed, fresh]
    executed: list[PlanningInputBundle] = []

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(observed),
        load_bundle=lambda: loaded.pop(0),
        execute=lambda bundle: executed.append(bundle),
        runtime_monitor=RuntimeMonitorSession(),
        runtime_observations=producer.observe,
        runtime_now=lambda: fresh_at,
    )

    assert loaded == []
    assert executed == [fresh]
    assert result == _planning_input_signature(fresh)
