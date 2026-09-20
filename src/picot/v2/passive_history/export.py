"""Read-only export of published trial objects; content verification stays offline."""

from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

MAX_EXPORT_BYTES = 16 * 1024**2
MAX_EXPORT_OBJECTS = 64
MAX_SCAN_ENTRIES = 1024
PREFIX = "picot_history_capture_trial"


def _read_regular(path: Path, limit: int) -> bytes:
    # Reject symlinks at open as well as during discovery; never follow an object link.
    import stat

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("not_regular_or_over_budget")
        data = handle.read(limit + 1)
        if len(data) > limit:
            raise ValueError("over_budget")
        return data


def export_trial(archive: ZipFile, root: Path) -> None:
    """Only the explicitly allow-listed trial directory may reach this function."""
    objects: list[dict[str, object]] = []
    issues: list[dict[str, str]] = []
    report: dict[str, object] = {
        "schema_version": 1,
        "scope": "published_objects_only",
        "status": "exported",
        "content_verified": False,
        "scan_complete": False,
        "objects": objects,
        "issues": issues,
        "budget_bytes": MAX_EXPORT_BYTES,
        "object_limit": MAX_EXPORT_OBJECTS,
        "scan_limit": MAX_SCAN_ENTRIES,
    }
    used = scanned = 0
    try:
        if root.name != PREFIX or root.is_symlink():
            raise ValueError("invalid_trial_root")
        if not root.exists():
            report["status"] = "not_present"
            return
        marker = _read_regular(root / "passive-history.owner", 64)
        if marker != b"picot-passive-history-v1\n":
            raise ValueError("unknown_owner")
        parent = root / "objects"
        if parent.is_symlink():
            raise ValueError("symlink_objects_directory")
        for bucket in range(256):
            folder = parent / f"{bucket:02x}"
            if folder.is_symlink():
                issues.append({"path": str(folder.relative_to(root)), "reason": "symlink"})
                continue
            if not folder.exists():
                continue
            # Stream discovery instead of materialising an unbounded directory listing.
            with os.scandir(folder) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > MAX_SCAN_ENTRIES or len(objects) >= MAX_EXPORT_OBJECTS:
                        report["status"] = "partial"
                        issues.append({"reason": "inventory_or_object_limit"})
                        return
                    name = entry.name
                    if not re.fullmatch(r"[0-9a-f]{64}\.json\.gz", name):
                        issues.append({"reason": "unexpected_object_name"})
                        continue
                    if not name.startswith(folder.name):
                        issues.append({"reason": "digest_bucket_mismatch"})
                        continue
                    path = folder / name
                    relative = str(path.relative_to(root))
                    try:
                        data = _read_regular(path, MAX_EXPORT_BYTES - used)
                    except (OSError, ValueError):
                        issues.append({"path": relative, "reason": "unreadable_or_over_budget"})
                        continue
                    member = f"{PREFIX}/{relative}"
                    archive.writestr(member, data, compress_type=ZIP_STORED)
                    objects.append({
                        "member": member,
                        "bytes": len(data),
                        "compressed_sha256": sha256(data).hexdigest(),
                        "claimed_content_sha256": name.removesuffix(".json.gz"),
                    })
                    used += len(data)
        report["scan_complete"] = True
    except (OSError, ValueError):
        report["status"] = "unavailable"
        issues.append({"reason": "trial_directory_unavailable_or_invalid"})
    finally:
        if issues and report["status"] == "exported":
            report["status"] = "partial"
        report["exported_bytes"] = used
        archive.writestr(f"{PREFIX}/export-manifest.json", json.dumps(report))
