import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from picot_energy_devices.diagnostics import DiagnosticsRecorder
from picot_energy_devices.regulation import RegulationSnapshotStore
from picot_energy_devices.regulation_guard import CorrectionGuard
from picot_energy_devices.runtime import regulation_poll_once
from picot_energy_devices.store import EnergyDeviceStore
from picot_energy_devices.web_ui import DASHBOARD_HTML, create_web_server


def read_zip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name).decode() for name in archive.namelist()}


def sample(now, **changes):
    return dict(evaluated_at=now.isoformat(), source_measured_at=now.isoformat(),
                source_ages_seconds=[0, 0], candidate_w=200, raw_grid_w=2500,
                battery_w=0, ev_w=2300, status="ready", fallback="none", **changes)


def test_48_hour_retention_and_events_survive_restart_without_secrets(tmp_path):
    now = datetime.now(UTC)
    path = tmp_path / "telemetry.sqlite3"
    recorder = DiagnosticsRecorder(path, options={"supervisor_token": "secret-token",
                                                 "ev_local_rpc_url": "private-url",
                                                 "regulation_control_enabled": True})
    try:
        old = now - timedelta(hours=49)
        recorder.record("regulation", dict(sample(old), status="blocked", reason="old_loss"),
                        now=old)
        recorder.record("regulation", sample(now), now=now)
        recorder.record("ev", {"session": {"session_id": "ev1", "state": "active",
                                          "current_power_w": 2300, "switch_state": "on",
                                          "private_comment": "secret-comment"}}, now=now)
        recorder.queue.join()
        files = read_zip(recorder.export_zip(now=now))
        assert "old_loss" not in files["measurements.jsonl"]
        assert "old_loss" in files["events.jsonl"]
        assert '"current_power_w":2300' in files["measurements.jsonl"]
        assert all("secret" not in contents and "private-url" not in contents
                   for contents in files.values())
        assert json.loads(files["manifest.json"])["retention_hours"] == 48
        later = now + timedelta(minutes=6)
        recorder.record("regulation", sample(later), now=later)
        recorder.queue.join()
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT count(*) FROM samples WHERE stamp < ?",
                              (now.timestamp() - 48 * 3600,)).fetchone()[0] == 0
    finally:
        recorder.close()
    restarted = DiagnosticsRecorder(path, options={})
    try:
        restarted.queue.join()
        assert "old_loss" in read_zip(restarted.export_zip(now=now))["events.jsonl"]
    finally:
        restarted.close()


def test_one_sample_per_second_events_not_every_heartbeat_and_consumer_fallback(tmp_path):
    now = datetime.now(UTC)
    recorder = DiagnosticsRecorder(tmp_path / "telemetry.sqlite3", options={})
    try:
        for _ in range(10):
            recorder.record("regulation", sample(now, consumer_source="energy_devices"), now=now)
        recorder.record("regulation", sample(now, consumer_source="shelly_raw"),
                        now=now + timedelta(seconds=1))
        recorder.queue.join()
        files = read_zip(recorder.export_zip(now=now + timedelta(seconds=2)))
        samples = [json.loads(line) for line in files["measurements.jsonl"].splitlines()]
        events = [json.loads(line) for line in files["events.jsonl"].splitlines()]
        assert len(samples) == 2
        assert len([e for e in events if e["kind"] == "regulation"]) == 2
        assert samples[-1]["data"]["consumer_source"] == "shelly_raw"
    finally:
        recorder.close()


def test_write_failure_and_queue_overload_are_visible_not_raised(tmp_path):
    now = datetime.now(UTC)
    recorder = DiagnosticsRecorder(tmp_path / "telemetry.sqlite3", options={})
    try:
        recorder.queue.join()
        with sqlite3.connect(recorder.path) as db:
            db.execute("DROP TABLE samples")
        recorder.record("regulation", sample(now), now=now)
        recorder.queue.join()
        assert recorder.dropped == 1
        assert recorder.last_error is not None
        with sqlite3.connect(recorder.path) as db:
            db.execute("CREATE TABLE samples (bucket INTEGER, kind TEXT, stamp REAL, "
                       "payload TEXT, PRIMARY KEY(bucket, kind))")
        recorder.record("regulation", sample(now), now=now)
        recorder.queue.join()
        events = [json.loads(line) for line in
                  read_zip(recorder.export_zip())["events.jsonl"].splitlines()]
        assert any(e["kind"] == "logging_health" and e["data"]["dropped_records"] == 1
                   for e in events)
        recorder.stop.set()
        recorder.thread.join(timeout=2)
        for _ in range(1025):
            recorder.record("regulation", sample(now), now=now)
        assert recorder.dropped == 2
    finally:
        recorder.close()


