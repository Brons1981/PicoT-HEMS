from datetime import UTC, datetime, timedelta

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.live_runtime import _planning_input_signature, _run_live_cycle
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


def test_run_live_cycle_executes_first_cycle_and_returns_new_signature() -> None:
    bundle = _bundle(captured_at=BASE)
    calls: list[str] = []

    result = _run_live_cycle(
        previous_signature=None,
        bundle=bundle,
        execute=lambda current: calls.append(current.snapshot.run_id),
    )

    assert calls == [bundle.snapshot.run_id]
    assert result == _planning_input_signature(bundle)


def test_run_live_cycle_skips_identical_content_and_keeps_signature() -> None:
    first = _bundle(captured_at=BASE)
    second = _bundle(captured_at=BASE + timedelta(minutes=1))
    previous_signature = _planning_input_signature(first)
    calls: list[str] = []

    result = _run_live_cycle(
        previous_signature=previous_signature,
        bundle=second,
        execute=lambda current: calls.append(current.snapshot.run_id),
    )

    assert calls == []
    assert result == previous_signature


def test_run_live_cycle_executes_changed_content_and_updates_signature() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    second = _bundle(captured_at=BASE + timedelta(minutes=1), price=0.10)
    previous_signature = _planning_input_signature(first)
    calls: list[str] = []

    result = _run_live_cycle(
        previous_signature=previous_signature,
        bundle=second,
        execute=lambda current: calls.append(current.snapshot.run_id),
    )

    assert calls == [second.snapshot.run_id]
    assert result == _planning_input_signature(second)
    assert result != previous_signature


def test_run_live_cycle_executes_unchanged_content_at_forced_boundary() -> None:
    first = _bundle(captured_at=BASE)
    boundary = BASE + timedelta(minutes=15)
    at_boundary = _bundle(captured_at=boundary)
    calls: list[str] = []

    result = _run_live_cycle(
        previous_signature=_planning_input_signature(first),
        bundle=at_boundary,
        execute=lambda current: calls.append(current.snapshot.run_id),
        force_run=lambda current: current.snapshot.captured_at >= boundary,
    )

    assert calls == [at_boundary.snapshot.run_id]
    assert result == _planning_input_signature(at_boundary)
