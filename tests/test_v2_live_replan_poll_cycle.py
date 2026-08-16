from datetime import UTC, datetime, timedelta
from pathlib import Path

import picot.v2.live_runtime as live_runtime
from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.live_runtime import _planning_input_signature, _poll_live_cycle
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


def test_poll_cycle_always_loads_fresh_input_but_skips_identical_execution() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    second = _bundle(captured_at=BASE + timedelta(minutes=1), price=0.20)
    loaded = [second]
    calls: list[str] = []

    result = _poll_live_cycle(
        previous_signature=_planning_input_signature(first),
        load_bundle=lambda: loaded.pop(0),
        execute=lambda bundle: calls.append(bundle.snapshot.run_id),
    )

    assert loaded == []
    assert calls == []
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
