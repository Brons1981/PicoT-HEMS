"""Export functions for PicoT Discovery outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    """Write UTF-8 JSON in a stable, human-readable form."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def export_discovery_snapshot(
    result: dict[str, Any], output_directory: Path
) -> dict[str, Path]:
    """Export both source datasets and a complete Discovery snapshot."""
    files = {
        "config": output_directory / "config.json",
        "states": output_directory / "states.json",
        "services": output_directory / "services.json",
        "summary": output_directory / "discovery_summary.json",
        "snapshot": output_directory / "discovery_snapshot.json",
    }

    write_json(files["config"], result["config"])
    write_json(files["states"], result["states"])
    write_json(files["services"], result["services"])
    write_json(files["summary"], result["summary"])
    write_json(files["snapshot"], result)

    return files
