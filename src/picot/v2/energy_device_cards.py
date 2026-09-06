"""Optional neutral Energy Devices catalog and observer-only placements.

This module is deliberately outside PlanningInputSnapshot assembly. Catalog
availability and user placements cannot alter a Planner Run in V2ADR-064's
observer-only first slice.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SUPPORTED_CATALOG_SCHEMA_VERSION = 1
PLACEMENT_SCHEMA_VERSION = 1
PLACEMENT_METHOD_VERSION = "observer-energy-device-placement:v1"


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric or null")
    numeric = float(value)
    if numeric < 0.0:
        raise ValueError(f"{label} must not be negative")
    return numeric


@dataclass(frozen=True, slots=True)
class EnergyDeviceCard:
    card_id: str
    device_id: str
    name: str
    availability: str
    active: bool
    current_power_w: float | None
    expected_power_w: float | None
    expected_duration_seconds: float | None
    expected_energy_wh: float | None
    confidence: float
    completed_session_count: int
    profile_status: str
    profile_revision: int
    last_observed_at: str | None
    method_version: str

    @classmethod
    def from_payload(cls, payload: object) -> EnergyDeviceCard:
        if not isinstance(payload, dict):
            raise ValueError("energy-device card must be an object")
        strings = {
            key: payload.get(key)
            for key in (
                "card_id",
                "device_id",
                "name",
                "availability",
                "profile_status",
                "method_version",
            )
        }
        if any(not isinstance(value, str) or not value.strip() for value in strings.values()):
            raise ValueError("energy-device card requires stable text fields")
        active = payload.get("active")
        if not isinstance(active, bool):
            raise ValueError("energy-device active state must be boolean")
        confidence = _optional_number(payload.get("confidence"), "confidence")
        if confidence is None or confidence > 1.0:
            raise ValueError("confidence must be between zero and one")
        completed = payload.get("completed_session_count")
        revision = payload.get("profile_revision")
        if isinstance(completed, bool) or not isinstance(completed, int) or completed < 0:
            raise ValueError("completed-session count must be a non-negative integer")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("profile revision must be a non-negative integer")
        observed = payload.get("last_observed_at")
        if observed is not None and not isinstance(observed, str):
            raise ValueError("last observation must be text or null")
        return cls(
            card_id=str(strings["card_id"]),
            device_id=str(strings["device_id"]),
            name=str(strings["name"]),
            availability=str(strings["availability"]),
            active=active,
            current_power_w=_optional_number(payload.get("current_power_w"), "current power"),
            expected_power_w=_optional_number(
                payload.get("expected_power_w"), "expected power"
            ),
            expected_duration_seconds=_optional_number(
                payload.get("expected_duration_seconds"), "expected duration"
            ),
            expected_energy_wh=_optional_number(
                payload.get("expected_energy_wh"), "expected energy"
            ),
            confidence=confidence,
            completed_session_count=completed,
            profile_status=str(strings["profile_status"]),
            profile_revision=revision,
            last_observed_at=observed,
            method_version=str(strings["method_version"]),
        )

    def as_public_dict(self) -> dict[str, object]:
        return {
            "card_id": self.card_id,
            "device_id": self.device_id,
            "name": self.name,
            "availability": self.availability,
            "active": self.active,
            "current_power_w": self.current_power_w,
            "expected_power_w": self.expected_power_w,
            "expected_duration_seconds": self.expected_duration_seconds,
            "expected_energy_wh": self.expected_energy_wh,
            "confidence": self.confidence,
            "completed_session_count": self.completed_session_count,
            "profile_status": self.profile_status,
            "profile_revision": self.profile_revision,
            "last_observed_at": self.last_observed_at,
            "method_version": self.method_version,
        }


@dataclass(frozen=True, slots=True)
class EnergyDeviceCatalog:
    status: str
    source_entity_id: str
    revision: int | None
    generated_at: str | None
    cards: tuple[EnergyDeviceCard, ...]
    error: str | None = None

    def as_public_dict(self) -> dict[str, object]:
        return {
            "schema_version": SUPPORTED_CATALOG_SCHEMA_VERSION,
            "status": self.status,
            "source_entity_id": self.source_entity_id,
            "revision": self.revision,
            "generated_at": self.generated_at,
            "observer_only": True,
            "planning_authority": False,
            "card_count": len(self.cards),
            "cards": [card.as_public_dict() for card in self.cards],
            "error": self.error,
        }


class HomeAssistantEnergyDeviceCatalogReader:
    """Read one optional external catalog without entering snapshot assembly."""

    def __init__(self, token: str, entity_id: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        if not entity_id.startswith("sensor."):
            raise ValueError("energy-device catalog entity must be a sensor")
        self._token = token
        self._entity_id = entity_id

    def unavailable(self, error: str) -> EnergyDeviceCatalog:
        return EnergyDeviceCatalog(
            status="unavailable",
            source_entity_id=self._entity_id,
            revision=None,
            generated_at=None,
            cards=(),
            error=error[:240],
        )

    def read(self) -> EnergyDeviceCatalog:
        request = Request(
            "http://supervisor/core/api/states/" + quote(self._entity_id, safe="."),
            headers={"Authorization": f"Bearer {self._token}"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
            if not isinstance(payload, dict):
                raise ValueError("catalog state must be an object")
            attributes = payload.get("attributes")
            if not isinstance(attributes, dict):
                raise ValueError("catalog attributes must be an object")
            if attributes.get("schema_version") != SUPPORTED_CATALOG_SCHEMA_VERSION:
                raise ValueError("unsupported catalog schema")
            if attributes.get("producer") != "picot-energy-devices":
                raise ValueError("unexpected catalog producer")
            if attributes.get("observer_only") is not True:
                raise ValueError("catalog must be observer-only")
            if attributes.get("planning_authority") is not False:
                raise ValueError("catalog must not claim planning authority")
            raw_cards = attributes.get("cards")
            if not isinstance(raw_cards, list) or len(raw_cards) > 100:
                raise ValueError("catalog cards must be a bounded list")
            cards = tuple(EnergyDeviceCard.from_payload(item) for item in raw_cards)
            if len({card.card_id for card in cards}) != len(cards):
                raise ValueError("catalog card IDs must be unique")
            revision = attributes.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ValueError("catalog revision must be a positive integer")
            generated_at = attributes.get("generated_at")
            if not isinstance(generated_at, str) or not generated_at:
                raise ValueError("catalog generation time must be explicit")
            return EnergyDeviceCatalog(
                status="available",
                source_entity_id=self._entity_id,
                revision=revision,
                generated_at=generated_at,
                cards=cards,
            )
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            return self.unavailable(str(error))


@dataclass(frozen=True, slots=True)
class EnergyDevicePlacement:
    placement_id: str
    card_id: str
    name: str
    starts_at: datetime
    ends_at: datetime
    created_at: datetime
    source: str = "picot_timeline_user"

    def __post_init__(self) -> None:
        for value in (self.starts_at, self.ends_at, self.created_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("placement times must be timezone-aware")
        if self.ends_at <= self.starts_at:
            raise ValueError("placement end must be after its start")
        if not self.card_id.strip() or not self.name.strip():
            raise ValueError("placement card and name must be explicit")

    def as_public_dict(self) -> dict[str, object]:
        return {
            "placement_id": self.placement_id,
            "card_id": self.card_id,
            "name": self.name,
            "starts_at": self.starts_at.isoformat(),
            "ends_at": self.ends_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "source": self.source,
            "observer_only": True,
            "planning_authority": False,
        }


class EnergyDevicePlacementStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()
        self._placements = self._load()

    def _load(self) -> tuple[EnergyDevicePlacement, ...]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ()
        if not isinstance(raw, dict) or raw.get("schema_version") != PLACEMENT_SCHEMA_VERSION:
            raise ValueError("unsupported energy-device placement document")
        placements = raw.get("placements")
        if not isinstance(placements, list):
            raise ValueError("placement document requires a list")
        return tuple(
            EnergyDevicePlacement(
                placement_id=str(item["placement_id"]),
                card_id=str(item["card_id"]),
                name=str(item["name"]),
                starts_at=datetime.fromisoformat(str(item["starts_at"])),
                ends_at=datetime.fromisoformat(str(item["ends_at"])),
                created_at=datetime.fromisoformat(str(item["created_at"])),
                source=str(item.get("source", "picot_timeline_user")),
            )
            for item in placements
            if isinstance(item, dict)
        )

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": PLACEMENT_SCHEMA_VERSION,
                    "method_version": PLACEMENT_METHOD_VERSION,
                    "observer_only": True,
                    "planning_authority": False,
                    "placements": [item.as_public_dict() for item in self._placements],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self._path)

    def public_view(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema_version": PLACEMENT_SCHEMA_VERSION,
                "method_version": PLACEMENT_METHOD_VERSION,
                "observer_only": True,
                "planning_authority": False,
                "placements": [item.as_public_dict() for item in self._placements],
            }

    def update(
        self,
        payload: dict[str, object],
        *,
        available_cards: Iterable[EnergyDeviceCard],
        now: datetime | None = None,
    ) -> dict[str, object]:
        cards = {card.card_id: card for card in available_cards}
        action = payload.get("action")
        with self._lock:
            if action == "add":
                card_id = payload.get("card_id")
                if not isinstance(card_id, str) or card_id not in cards:
                    raise ValueError("select a currently available device card")
                starts_at = datetime.fromisoformat(str(payload.get("starts_at")))
                ends_at = datetime.fromisoformat(str(payload.get("ends_at")))
                created_at = now or datetime.now(UTC)
                seed = "|".join(
                    (
                        card_id,
                        starts_at.isoformat(),
                        ends_at.isoformat(),
                        created_at.isoformat(),
                    )
                )
                placement = EnergyDevicePlacement(
                    placement_id=f"energy-device-placement-{sha256(seed.encode()).hexdigest()[:16]}",
                    card_id=card_id,
                    name=cards[card_id].name,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    created_at=created_at,
                )
                self._placements = (*self._placements, placement)
            elif action == "remove":
                placement_id = payload.get("placement_id")
                if not isinstance(placement_id, str) or not placement_id:
                    raise ValueError("placement ID is required")
                retained = tuple(
                    item for item in self._placements if item.placement_id != placement_id
                )
                if len(retained) == len(self._placements):
                    raise ValueError("unknown placement")
                self._placements = retained
            else:
                raise ValueError("unknown placement action")
            self._write()
            return self.public_view_unlocked()

    def public_view_unlocked(self) -> dict[str, object]:
        return {
            "schema_version": PLACEMENT_SCHEMA_VERSION,
            "method_version": PLACEMENT_METHOD_VERSION,
            "observer_only": True,
            "planning_authority": False,
            "placements": [item.as_public_dict() for item in self._placements],
        }
