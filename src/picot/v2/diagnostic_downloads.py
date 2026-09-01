"""Read-only, explicitly allow-listed PicoT diagnostic exports."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile

MAX_INCIDENT_EVENTS = 20
TAIL_READ_CHUNK_BYTES = 64 * 1024


def incident_overview(path: Path) -> list[dict[str, object]]:
    """Return compact recent incident facts without replaying full forecasts."""
    if not path.is_file():
        return []
    records: list[dict[str, object]] = []
    for raw_line in _tail_lines(path, MAX_INCIDENT_EVENTS):
        try:
            value: object = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(_compact_incident(value))
    return records


def _tail_lines(path: Path, count: int) -> list[str]:
    """Read only the final JSONL records, even when the file is very large."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        chunks: list[bytes] = []
        newline_count = 0
        while position > 0 and newline_count <= count:
            size = min(TAIL_READ_CHUNK_BYTES, position)
            position -= size
            handle.seek(position)
            chunk = handle.read(size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
    return [
        line.decode("utf-8", errors="replace")
        for line in b"".join(reversed(chunks)).splitlines()[-count:]
    ]


def diagnostic_zip(paths: tuple[Path, ...]) -> bytes:
    """Build one archive from existing files in the explicit runtime allow-list."""
    output = BytesIO()
    write_diagnostic_zip(output, paths)
    return output.getvalue()


def write_diagnostic_zip(output: BinaryIO, paths: tuple[Path, ...]) -> None:
    """Stream an allow-listed archive without buffering every source file."""
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in paths:
            if path.is_file():
                archive.write(path, arcname=path.name)


def _compact_incident(record: dict[str, object]) -> dict[str, object]:
    if record.get("detail_level") == "basic":
        return {
            "event": record.get("event"),
            "incident_id": record.get("incident_id"),
            "captured_at_local": record.get("captured_at_local"),
            "captured_at_utc": record.get("captured_at_utc"),
            "run_id": record.get("run_id"),
            "reason": record.get("evaluation_reason"),
            "polls": [],
        }
    poll = record.get("poll")
    current = poll if isinstance(poll, dict) else {}
    preceding = record.get("preceding_polls")
    previous = preceding if isinstance(preceding, list) else []
    polls = [*previous, current]
    return {
        "event": record.get("event"),
        "incident_id": record.get("incident_id"),
        "captured_at_local": current.get("captured_at_local"),
        "captured_at_utc": current.get("captured_at_utc"),
        "run_id": current.get("run_id"),
        "reason": _evaluation_reason(current),
        "polls": [
            _compact_poll(item)
            for item in polls
            if isinstance(item, dict)
        ],
    }


def _evaluation_reason(poll: dict[str, object]) -> object:
    evaluation = poll.get("evaluation")
    return evaluation.get("reason") if isinstance(evaluation, dict) else None


def _compact_poll(poll: dict[str, object]) -> dict[str, object]:
    entities = poll.get("entities")
    return {
        "captured_at_local": poll.get("captured_at_local"),
        "captured_at_utc": poll.get("captured_at_utc"),
        "run_id": poll.get("run_id"),
        "evaluation_status": (
            evaluation.get("status")
            if isinstance((evaluation := poll.get("evaluation")), dict)
            else None
        ),
        "evaluation_reason": _evaluation_reason(poll),
        "entities": [
            {
                "entity_id": entity.get("entity_id"),
                "semantic_role": entity.get("semantic_role"),
                "state": entity.get("state"),
                "unit": entity.get("unit"),
                "availability": entity.get("availability"),
                "last_changed_at": entity.get("last_changed_at"),
                "last_updated_at": entity.get("last_updated_at"),
                "error": entity.get("error"),
            }
            for entity in entities
            if isinstance(entity, dict)
        ]
        if isinstance(entities, list)
        else [],
    }
