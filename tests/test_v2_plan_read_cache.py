import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def write_state(path, scope="old"):
    path.write_text(json.dumps({"schema_version": 1, "commitments": {},
                                "ev_exclusion_scopes": [scope]}), encoding="utf-8")


def test_unchanged_parallel_reads_parse_once(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    write_state(path)
    store = ActivePlanCommitmentStore(path)
    original = Path.read_text
    reads = []

    def read(self, *args, **kwargs):
        reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: store.load_ev_exclusion_scopes(), range(20))) == [
            {"old"}
        ] * 20
    assert reads == [path]


def test_external_atomic_replace_same_size_and_mtime_is_seen(tmp_path):
    path = tmp_path / "state.json"
    write_state(path)
    store = ActivePlanCommitmentStore(path)
    assert store.load_ev_exclusion_scopes() == {"old"}
    stat = path.stat()
    other = tmp_path / "replacement.json"
    write_state(other, "new")
    os.utime(other, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    os.replace(other, path)
    assert store.load_ev_exclusion_scopes() == {"new"}


def test_external_edit_corruption_deletion_and_recreation(tmp_path):
    path = tmp_path / "state.json"
    write_state(path)
    store = ActivePlanCommitmentStore(path)
    assert store.load_ev_exclusion_scopes() == {"old"}
    write_state(path, "changed")
    assert store.load_ev_exclusion_scopes() == {"changed"}
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing destructive reset"):
        store.load_ev_exclusion_scopes()
    path.unlink()
    assert store.load_ev_exclusion_scopes() == set()
    write_state(path, "returned")
    assert store.load_ev_exclusion_scopes() == {"returned"}


def test_writes_are_visible_and_payloads_do_not_alias(tmp_path):
    path = tmp_path / "state.json"
    write_state(path)
    store = ActivePlanCommitmentStore(path)
    old = store._read_payload()
    store.save_ev_exclusion_scopes({"new"})
    assert old["ev_exclusion_scopes"] == ["old"]
    assert store.load_ev_exclusion_scopes() == {"new"}
    mutable = store._load_payload()
    mutable["ev_exclusion_scopes"].append("not_saved")
    assert store.load_ev_exclusion_scopes() == {"new"}


def test_returned_recalculation_status_is_deeply_detached(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 1, "commitments": {},
        "daily_recalculation": {"status": "pending", "results": {"x": [1]}}}),
        encoding="utf-8")
    store = ActivePlanCommitmentStore(path)
    store.daily_recalculation_status()["results"]["x"].append(2)
    assert store.daily_recalculation_status()["results"] == {"x": [1]}


def test_replacement_during_read_retries_new_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    write_state(path)
    store = ActivePlanCommitmentStore(path)
    original = Path.read_text
    calls = []

    def read(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            replacement = tmp_path / "new.json"
            write_state(replacement, "new")
            os.replace(replacement, path)
        return value

    monkeypatch.setattr(Path, "read_text", read)
    assert store.load_ev_exclusion_scopes() == {"new"}
    assert len(calls) == 2