def test_latch_keeps_original_missing_source_and_time_after_recovery_and_restart(tmp_path):
    now = datetime.now(UTC)
    path = tmp_path / "guard.json"
    guard = CorrectionGuard(enabled=True, path=path)
    guard.check(result=sample(now), offered_w=200, now=now)
    missing = dict(sample(now), status="blocked", candidate_w=None,
                   reason="ev_local_api_unavailable", source_failure_entity="local_rpc")
    guard.check(result=missing, offered_w=200, now=now + timedelta(seconds=1))
    latched = guard.check(result=missing, offered_w=200, now=now + timedelta(seconds=10))
    assert latched["latched_at"] == (now + timedelta(seconds=10)).isoformat()
    recovered = CorrectionGuard(enabled=True, path=path).check(
        result=sample(now + timedelta(seconds=11)), offered_w=200,
        now=now + timedelta(seconds=11))
    assert recovered["latched_origin"]["reason"] == "ev_local_api_unavailable"
    assert recovered["latched_origin"]["source_failure_entity"] == "local_rpc"
    assert recovered["latched_at"] == latched["latched_at"]
    assert recovered["correction_source_reason"] is None


def test_legacy_latch_does_not_invent_missing_historical_cause(tmp_path):
    path = tmp_path / "guard.json"
    path.write_text('{"reason":"persistent_measurement_loss"}')
    now = datetime.now(UTC)
    output = CorrectionGuard(enabled=True, path=path).check(result=sample(now),
                                                         offered_w=200, now=now)
    assert output["status"] == "blocked"
    assert output["latched_origin"] is None
    assert output["latched_at"] is None


def test_diagnosis_download_is_real_zip_and_does_not_mutate_control(tmp_path):
    recorder = DiagnosticsRecorder(tmp_path / "telemetry.sqlite3", options={})
    recorder.queue.join()
    server = create_web_server(EnergyDeviceStore(tmp_path / "devices.sqlite3"),
                               host="127.0.0.1", port=0, diagnostics=recorder)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert 'href="api/diagnostics.zip"' in DASHBOARD_HTML
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/diagnostics.zip", timeout=5) as r:
            assert r.headers["Content-Type"] == "application/zip"
            assert "attachment; filename=" in r.headers["Content-Disposition"]
            assert "manifest.json" in read_zip(r.read())
        assert recorder.options == {}
    finally:
        server.shutdown()
        server.server_close()
        recorder.close()


def test_disabled_diagnostics_returns_explicit_503(tmp_path):
    server = create_web_server(EnergyDeviceStore(tmp_path / "devices.sqlite3"),
                               host="127.0.0.1", port=0)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{server.server_port}/api/diagnostics.zip", timeout=5)
        assert error.value.code == 503
    finally:
        server.shutdown()
        server.server_close()


def test_runtime_records_intended_offered_power_provenance_without_extra_reads(tmp_path):
    from picot_energy_devices.home_assistant import HomeAssistantClient

    class Client:
        reads = []
        measurement = staticmethod(HomeAssistantClient.measurement)

        def state(self, entity):
            self.reads.append(entity)
            return {"state": {"sensor.raw": "2500", "sensor.battery": "0",
                              "sensor.ev": "2300", "sensor.ct": "200"}[entity],
                    "last_reported": datetime.now(UTC).isoformat(),
                    "attributes": {"unit_of_measurement": "W",
                                   "selected_source": "energy_devices"}}

        def publish_regulation_policy(self, payload):
            self.policy = payload

        def publish_regulation_shadow(self, payload):
            pass

    recorder = DiagnosticsRecorder(tmp_path / "telemetry.sqlite3", options={})
    try:
        client = Client()
        regulation_poll_once(client=client, raw_entity="sensor.raw",
                             battery_entity="sensor.battery",
                             ev_entity="sensor.ev", offered_entity="sensor.ct",
                             guard=CorrectionGuard(enabled=True), diagnostics=recorder,
                             snapshots=RegulationSnapshotStore(control_enabled=True,
                                                               minimum_ready_reports=1))
        recorder.queue.join()
        files = read_zip(recorder.export_zip())
        row = json.loads(files["measurements.jsonl"].splitlines()[0])["data"]
        assert row["intended_candidate_w"] == row["offered_p1_w"] == 200
        assert row["raw_measured_at"] is not None
        assert row["ev_measured_at"] is not None
        assert client.reads == ["sensor.raw", "sensor.battery", "sensor.ev", "sensor.ct"]
        assert client.policy["candidate_w"] == 200
    finally:
        recorder.close()


def test_missing_input_origin_is_not_replaced_by_an_earlier_offer_mismatch():
    now = datetime.now(UTC)
    guard = CorrectionGuard(enabled=True)
    guard.check(result=sample(now), offered_w=200, now=now)
    guard.check(result=sample(now), offered_w=2500, now=now + timedelta(seconds=1))
    missing = dict(sample(now), status="blocked", candidate_w=None,
                   reason="ev_local_api_unavailable", source_failure_entity="local_rpc")
    output = guard.check(result=missing, offered_w=2500, now=now + timedelta(seconds=10))
    assert output["reason"] == "persistent_measurement_loss"
    assert output["latched_origin"]["reason"] == "ev_local_api_unavailable"
