from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest
from test_v2_live_replan_cycle import _bundle

from picot.v2.diagnostic_downloads import diagnostic_zip
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.household_load_rejections import HouseholdLoadRejectionStore
from picot.v2.live_runtime import _poll_live_cycle
from picot.v2.planning_input import SourceEvidence, _assess_household_load_evidence

AT = datetime(2026, 9, 21, 12, 10, tzinfo=UTC)


def evidence(pv="876"):
    values = {"grid_power": "0", "pv_power": pv, "storage_power_signed": "1400",
              "storage_power_to_house": "0", "storage_power_from_house": "1400"}
    return tuple(SourceEvidence(
        evidence_id=role, category="test", semantic_role=role, entity_id="sensor." + role,
        raw_state=value, raw_unit="W", observed_at=AT, availability="available",
        mapping_version="test-v1", state_read_at=AT, last_updated_at=AT,
    ) for role, value in values.items())


def bundle(pv="876"):
    sources = evidence(pv)
    observation, reason = _assess_household_load_evidence(sources, sampled_at=AT)
    return replace(_bundle(captured_at=AT), evidence=sources,
                   household_load_observation=observation, household_load_rejection_reason=reason)


def test_rejected_balance_preserves_sources_and_export_but_never_valid_load(tmp_path):
    b = bundle()
    assert b.household_load_observation is None
    assert b.household_load_rejection_reason == "negative_household_power_balance"
    path = tmp_path / "picot_v2_household_load_rejections.jsonl"
    HouseholdLoadRejectionStore(path).append(b)
    record = json.loads(path.read_text())
    assert record["reason"] == "negative_household_power_balance"
    assert record["snapshot_id"] == b.snapshot.snapshot_id
    assert {s["semantic_role"]: s["raw_state"] for s in record["sources"]} == {
        "grid_power": "0", "pv_power": "876", "storage_power_signed": "1400",
        "storage_power_to_house": "0", "storage_power_from_house": "1400"}
    assert all(s["state_read_at"] == AT.isoformat() for s in record["sources"])
    assert HouseholdLoadHistoryStore(path).load() == ()
    with ZipFile(BytesIO(diagnostic_zip((path,)))) as z:
        assert z.read(path.name) == path.read_bytes()
    HouseholdLoadRejectionStore(path).append(bundle("2000"))
    assert len(path.read_text().splitlines()) == 1


@pytest.mark.parametrize(("sources", "reason"), [
    (evidence()[:-1], "required_source_missing"),
    (evidence() + evidence()[:1], "duplicate_source_role"),
    (evidence("unknown"), "source_value_not_numeric"),
    (evidence("nan"), "source_value_not_finite"),
    ((replace(evidence()[0], availability="unavailable"),) + evidence()[1:],
     "source_unavailable_or_invalid_metadata"),
    (evidence()[:-1] + (replace(evidence()[-1], raw_state="0"),),
     "storage_power_inconsistent"),
])
def test_rejection_reason_comes_from_input_assessment(sources, reason):
    assert _assess_household_load_evidence(sources, sampled_at=AT) == (None, reason)


def test_storage_limit_keeps_existing_evidence(tmp_path, monkeypatch):
    import picot.v2.household_load_rejections as module
    path = tmp_path / "rejections.jsonl"
    store = HouseholdLoadRejectionStore(path)
    store.append(bundle())
    original = path.read_bytes()
    monkeypatch.setattr(module, "MAX_HISTORY_BYTES", len(original))
    with pytest.raises(OSError, match="storage_limit"):
        store.append(bundle())
    assert path.read_bytes() == original


def test_rejected_poll_is_recorded_and_storage_failure_does_not_stop_cycle(capsys):
    b = bundle()
    executed, rejected, accepted = [], [], []
    def failed_store(current):
        rejected.append(current)
        raise OSError("test_write_failure")
    _poll_live_cycle(previous_signature=None, load_bundle=lambda: b,
                     execute=executed.append, persist_observation=accepted.append,
                     persist_rejection=failed_store)
    assert executed == [b]
    assert rejected == [b]
    assert accepted == []
    assert "rejection_history_unavailable" in capsys.readouterr().out
