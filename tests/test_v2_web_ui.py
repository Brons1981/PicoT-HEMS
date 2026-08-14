import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from picot.v2.contracts import (
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project
from picot.v2.web_ui import WebViewStore, build_web_view


def test_web_view_serializes_nine_stages_and_full_pv_timeline() -> None:
    captured_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    bootstrap = CanonicalPipeline().run(
        captured_at=captured_at
    ).planning_input
    starts_at = captured_at + timedelta(minutes=30)
    intervals = (
        PVEnergyTimelineInterval(
            interval_id="pv-interval-1",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            pv_energy_wh=1200.0,
            evidence_type="FORECAST",
            confidence=0.90,
            actual_evidence_ids=(),
            forecast_evidence_ids=("solcast-1",),
            conversion_method_version="solcast:v1",
        ),
        PVEnergyTimelineInterval(
            interval_id="pv-interval-2",
            starts_at=starts_at + timedelta(minutes=30),
            ends_at=starts_at + timedelta(minutes=60),
            pv_energy_wh=1350.0,
            evidence_type="FORECAST",
            confidence=0.85,
            actual_evidence_ids=(),
            forecast_evidence_ids=("solcast-2",),
            conversion_method_version="solcast:v1",
        ),
    )
    timeline = PVEnergyTimeline(
        timeline_id="pv-timeline-1",
        run_id=bootstrap.run_id,
        snapshot_id=bootstrap.snapshot_id,
        intervals=intervals,
    )
    run = CanonicalPipeline().run(
        planning_input=replace(
            bootstrap,
            pv_energy_timeline=timeline,
        )
    )

    view = build_web_view(run, project(run))

    assert view["schema_version"] == 1
    assert view["observer_only"] is True
    assert view["picot_version"] == run.planning_input.picot_version
    assert view["run_id"] == run.planning_input.run_id
    assert view["snapshot_id"] == run.planning_input.snapshot_id
    assert view["captured_at"] == "2026-08-14T10:00:00+00:00"

    pipeline = view["pipeline"]
    assert len(pipeline) == 9
    assert [item["stage"] for item in pipeline] == list(range(1, 10))
    assert pipeline[0]["entity_id"] == (
        "sensor.picot_v2_pipeline_01_planning_input"
    )
    assert pipeline[0]["state"] == "ready"
    assert pipeline[0]["attributes"]["pv_energy_total_wh"] == 2550.0

    assert view["pv_energy_timeline"] == {
        "available": True,
        "timeline_id": "pv-timeline-1",
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "interval_count": 2,
        "total_wh": 2550.0,
        "starts_at": "2026-08-14T10:30:00+00:00",
        "ends_at": "2026-08-14T11:30:00+00:00",
        "intervals": [
            {
                "interval_id": "pv-interval-1",
                "starts_at": "2026-08-14T10:30:00+00:00",
                "ends_at": "2026-08-14T11:00:00+00:00",
                "pv_energy_wh": 1200.0,
                "evidence_type": "FORECAST",
                "confidence": 0.90,
                "actual_evidence_ids": [],
                "forecast_evidence_ids": ["solcast-1"],
                "conversion_method_version": "solcast:v1",
            },
            {
                "interval_id": "pv-interval-2",
                "starts_at": "2026-08-14T11:00:00+00:00",
                "ends_at": "2026-08-14T11:30:00+00:00",
                "pv_energy_wh": 1350.0,
                "evidence_type": "FORECAST",
                "confidence": 0.85,
                "actual_evidence_ids": [],
                "forecast_evidence_ids": ["solcast-2"],
                "conversion_method_version": "solcast:v1",
            },
        ],
    }
    assert json.loads(json.dumps(view)) == view


def test_web_view_represents_missing_pv_timeline_without_intervals() -> None:
    run = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    )

    view = build_web_view(run, project(run))

    assert view["pv_energy_timeline"] == {
        "available": False,
        "timeline_id": None,
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "interval_count": 0,
        "total_wh": 0,
        "starts_at": None,
        "ends_at": None,
        "intervals": [],
    }


def test_web_view_store_atomically_replaces_latest_serialized_view() -> None:
    store = WebViewStore()
    first: dict[str, object] = {
        "run_id": "run-1",
        "pipeline": [{"stage": 1, "state": "ready"}],
    }
    second: dict[str, object] = {
        "run_id": "run-2",
        "pipeline": [{"stage": 1, "state": "updated"}],
    }

    assert store.latest_json() is None

    store.publish(first)
    first["run_id"] = "mutated-after-publish"
    first_json = store.latest_json()

    assert first_json is not None
    assert json.loads(first_json) == {
        "run_id": "run-1",
        "pipeline": [{"stage": 1, "state": "ready"}],
    }

    store.publish(second)
    second_json = store.latest_json()

    assert second_json is not None
    assert json.loads(second_json) == {
        "run_id": "run-2",
        "pipeline": [{"stage": 1, "state": "updated"}],
    }
