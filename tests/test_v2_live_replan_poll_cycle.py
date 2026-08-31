from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import picot.v2.live_runtime as live_runtime
from picot.domain.runtime import RuntimeObservation, RuntimeObservationKind
from picot.runtime.runtime_monitor import RuntimeMonitorSession
from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.live_runtime import (
    PlanningResetBarrier,
    _observer_input_signature,
    _planning_input_signature,
    _poll_live_cycle,
)
from picot.v2.plan_commitment_store import ActivePlanCommitment
from picot.v2.planning_input import (
    CanonicalInputFact,
    HouseholdLoadObservation,
    PlanningInputBundle,
)
from picot.v2.zendure_mode_capabilities import (
    derive_zendure_mode_capability_evidence,
)

BASE = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _bundle(
    *,
    captured_at: datetime,
    price: float,
    storage_mode: str | None = None,
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
        storage_mode_capability_evidence=(
            derive_zendure_mode_capability_evidence(
                {
                    "state": storage_mode,
                    "attributes": {
                        "options": ["Standby", "Nul op de meter"]
                    },
                },
                captured_at=captured_at,
                source_entity_id="input_select.zendure_mode",
                capability_id="storage-capability-home-battery",
                execution_scope_id="home-battery",
            )
            if storage_mode is not None
            else None
        ),
    )
    fact = CanonicalInputFact(
        fact_id=f"fact-{captured_at.isoformat()}",
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        category="p1",
        semantic_role="grid_power",
        value=500.0,
        unit="W",
        observed_at=BASE,
        availability="available",
        evidence_id="evidence-grid",
        mapping_version="mapping-grid",
    )
    observation = HouseholdLoadObservation(
        power_w=500.0,
        sampled_at=captured_at,
        evidence_ids=(
            "evidence-grid",
            "evidence-pv",
            "evidence-storage",
        ),
        method_version="complete-power-balance:v1",
    )
    return PlanningInputBundle(
        snapshot=snapshot,
        evidence=(),
        facts=(fact,),
        assembly_started_at=captured_at,
        assembly_finished_at=captured_at,
        household_load_observation=observation,
    )


def _with_active_commitment(
    bundle: PlanningInputBundle,
) -> PlanningInputBundle:
    commitment = ActivePlanCommitment(
        execution_scope_id="home-battery",
        plan_id="plan-tomorrow",
        plan_revision=1,
        primitive="balance_bidirectional",
        source_policy="pv_only",
        starts_at=BASE + timedelta(hours=12),
        ends_at=BASE + timedelta(hours=15),
        target_energy_wh=8160.0,
    )
    return replace(
        bundle,
        snapshot=replace(
            bundle.snapshot,
            active_plan_commitments=(commitment,),
        ),
    )


def test_poll_cycle_always_loads_fresh_input_but_skips_identical_execution() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    second = _bundle(captured_at=BASE + timedelta(minutes=1), price=0.20)
    loaded = [second]
    calls: list[str] = []
    refreshed: list[str] = []

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: loaded.pop(0),
        execute=lambda bundle: calls.append(bundle.snapshot.run_id),
        refresh_unchanged=lambda bundle: refreshed.append(
            bundle.snapshot.run_id
        ),
    )

    assert loaded == []
    assert calls == []
    assert refreshed == [second.snapshot.run_id]
    assert result == _planning_input_signature(first)


def test_poll_cycle_executes_when_fresh_input_changed() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    changed = _bundle(captured_at=BASE + timedelta(minutes=1), price=0.10)
    calls: list[str] = []

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: changed,
        execute=lambda bundle: calls.append(bundle.snapshot.run_id),
    )

    assert calls == [changed.snapshot.run_id]
    assert result == _planning_input_signature(changed)


def test_poll_cycle_advances_clock_boundary_before_changed_execution() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    changed = _bundle(
        captured_at=BASE + timedelta(minutes=15),
        price=0.10,
    )
    events: list[tuple[str, str]] = []

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: changed,
        execute=lambda bundle: events.append(
            ("execute", bundle.snapshot.run_id)
        ),
        advance_clock_boundaries=lambda bundle: events.append(
            ("advance", bundle.snapshot.run_id)
        ),
    )

    assert events == [
        ("advance", changed.snapshot.run_id),
        ("execute", changed.snapshot.run_id),
    ]
    assert result == _planning_input_signature(changed)


def test_poll_cycle_advances_clock_boundary_when_execution_is_unchanged() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    unchanged = _bundle(
        captured_at=BASE + timedelta(minutes=15),
        price=0.20,
    )
    advanced: list[str] = []
    refreshed: list[str] = []

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: unchanged,
        execute=lambda bundle: None,
        advance_clock_boundaries=lambda bundle: advanced.append(
            bundle.snapshot.run_id
        ),
        refresh_unchanged=lambda bundle: refreshed.append(
            bundle.snapshot.run_id
        ),
    )

    assert advanced == [unchanged.snapshot.run_id]
    assert refreshed == [unchanged.snapshot.run_id]
    assert result == _planning_input_signature(first)


