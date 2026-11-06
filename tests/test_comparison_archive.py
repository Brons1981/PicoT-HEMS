import json

import pytest

from picot.v2.comparison_archive import archive_comparison_record, expand_comparison_record


def test_archive_roundtrip_preserves_all_fields_and_rejects_damage():
    record = {"event": "planning_outcome_changed", "poll": {
        "captured_at_utc": "2026-11-06T16:29:21+00:00",
        "planning_input": {"snapshot_id": "source"},
        "comparison_detail_format": "market-revision-compact:v1",
        "candidate_set": {"candidates": [{"candidate_id": "a"}]},
        "outcomes": {"unavailable": None, "amount": -0.000248552502},
        "evaluation": {"status": "plan_retained", "canonical_record": {"winner": "a"},
                       "evaluated_candidate_ids": ["a"]},
        "comparison_evidence_dictionary": {"e0": {"ids": ["evidence"]}},
    }}
    before = json.dumps(record)
    archived = archive_comparison_record(record)
    assert archived["poll"]["planning_input"] == record["poll"]["planning_input"]
    assert archived["poll"]["evaluation"]["status"] == "plan_retained"
    assert expand_comparison_record(archived) == record
    assert json.dumps(record) == before
    archived["poll"]["comparison_archive"]["sha256"] = "damaged"
    with pytest.raises(ValueError, match="integrity"):
        expand_comparison_record(archived)


def test_existing_unarchived_records_are_unchanged():
    record = {"poll": {"captured_at_utc": "2026-11-06T00:00:00Z"}}
    assert archive_comparison_record(record) is record
    assert expand_comparison_record(record) is record
