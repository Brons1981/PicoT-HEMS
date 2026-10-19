"""One immutable-by-contract JSON read snapshot per file owner."""

import json
from pathlib import Path
from threading import RLock
from typing import Any


class JSONFileCache:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()
        self._signature: tuple[int, ...] | None = None
        self._value: Any = None

    def invalidate(self) -> None:
        with self._lock:
            self._signature = None
            self._value = None

    def _stat(self) -> tuple[int, ...]:
        stat = self._path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def read(self) -> Any:
        """Detect atomic replacements and in-place edits; never serve stale on failure."""
        with self._lock:
            try:
                signature = self._stat()
                if signature == self._signature:
                    return self._value
                self.invalidate()
                for _ in range(3):
                    value = json.loads(self._path.read_text(encoding="utf-8"))
                    after = self._stat()
                    if signature == after:
                        self._value, self._signature = value, signature
                        return value
                    signature = after
                raise OSError("plan state kept changing during read")
            except (OSError, ValueError):
                self.invalidate()
                raise
