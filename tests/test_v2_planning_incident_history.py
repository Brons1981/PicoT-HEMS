from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

from test_v2_delegated_storage_pipeline_integration import _snapshot
from test_v2_planning_fallback import _missing_forecast_fallback_run

from picot.v2.pipeline import CanonicalPipeline
from picot.v2.planning_incident_history import PlanningIncidentHistory
from picot.v2.planning_input import PlanningInputBundle, SourceEvidence


def _bundle(snapshot: object, *, state: str) -> PlanningInputBundle:
    captured_at = snapshot.captured_at
    evidence = SourceEvidence(
        evidence_id=f"evidence-{state}",
        category="pv",
        semantic_role="pv_power",
        entity_id="sensor.goodwe_vermogen",
        raw_state=state,
        raw_unit="W",
        observed_at=captured_at,
        availability="available",
        mapping_version="mapping-test",
        last_changed_at=captured_at - timedelta(seconds=30),
        last_updated_at=captured_at,
    )
    return PlanningInputBundle(
        snapshot=snapshot,
        evidence=(evidence,),
        facts=(),
        assembly_started_at=captured_at - timedelta(milliseconds=20),
        assembly_finished_at=captured_at,
    )


def test_fallback_persists_five_preceding_polls_and_recovery(tmp_path) -> None:
    path = tmp_path / "planning-incidents.jsonl"
    history = PlanningIncidentHistory(path)
    source = _snapshot()

    for index in range(6):
        run = CanonicalPipeline().run(planning_input=source)
        history.record(bundle=_bundle(source, state=str(index)), run=run)

    fallback = _missing_forecast_fallback_run()
    history.record(
        bundle=_bundle(fallback.planning_input, state="0"),
        run=fallback,
    )
    normal = CanonicalPipeline().run(planning_input=source)
    history.record(bundle=_bundle(source, state="125"), run=normal)

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["event"] for record in records] == [
        "fallback_started",
        "fallback_recovered",
    ]
    assert len(records[0]["preceding_polls"]) == 5
    assert records[0]["preceding_polls"][0]["entities"][0]["state"] == "1"
    assert records[0]["poll"]["evaluation"]["status"] == "fallback_active"
    assert records[0]["poll"]["entities"][0] == {
        "entity_id": "sensor.goodwe_vermogen",
        "category": "pv",
        "semantic_role": "pv_power",
        "state": "0",
        "unit": "W",
        "availability": "available",
        "observed_at": fallback.planning_input.captured_at.isoformat(),
        "last_changed_at": (
            fallback.planning_input.captured_at - timedelta(seconds=30)
        ).isoformat(),
        "last_updated_at": fallback.planning_input.captured_at.isoformat(),
        "error": None,
        "evidence_id": "evidence-0",
        "mapping_version": "mapping-test",
        "price_points": [],
        "pv_energy_intervals": [],
    }
    assert records[1]["incident_id"] == records[0]["incident_id"]
    assert records[1]["poll"]["captured_at_local"].endswith("+02:00")


def test_identical_active_fallback_does_not_grow_history(tmp_path) -> None:
    path = tmp_path / "planning-incidents.jsonl"
    history = PlanningIncidentHistory(path)
    fallback = _missing_forecast_fallback_run()
    bundle = _bundle(fallback.planning_input, state="0")

    history.record(bundle=bundle, run=fallback)
    history.record(bundle=bundle, run=fallback)

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["event"] for record in records] == ["fallback_started"]


def test_household_fallback_transition_is_persisted(tmp_path) -> None:
    path = tmp_path / "planning-incidents.jsonl"
    history = PlanningIncidentHistory(path)
    normal = _snapshot()
    normal_run = CanonicalPipeline().run(planning_input=normal)
    history.record(bundle=_bundle(normal, state="100"), run=normal_run)

    assert normal.household_load_forecast is not None
    fallback = replace(
        normal,
        household_load_forecast=replace(
            normal.household_load_forecast,
            fallback_active=True,
            fallback_reason="insufficient historical coverage",
        ),
    )
    fallback_run = CanonicalPipeline().run(planning_input=fallback)
    history.record(bundle=_bundle(fallback, state="0"), run=fallback_run)
    history.record(bundle=_bundle(normal, state="120"), run=normal_run)

    records = [json.loads(line) for line in path.read_text().splitlines()]
    household_events = [
        record["event"]
        for record in records
        if record["event"].startswith("household_")
    ]
    assert household_events == [
        "household_fallback_started",
        "household_fallback_recovered",
    ]
