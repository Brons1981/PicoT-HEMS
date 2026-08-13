from datetime import UTC, datetime, timedelta

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.live_runtime import _planning_input_signature, _should_run_cycle
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


def test_identical_source_content_has_same_signature_across_fresh_snapshots() -> None:
    first = _bundle(captured_at=BASE)
    second = _bundle(captured_at=BASE + timedelta(minutes=1))

    assert first.snapshot.run_id != second.snapshot.run_id
    assert _planning_input_signature(first) == _planning_input_signature(second)


def test_changed_price_forecast_changes_signature() -> None:
    first = _bundle(captured_at=BASE, price=0.20)
    second = _bundle(captured_at=BASE + timedelta(minutes=1), price=0.10)

    assert _planning_input_signature(first) != _planning_input_signature(second)


def test_changed_canonical_fact_changes_signature() -> None:
    first = _bundle(captured_at=BASE, grid_power=500.0)
    second = _bundle(captured_at=BASE + timedelta(minutes=1), grid_power=700.0)

    assert _planning_input_signature(first) != _planning_input_signature(second)


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