def test_observer_detects_fresh_input_while_commitment_stays_stable() -> None:
    first = _with_active_commitment(_bundle(captured_at=BASE, price=0.20))
    changed = _with_active_commitment(
        _bundle(captured_at=BASE + timedelta(minutes=1), price=0.10)
    )
    observed: list[str] = []
    executed: list[str] = []

    assert _planning_input_signature(first) == _planning_input_signature(changed)
    assert _observer_input_signature(first) != _observer_input_signature(changed)

    _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: changed,
        execute=lambda bundle: executed.append(bundle.snapshot.run_id),
        observe=lambda bundle: observed.append(bundle.snapshot.run_id),
    )

    assert observed == [changed.snapshot.run_id]
    assert executed == []


def test_observer_ignores_live_power_noise_but_detects_soc_change() -> None:
    first = _with_active_commitment(_bundle(captured_at=BASE, price=0.20))
    power_changed = replace(
        first,
        facts=(replace(first.facts[0], value=750.0),),
    )
    soc_first = replace(
        first,
        facts=(
            replace(
                first.facts[0],
                category="zendure",
                semantic_role="storage_soc",
                value=98.0,
                unit="%",
            ),
        ),
    )
    soc_changed = replace(
        soc_first,
        facts=(replace(soc_first.facts[0], value=97.0),),
    )

    assert _observer_input_signature(first) == _observer_input_signature(
        power_changed
    )
    assert _observer_input_signature(soc_first) != _observer_input_signature(
        soc_changed
    )


def test_planning_reset_waits_for_older_cycle_before_clearing_state() -> None:
    barrier = PlanningResetBarrier()
    cycle_started = Event()
    release_cycle = Event()
    reset_finished = Event()
    events: list[str] = []

    def cycle() -> None:
        events.append("cycle_started")
        cycle_started.set()
        assert release_cycle.wait(timeout=2)
        events.append("cycle_finished")

    def reset() -> None:
        generation, _ = barrier.reset(
            lambda: events.append("state_cleared")
        )
        assert generation == 1
        reset_finished.set()

    cycle_thread = Thread(target=lambda: barrier.run_cycle(cycle))
    reset_thread = Thread(target=reset)
    cycle_thread.start()
    assert cycle_started.wait(timeout=2)
    reset_thread.start()

    assert not reset_finished.wait(timeout=0.05)
    release_cycle.set()
    cycle_thread.join(timeout=2)
    reset_thread.join(timeout=2)

    assert events == ["cycle_started", "cycle_finished", "state_cleared"]
    assert barrier.generation == 1


def test_manual_override_reset_requests_an_immediate_fresh_planning_cycle() -> None:
    replan_requested = Event()

    class Runtime:
        def reset_current_manual_override(self, *, reset_at, reset_id):
            return type(
                "Provenance",
                (),
                {
                    "status": "observed",
                    "reset_id": reset_id,
                    "manual_override_active": False,
                },
            )()

    result = live_runtime._reset_storage_mode_override_and_request_replan(
        runtime=Runtime(),
        replan_requested=replan_requested,
        reset_id="reset-override",
        reset_at=BASE,
    )

    assert result == {
        "status": "observed",
        "reset_id": "reset-override",
        "manual_override_active": False,
        "replan_requested": True,
    }
    assert replan_requested.is_set()


def test_poll_cycle_executes_when_only_storage_mode_changed() -> None:
    first = _bundle(
        captured_at=BASE,
        price=0.20,
        storage_mode="Standby",
    )
    changed = _bundle(
        captured_at=BASE + timedelta(minutes=1),
        price=0.20,
        storage_mode="Nul op de meter",
    )

    assert _planning_input_signature(first) != _planning_input_signature(changed)


def test_live_history_uses_persistent_addon_data_path() -> None:
    assert live_runtime.HOUSEHOLD_LOAD_HISTORY_PATH == Path(
        "/data/picot_v2_household_load_history.jsonl"
    )


def test_poll_cycle_persists_observation_when_execution_is_skipped() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    fresh = _bundle(
        captured_at=BASE + timedelta(minutes=1),
        price=0.20,
    )
    persisted: list[HouseholdLoadObservation] = []
    executed: list[str] = []

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: fresh,
        execute=lambda bundle: executed.append(
            bundle.snapshot.run_id
        ),
        persist_observation=persisted.append,
    )

    assert persisted == [fresh.household_load_observation]
    assert executed == []
    assert result == _planning_input_signature(first)


