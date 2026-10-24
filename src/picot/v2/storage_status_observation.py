"""Small, read-only HA mode observations independent of planning latency."""
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Thread

from picot.v2.zendure_mode_capabilities import (
    HomeAssistantZendureModeCapabilityReader,
    StorageModeCapabilityConfig,
    ZendureModeCapabilityEvidence,
)


def observe_storage_status(
    *, read: Callable[[], ZendureModeCapabilityEvidence],
    publish: Callable[[dict[str, object]], None],
    source_entity_id: str,
) -> None:
    """Never dispatch, claim a command succeeded, or feed back into planning."""
    started = datetime.now(UTC)
    try:
        evidence = read()
        available = (evidence.status == "available" and evidence.current_vendor_mode
                     not in (None, "unknown", "unavailable", ""))
        status: dict[str, object] = {
            "active_mode": evidence.current_vendor_mode if available else None,
            "observed_at": evidence.captured_at.isoformat(),
            "mode_changed_at": (evidence.state_changed_at.isoformat()
                                if evidence.state_changed_at is not None else None),
            "availability": "available" if available else "unavailable",
            "source_entity_id": evidence.source_entity_id,
            "error": evidence.unavailable_reason,
        }
    except Exception as exc:
        # An optional display observer must recover from a malformed HA response.
        status = {"active_mode": None, "observed_at": started.isoformat(),
                  "mode_changed_at": None, "availability": "unavailable",
                  "source_entity_id": source_entity_id, "error": type(exc).__name__}
    publish(status)


def start_storage_status_observer(
    *, token: str, config: StorageModeCapabilityConfig,
    publish: Callable[[dict[str, object]], None],
) -> Thread:
    reader = HomeAssistantZendureModeCapabilityReader(token)
    delay = Event()

    def observe() -> None:
        while True:
            observe_storage_status(
                read=lambda: reader.read(config, captured_at=datetime.now(UTC)),
                publish=publish, source_entity_id=config.source_entity_id,
            )
            delay.wait(10.0)

    thread = Thread(target=observe, name="picot-v2-storage-status", daemon=True)
    thread.start()
    return thread
