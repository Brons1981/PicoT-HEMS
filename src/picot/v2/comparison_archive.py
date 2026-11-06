"""Lossless, self-contained compression of oversized diagnostic comparisons.

Only the wire record changes. Planning input and execution evidence remain directly
readable; expand_comparison_record restores every original comparison field.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
from typing import Any

ENCODING = "gzip-base64-json:v1"
_FIELDS = ("candidate_set", "outcomes", "evaluation", "comparison_evidence_dictionary",
           "comparison_detail_format")


def archive_comparison_record(record: dict[str, Any]) -> dict[str, Any]:
    poll = record.get("poll")
    if not isinstance(poll, dict) or poll.get("comparison_detail_format") != (
        "market-revision-compact:v1"
    ):
        return record
    raw = json.dumps({key: poll[key] for key in _FIELDS if key in poll},
                     separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    evaluation = poll.get("evaluation", {})
    summary = {key: value for key, value in evaluation.items()
               if key not in {"canonical_record", "evaluated_candidate_ids"}}
    return {**record, "poll": {
        **{key: value for key, value in poll.items() if key not in _FIELDS},
        "evaluation": summary,
        "comparison_detail_format": "market-revision-archive:v1",
        "comparison_archive": {
            "encoding": ENCODING, "uncompressed_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "data": base64.b64encode(gzip.compress(raw, compresslevel=1, mtime=0)).decode("ascii"),
        },
    }}


def expand_comparison_record(record: dict[str, Any]) -> dict[str, Any]:
    """Restore the exact JSON fields; reject damaged or unsupported archives."""
    poll = record.get("poll")
    if not isinstance(poll, dict) or "comparison_archive" not in poll:
        return record
    archive = poll["comparison_archive"]
    if archive.get("encoding") != ENCODING:
        raise ValueError("unsupported comparison archive encoding")
    raw = gzip.decompress(base64.b64decode(archive["data"], validate=True))
    if (len(raw) != archive["uncompressed_bytes"]
            or hashlib.sha256(raw).hexdigest() != archive["sha256"]):
        raise ValueError("comparison archive integrity mismatch")
    restored = json.loads(raw)
    if not isinstance(restored, dict) or set(restored) - set(_FIELDS):
        raise ValueError("invalid comparison archive fields")
    return {**record, "poll": {
        **{key: value for key, value in poll.items() if key != "comparison_archive"},
        **restored,
    }}
