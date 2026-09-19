"""Bounded optional pre-reduction capture; producer never waits for durable storage."""

from __future__ import annotations

import gzip
import os
import shutil
import sys
import tempfile
from collections import Counter, deque
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from typing import Literal, overload

from .storage import own_directory

CHUNK = 256 * 1024


def verified_chunks(path: Path, *, limit: int = 32 * 1024**2) -> Iterator[bytes]:
    if path.is_symlink():
        raise ValueError("evidence must not be a symlink")
    digest = sha256()
    size = 0
    with gzip.open(path, "rb") as handle:
        while block := handle.read(min(CHUNK, limit + 1 - size)):
            size += len(block)
            if size > limit:
                raise ValueError("evidence_uncompressed_limit")
            digest.update(block)
            yield block
    if digest.hexdigest() != path.name.removesuffix(".json.gz"):
        raise ValueError("evidence_digest_mismatch")


def verify(path: Path, *, limit: int = 32 * 1024**2) -> bytes:
    return b"".join(verified_chunks(path, limit=limit))


def inventory_bytes(root: Path, *, total_directory_budget: bool) -> int:
    size = 0
    # Include abandoned temporary files and metadata; never remove them for room.
    inventory = (root.rglob("*") if total_directory_budget
                 else (root / "objects").glob("*/*.json.gz"))
    for index, path in enumerate(inventory):
        if index >= 100_000:
            raise OSError("evidence inventory limit")
        if path.is_symlink():
            raise ValueError("history inventory must not follow symlinks")
        if path.is_file():
            size += path.stat().st_size
    return size


def publish(
    root: Path, text: str, *, free_reserve: int, storage_limit: int,
    total_directory_budget: bool = False,
) -> Path:
    """Worker-only I/O. Publication precedes index discovery; no manifest required."""
    objects = root / "objects"
    objects.mkdir(exist_ok=True)
    size = inventory_bytes(root, total_directory_budget=total_directory_budget)
    maximum_write = len(text) * 4 + 65536
    if size + maximum_write > storage_limit:
        raise OSError("evidence storage budget")
    if shutil.disk_usage(root).free < free_reserve + maximum_write:
        raise OSError("evidence free space reserve")
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=root)
    temporary = Path(name)
    digest = sha256()
    try:
        with os.fdopen(fd, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
                for offset in range(0, len(text), CHUNK):
                    chunk = text[offset : offset + CHUNK].encode("utf-8")
                    digest.update(chunk)
                    zipped.write(chunk)
            raw.flush()
            os.fsync(raw.fileno())
        key = digest.hexdigest()
        directory = objects / key[:2]
        directory.mkdir(exist_ok=True)
        if directory.is_symlink():
            raise ValueError("evidence bucket must not be a symlink")
        destination = directory / f"{key}.json.gz"
        try:
            # Never replace an existing evidence object, including a corrupt one.
            os.link(temporary, destination)
        except FileExistsError:
            for _ in verified_chunks(destination):
                pass
        finally:
            temporary.unlink(missing_ok=True)
        for folder in (directory, objects, root):
            directory_fd = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


class EvidenceRecorder:
    """Explicitly created only; live capture requires the disabled-by-default trial."""

    def __init__(
        self,
        root: Path,
        *,
        max_records: int = 2,
        max_record_bytes: int = 32 * 1024**2,
        memory_budget: int = 64 * 1024**2,
        storage_limit: int = 512 * 1024**2,
        free_reserve: int = 128 * 1024**2,
        stop_on_failure: bool = False,
        duration_seconds: float | None = None,
        total_directory_budget: bool = False,
    ) -> None:
        if min(max_records, max_record_bytes, memory_budget, storage_limit) <= 0:
            raise ValueError("positive history budgets required")
        if duration_seconds is not None and duration_seconds <= 0:
            raise ValueError("positive trial duration required")
        self._deadline = (
            monotonic() + duration_seconds if duration_seconds is not None else None
        )
        self._stop_on_failure = stop_on_failure
        self._total_directory_budget = total_directory_budget
        self._failed = Event()
        self.root = own_directory(root)
        self.max_records, self.max_record_bytes = max_records, max_record_bytes
        self.memory_budget, self.storage_limit, self.free_reserve = (
            memory_budget,
            storage_limit,
            free_reserve,
        )
        self._lock = Lock()
        self._queue: deque[tuple[str, int]] = deque()
        self._pending = self._reserved = 0
        self._storage_bytes = -1
        self._stopping = False
        self._contended = self._too_large = 0
        self._idle = Event()
        self._outcomes: Counter[str] = Counter()
        self._worker = Thread(target=self._run, name="picot-history-capture", daemon=True)
        self._worker.start()

    def offer(self, text: str) -> str:
        if self._failed.is_set():
            return "stopped"
        if self._expired():
            return "expired"
        size = sys.getsizeof(text)
        if size > self.max_record_bytes:
            self._too_large += 1
            return "too_large"
        if not self._lock.acquire(blocking=False):
            self._contended += 1
            return "contended"
        try:
            if self._stopping:
                return "stopped"
            if self._pending >= self.max_records or self._reserved + size > self.memory_budget:
                self._outcomes["rejected_full"] += 1
                return "full"
            self._queue.append((text, size))
            self._pending += 1
            self._reserved += size
            return "accepted"
        finally:
            self._lock.release()

    def _expired(self) -> bool:
        return self._deadline is not None and monotonic() >= self._deadline

    @overload
    def status(self, *, blocking: Literal[True] = True) -> dict[str, int]: ...

    @overload
    def status(self, *, blocking: Literal[False]) -> dict[str, int] | None: ...

    def status(self, *, blocking: bool = True) -> dict[str, int] | None:
        """Runtime diagnostics use blocking=False and skip a contended sample."""
        if not self._lock.acquire(blocking=blocking):
            return None
        try:
            return dict(self._outcomes) | {
                "expired": int(self._expired()),
                "stopped": int(self._stopping or self._failed.is_set()),
                "storage_bytes": self._storage_bytes,
                "pending": self._pending,
                "reserved": self._reserved,
                "rejected_contended": self._contended,
                "rejected_too_large": self._too_large,
            }
        finally:
            self._lock.release()

    def close(self, timeout: float = 5.0) -> bool:
        with self._lock:
            self._stopping = True
        self._idle.set()
        self._worker.join(timeout)
        return not self._worker.is_alive()

    def _run(self) -> None:
        while True:
            with self._lock:
                if self._failed.is_set() or self._expired():
                    self._outcomes["discarded"] += len(self._queue)
                    self._queue.clear()
                    self._pending = self._reserved = 0
                    self._stopping = True
                    return
                item = self._queue.popleft() if self._queue else None
                stopping = self._stopping
            if item is None:
                if stopping:
                    return
                self._idle.wait(0.05)
                self._idle.clear()
                continue
            text, size = item
            outcome = "published"
            try:
                publish(
                    self.root,
                    text,
                    free_reserve=self.free_reserve,
                    storage_limit=self.storage_limit,
                    total_directory_budget=self._total_directory_budget,
                )
            except Exception:
                outcome = "failed"
                if self._stop_on_failure:
                    self._failed.set()
            finally:
                if self._total_directory_budget:
                    try:
                        self._storage_bytes = inventory_bytes(
                            self.root, total_directory_budget=True,
                        )
                    except (OSError, ValueError):
                        self._storage_bytes = -1
                # Drop the large objects before releasing their reservation.
                text = ""
                item = None
                with self._lock:
                    self._pending -= 1
                    self._reserved -= size
                    self._outcomes[outcome] += 1
