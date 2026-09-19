from __future__ import annotations

import json
from threading import Event

import pytest

from picot.v2.passive_history.evidence import EvidenceRecorder, verify
from picot.v2.passive_history.trial import HistoryCaptureTrial
from picot.v2.planning_incident_history import PlanningIncidentHistory


@pytest.mark.parametrize(
    "options",
    [{}, {"history_capture_trial_enabled": False}, {"history_capture_trial_enabled": "false"}],
)
def test_disabled_has_no_directory_or_recorder(tmp_path, options):
    trial = HistoryCaptureTrial(options, root=tmp_path / "trial")
    assert trial.evidence_offer is None
    assert trial.report()["state"] == "disabled"
    assert not (tmp_path / "trial").exists()


def test_real_capture_keeps_full_record_and_original_output(tmp_path):
    trial = HistoryCaptureTrial({"history_capture_trial_enabled": True}, root=tmp_path / "trial")
    original = PlanningIncidentHistory(tmp_path / "original.jsonl")
    enabled = PlanningIncidentHistory(
        tmp_path / "enabled.jsonl", evidence_offer=trial.evidence_offer
    )
    record = {"event": "synthetic", "poll": {"padding": "x" * (9 * 1024**2)}}
    original._append(record)
    enabled._append(record)
    assert trial.recorder.close()
    assert enabled.path.read_bytes() == original.path.read_bytes()
    paths = list((tmp_path / "trial" / "objects").glob("*/*.json.gz"))
    assert len(paths) == 1
    assert json.loads(verify(paths[0])) == record
    report = trial.report()
    assert report["accepted"] == report["published"] == 1
    assert report["missed"] == 0
    assert report["offer_max_ms"] >= 0


def test_initialization_failure_contains_error(tmp_path):
    root = tmp_path / "trial"
    root.mkdir()
    (root / "foreign").write_text("keep")
    trial = HistoryCaptureTrial({"history_capture_trial_enabled": True}, root=root)
    assert trial.evidence_offer is None
    assert trial.report()["state"] == "initialization_failed"
    assert (root / "foreign").read_text() == "keep"


