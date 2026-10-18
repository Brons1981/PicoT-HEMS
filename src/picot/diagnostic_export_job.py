"""One bounded, observable background diagnostic export per dashboard server."""

from collections.abc import Callable
from threading import Lock, Thread
from uuid import uuid4

Progress = Callable[[int, int, str], None]
Builder = Callable[[Progress], bytes]


class DiagnosticExportJob:
    def __init__(self) -> None:
        self._lock = Lock()
        self._state: dict[str, object] = {"status": "idle", "job_id": None}
        self._body: bytes | None = None

    def start(self, builder: Builder, filename: str) -> dict[str, object]:
        with self._lock:
            if self._state["status"] == "building":
                return dict(self._state)
            job_id = uuid4().hex
            self._body = None
            self._state = {
                "job_id": job_id, "status": "building", "completed": 0, "total": 0,
                "message": "Verzoek ontvangen; diagnose wordt voorbereid.",
                "filename": filename, "size_bytes": None, "error": None,
            }
            accepted = dict(self._state)
        worker = Thread(target=self._build, args=(job_id, builder),
                        name="diagnostic-export", daemon=True)
        try:
            worker.start()
        except RuntimeError:
            with self._lock:
                self._state.update(status="failed", error="Diagnose kon niet worden gestart.")
            return self.status()
        return accepted

    def _build(self, job_id: str, builder: Builder) -> None:
        def progress(completed: int, total: int, message: str) -> None:
            with self._lock:
                if self._state["job_id"] == job_id:
                    self._state.update(completed=max(0, completed), total=max(0, total),
                                       message=message)

        try:
            body = builder(progress)
            if not isinstance(body, bytes):
                raise TypeError("diagnostic builder must return bytes")
        except Exception:
            # Report worker failure to the polling browser rather than hanging forever.
            # Do not expose exception text containing local paths or source data.
            with self._lock:
                self._state.update(
                    status="failed", error="Diagnose maken is mislukt. Probeer opnieuw.",
                    message="Diagnose maken is mislukt.",
                )
            return
        with self._lock:
            self._body = body
            self._state.update(status="ready", size_bytes=len(body),
                               message="Diagnosebestand klaar om te downloaden.")

    def status(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state)

    def download(self, job_id: str) -> tuple[bytes, str] | None:
        with self._lock:
            if (self._state["status"] != "ready" or self._state["job_id"] != job_id
                    or self._body is None):
                return None
            return self._body, str(self._state["filename"])
