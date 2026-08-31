from inspect import getsource
from pathlib import Path

from picot.architecture_ownership import OWNERSHIP_BY_LAYER
from picot.v2.mep_canonical_pipeline import build_mep_canonical_run

ROOT = Path(__file__).resolve().parents[1]


def test_every_architecture_reference_exists() -> None:
    missing = sorted(
        adr_path
        for ownership in OWNERSHIP_BY_LAYER.values()
        for adr_path in ownership.adr_paths
        if not (ROOT / adr_path).is_file()
    )

    assert missing == []


def test_every_owned_module_exposes_its_machine_readable_boundary() -> None:
    for layer, ownership in OWNERSHIP_BY_LAYER.items():
        source_path = (ROOT / "src" / Path(*ownership.module.split("."))).with_suffix(".py")
        source = source_path.read_text(encoding="utf-8")

        assert "ARCHITECTURE_OWNERSHIP" in source, source_path
        assert f'architecture_ownership("{layer}", __name__)' in source, source_path


def test_ownership_entries_define_positive_and_negative_boundaries() -> None:
    for ownership in OWNERSHIP_BY_LAYER.values():
        assert ownership.owns
        assert ownership.must_not
        assert set(ownership.owns).isdisjoint(ownership.must_not)


def test_session_start_routes_to_every_registered_adr() -> None:
    session_start = (ROOT / "PICOT_SESSION_START.md").read_text(encoding="utf-8")

    missing = sorted(
        adr_path
        for ownership in OWNERSHIP_BY_LAYER.values()
        for adr_path in ownership.adr_paths
        if adr_path not in session_start
    )

    assert missing == []


def test_live_mep_pipeline_delegates_all_winner_selection_to_adr032() -> None:
    source = getsource(build_mep_canonical_run)

    assert "EvaluationEngine().evaluate(" in source
    assert "MarketDailyEvaluationEngine" not in source
    assert "evaluate_commitment" not in source


def test_live_mep_pipeline_delegates_plan_construction_to_adr033() -> None:
    source = getsource(build_mep_canonical_run)

    assert "ExecutionPlanBuilder().build(" in source
    assert "ObserverExecutionPlan(" not in source
    assert "ObserverExecutionPlanSegment(" not in source