def test_failure_stops_and_discards_queue_without_retry(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    calls = []

    def failed(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        raise OSError("disk full")

    monkeypatch.setattr("picot.v2.passive_history.evidence.publish", failed)
    recorder = EvidenceRecorder(tmp_path / "trial", stop_on_failure=True)
    try:
        assert recorder.offer("one") == "accepted"
        assert entered.wait(2)
        assert recorder.offer("two") == "accepted"
        release.set()
        assert recorder.close()
        assert calls == [1]
        status = recorder.status()
        assert status["failed"] == status["discarded"] == 1
        assert status["pending"] == status["reserved"] == 0
        assert recorder.offer("three") == "stopped"
    finally:
        release.set()
        recorder.close()


def test_deadline_and_nonblocking_status(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("picot.v2.passive_history.evidence.monotonic", lambda: now[0])
    recorder = EvidenceRecorder(tmp_path / "trial", duration_seconds=30)
    try:
        recorder._lock.acquire()
        try:
            assert recorder.status(blocking=False) is None
        finally:
            recorder._lock.release()
        now[0] = 130.0
        assert recorder.offer("{}") == "expired"
        assert recorder.close()
        assert recorder.status()["expired"] == 1
    finally:
        recorder.close()


def test_budget_counts_abandoned_temporary_files(tmp_path):
    recorder = EvidenceRecorder(
        tmp_path / "trial", storage_limit=100_000, stop_on_failure=True, total_directory_budget=True
    )
    (recorder.root / ".pending-old").write_bytes(b"x" * 100_000)
    assert recorder.offer("{}") == "accepted"
    assert recorder.close()
    assert recorder.status()["failed"] == 1
    assert not list(recorder.root.glob("objects/*/*.json.gz"))
    assert (recorder.root / ".pending-old").stat().st_size == 100_000


def test_runtime_diagnostic_reports_disabled_baseline_and_failure_is_contained(
    tmp_path, capsys, monkeypatch
):
    from picot.v2.live_runtime import _log_history_capture_trial

    trial = HistoryCaptureTrial({}, root=tmp_path / "trial")
    _log_history_capture_trial(trial, cycle_ms=125.125, cycle_cpu_ms=40.5)
    row = json.loads(capsys.readouterr().out)
    assert row["state"] == "disabled"
    assert row["cycle_ms"] == 125.125
    assert row["cycle_cpu_ms"] == 40.5
    assert "rss_kib" in row

    def fail():
        raise OSError("diagnostic failure")

    monkeypatch.setattr(trial, "report", fail)
    _log_history_capture_trial(trial, cycle_ms=1, cycle_cpu_ms=1)
    assert capsys.readouterr().out == ""


def test_trial_report_skips_contended_status_without_waiting(tmp_path):
    trial = HistoryCaptureTrial({"history_capture_trial_enabled": True}, root=tmp_path / "trial")
    try:
        trial.recorder._lock.acquire()
        try:
            result = trial.report()
            assert result["status_available"] is False
            assert result["missed"] is None
        finally:
            trial.recorder._lock.release()
    finally:
        trial.recorder.close()


def test_addon_switch_is_optional_and_off_by_default():
    from pathlib import Path

    config = (Path(__file__).parents[1] / "picot_hems" / "config.yaml").read_text()
    options, schema = config.split("schema:")
    assert "history_capture_trial_enabled: false" in options
    assert "history_capture_trial_enabled: bool?" in schema


def test_actual_mep_record_retains_lineage_and_commitment(tmp_path):
    from dataclasses import asdict

    from test_independent_daily_reference_adapter import _snapshot
    from test_v2_mep_canonical_pipeline import _pipeline
    from test_v2_planning_incident_history import _bundle

    pipeline, _ = _pipeline(tmp_path)
    snapshot = _snapshot()
    run = pipeline.run(planning_input=snapshot)
    before_run = asdict(run)
    before_store = (tmp_path / "commitments.json").read_bytes()
    trial = HistoryCaptureTrial({"history_capture_trial_enabled": True}, root=tmp_path / "trial")
    disabled = PlanningIncidentHistory(tmp_path / "disabled.jsonl")
    enabled = PlanningIncidentHistory(
        tmp_path / "enabled.jsonl", evidence_offer=trial.evidence_offer
    )
    try:
        for history in (disabled, enabled):
            history.record(bundle=_bundle(snapshot, state="125"), run=run)
        assert trial.recorder.close()
        assert enabled.path.read_bytes() == disabled.path.read_bytes()
        assert asdict(run) == before_run
        assert (tmp_path / "commitments.json").read_bytes() == before_store
        captured = [
            json.loads(verify(path)) for path in trial.recorder.root.glob("objects/*/*.json.gz")
        ]
        originals = [json.loads(line) for line in disabled.path.read_text().splitlines()]
        assert len(captured) > 0
        assert all(record in captured for record in originals)
        assert captured[0]["poll"]["snapshot_id"] == snapshot.snapshot_id
        assert captured[0]["poll"]["evaluation"]["evaluation_id"] == run.evaluation.evaluation_id
    finally:
        trial.recorder.close()


def test_low_free_space_stops_capture_and_reports_loss(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "picot.v2.passive_history.evidence.shutil.disk_usage", lambda _: SimpleNamespace(free=1)
    )
    trial = HistoryCaptureTrial({"history_capture_trial_enabled": True}, root=tmp_path / "trial")
    assert trial.evidence_offer("{}") == "accepted"
    assert trial.recorder.close()
    report = trial.report()
    assert report["state"] == "storage_failed"
    assert report["missed"] == 1
    assert report["pending"] == 0
    assert not list(trial.recorder.root.glob("objects/*/*.json.gz"))
