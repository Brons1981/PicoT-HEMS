from datetime import UTC, datetime

from picot.v2.live_runtime import _append_storage_mode_transition
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project
from picot.v2.storage_mode_transition_history import (
    StorageModeTransitionEvent,
    StorageModeTransitionHistoryStore,
)
from picot.v2.web_ui import DASHBOARD_HTML, build_web_view


def _event(*, application_id: str = "application-1") -> StorageModeTransitionEvent:
    return StorageModeTransitionEvent(
        event_id=f"transition-{application_id}",
        occurred_at=datetime(2026, 8, 17, 10, 25, tzinfo=UTC),
        previous_vendor_mode="Nul op de meter",
        requested_vendor_mode="Alleen slim opladen",
        source="canonical_execution",
        reason="pv_charge_only_satisfies_storage_requirement",
        confidence=0.72,
        run_id="run-1",
        snapshot_id="snapshot-1",
        evaluation_id="evaluation-1",
        plan_id="plan-1",
        application_id=application_id,
    )


def test_transition_history_survives_restart_and_preserves_facts(tmp_path) -> None:
    path = tmp_path / "storage-mode-transitions.jsonl"
    store = StorageModeTransitionHistoryStore(path)

    assert store.append(_event()) is True

    restored = StorageModeTransitionHistoryStore(path).load()
    assert len(restored) == 1
    assert restored[0].previous_vendor_mode == "Nul op de meter"
    assert restored[0].requested_vendor_mode == "Alleen slim opladen"
    assert restored[0].confidence == 0.72
    assert restored[0].run_id == "run-1"


def test_transition_history_deduplicates_application_id(tmp_path) -> None:
    store = StorageModeTransitionHistoryStore(tmp_path / "history.jsonl")

    assert store.append(_event()) is True
    assert store.append(_event()) is False
    assert len(store.load()) == 1


def test_transition_history_skips_interrupted_row(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    store = StorageModeTransitionHistoryStore(path)
    store.append(_event())
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version":1')

    assert store.load() == (_event(),)


def test_web_view_exposes_transition_facts_on_history_tab() -> None:
    run = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 17, 10, 25, tzinfo=UTC)
    )

    view = build_web_view(
        run,
        project(run),
        storage_mode_transitions=(_event(),),
    )

    assert view["storage_mode_transition_history"] == [
        {
            "event_id": "transition-application-1",
            "occurred_at": "2026-08-17T10:25:00+00:00",
            "previous_vendor_mode": "Nul op de meter",
            "requested_vendor_mode": "Alleen slim opladen",
            "source": "canonical_execution",
            "reason": "pv_charge_only_satisfies_storage_requirement",
            "confidence": 0.72,
            "run_id": "run-1",
            "snapshot_id": "snapshot-1",
            "evaluation_id": "evaluation-1",
            "plan_id": "plan-1",
            "application_id": "application-1",
        }
    ]
    assert 'id="storage-mode-transition-history"' in DASHBOARD_HTML
    assert "renderStorageModeTransitionHistory" in DASHBOARD_HTML


def test_runtime_records_only_a_real_mode_change(tmp_path) -> None:
    store = StorageModeTransitionHistoryStore(tmp_path / "history.jsonl")
    facts = dict(
        source="canonical_execution",
        reason="hard_constraint_storage_requirement_satisfied",
        confidence=0.64,
        run_id="run-2",
        snapshot_id="snapshot-2",
        evaluation_id="evaluation-2",
        plan_id="plan-2",
        application_id="application-2",
        occurred_at=datetime(2026, 8, 17, 11, 0, tzinfo=UTC),
    )

    _append_storage_mode_transition(
        store,
        previous_vendor_mode="Nul op de meter",
        requested_vendor_mode="Alleen slim opladen",
        **facts,
    )
    _append_storage_mode_transition(
        store,
        previous_vendor_mode="Alleen slim opladen",
        requested_vendor_mode="Alleen slim opladen",
        **(facts | {"application_id": "application-3"}),
    )

    assert len(store.load()) == 1