def test_history_write_failure_does_not_stop_pipeline_cycle() -> None:
    fresh = _bundle(captured_at=BASE, price=0.10)
    executed: list[str] = []

    def fail_persistence(
        observation: HouseholdLoadObservation,
    ) -> None:
        del observation
        raise OSError("history unavailable")

    result = _poll_live_cycle(
        previous_signature=None,
        load_bundle=lambda: fresh,
        execute=lambda bundle: executed.append(
            bundle.snapshot.run_id
        ),
        persist_observation=fail_persistence,
    )

    assert executed == [fresh.snapshot.run_id]
    assert result == _planning_input_signature(fresh)


def test_poll_cycle_prepares_actual_pv_before_signature_and_execution(
) -> None:
    loaded = _bundle(captured_at=BASE, price=0.20)
    enriched = _bundle(
        captured_at=BASE + timedelta(minutes=1),
        price=0.10,
    )
    diagnostics = object()
    events: list[tuple[str, object]] = []

    def load_bundle() -> PlanningInputBundle:
        events.append(("loaded", loaded))
        return loaded

    def prepare_bundle(
        bundle: PlanningInputBundle,
    ) -> tuple[PlanningInputBundle, object]:
        assert bundle is loaded
        events.append(("prepared", enriched))
        return enriched, diagnostics

    def execute(
        bundle: PlanningInputBundle,
        actual_pv_diagnostics: object,
    ) -> None:
        events.append(("executed", bundle))
        assert bundle is enriched
        assert actual_pv_diagnostics is diagnostics

    result = _poll_live_cycle(
        previous_signature=None,
        load_bundle=load_bundle,
        prepare_bundle=prepare_bundle,
        execute=execute,
    )

    assert events == [
        ("loaded", loaded),
        ("prepared", enriched),
        ("executed", enriched),
    ]
    assert result == _planning_input_signature(enriched)


def test_non_material_runtime_observation_keeps_active_commitment() -> None:
    first = _with_active_commitment(_bundle(captured_at=BASE, price=0.20))
    fresh = _with_active_commitment(
        _bundle(captured_at=BASE + timedelta(minutes=1), price=0.10)
    )
    executed: list[str] = []

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: fresh,
        execute=lambda bundle: executed.append(bundle.snapshot.run_id),
        runtime_monitor=RuntimeMonitorSession(),
        runtime_observations=lambda bundle: (
            RuntimeObservation(
                observation_id="household-load:within-tolerance",
                kind=RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
                observed_at=bundle.snapshot.captured_at,
                source_reference="household-load-deviation",
                old_value="500Wh",
                new_value="540Wh",
                unit="Wh",
                material_transition=False,
            ),
        ),
    )

    assert executed == []
    assert result == _planning_input_signature(first)


def test_material_runtime_observation_forces_fresh_committed_run() -> None:
    first = _with_active_commitment(_bundle(captured_at=BASE, price=0.20))
    observed = _with_active_commitment(
        _bundle(captured_at=BASE + timedelta(minutes=1), price=0.10)
    )
    fresh = _with_active_commitment(
        _bundle(captured_at=BASE + timedelta(minutes=1, seconds=1), price=0.11)
    )
    loaded = [observed, fresh]
    executed: list[PlanningInputBundle] = []
    monitor = RuntimeMonitorSession()

    assert _planning_input_signature(first) == _planning_input_signature(observed)
    assert _planning_input_signature(first) == _planning_input_signature(fresh)

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: loaded.pop(0),
        execute=lambda bundle: executed.append(bundle),
        runtime_monitor=monitor,
        runtime_observations=lambda bundle: (
            RuntimeObservation(
                observation_id="household-load:material-excess:1",
                kind=RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
                observed_at=bundle.snapshot.captured_at,
                source_reference="household-load-deviation",
                old_value="1200Wh",
                new_value="3000Wh",
                unit="Wh",
                material_transition=True,
            ),
        ),
        runtime_now=lambda: fresh.snapshot.captured_at,
    )

    assert loaded == []
    assert executed == [fresh]
    assert result == _planning_input_signature(fresh)
    assert monitor.state.last_planner_run_started_at == fresh.snapshot.captured_at
    assert monitor.state.last_planner_run_ended_at == fresh.snapshot.captured_at

def test_grid_power_observation_defaults_to_one_second() -> None:
    assert live_runtime._grid_power_observation_interval_seconds({}) == 1.0


def test_grid_power_observation_interval_is_independent_from_planner_poll() -> None:
    options = {
        "grid_power_observation_interval_seconds": 1,
        "live_poll_interval_seconds": 60,
    }

    assert (
        live_runtime._grid_power_observation_interval_seconds(options)
        == 1.0
    )
