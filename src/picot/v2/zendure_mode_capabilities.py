"""Observer-only capability evidence for the Zendure HA mode selector."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from picot.domain.execution_primitive import ExecutionPrimitive

METHOD_VERSION: Final = "zendure-mode-capability-evidence:v2"

_MODE_DEFINITIONS: Final[
    dict[
        str,
        tuple[
            tuple[ExecutionPrimitive, ...],
            str | None,
            str,
            str,
            bool,
        ],
    ]
] = {
    "Standby": ((ExecutionPrimitive.STANDBY,), None, "none", "delegated", False),
    "Handmatig": (
        (ExecutionPrimitive.CHARGE_AT_POWER, ExecutionPrimitive.DISCHARGE_AT_POWER),
        "explicit_signed_power",
        "pv_and_grid",
        "explicit_power_required",
        True,
    ),
    "Nul op de meter": (
        (ExecutionPrimitive.BALANCE_BIDIRECTIONAL,),
        None,
        "surplus_only",
        "delegated",
        False,
    ),
    "Alleen slim ontladen": (
        (ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,),
        None,
        "none",
        "delegated",
        False,
    ),
    "Alleen slim opladen": (
        (ExecutionPrimitive.BALANCE_CHARGE_ONLY,),
        None,
        "surplus_only",
        "delegated",
        False,
    ),
    "Snel opladen": (
        (ExecutionPrimitive.CHARGE_AT_POWER,),
        "integration_configured_maximum",
        "pv_and_grid",
        "delegated",
        False,
    ),
    "Snel ontladen": (
        (ExecutionPrimitive.DISCHARGE_AT_POWER,),
        "integration_configured_maximum",
        "none",
        "delegated",
        False,
    ),
}

_DYNAMIC_MODES: Final = frozenset(
    {
        "Dynamisch NOM",
        "Dynamisch NOM (Duur)",
        "Dynamisch Handelen",
        "Dynamisch Handelen + NOM",
    }
)


@dataclass(frozen=True, slots=True)
class ZendureModeMapping:
    """Adapter-boundary mapping from one vendor mode to generic primitives."""

    vendor_mode: str
    primitives: tuple[ExecutionPrimitive, ...]
    power_semantics: str | None = None
    charge_source_semantics: str = "none"
    control_semantics: str = "delegated"
    requires_proven_power_limits: bool = False


@dataclass(frozen=True, slots=True)
class StorageModeCapabilityConfig:
    """Explicit HA binding and generic identity for storage-mode evidence."""

    source_entity_id: str
    capability_id: str
    execution_scope_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("source_entity_id", self.source_entity_id),
            ("capability_id", self.capability_id),
            ("execution_scope_id", self.execution_scope_id),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")


@dataclass(frozen=True, slots=True)
class ZendureModeCapabilityEvidence:
    """Read-only evidence derived from one Home Assistant entity payload."""

    captured_at: datetime
    source_entity_id: str
    capability_id: str
    execution_scope_id: str
    current_vendor_mode: str | None
    status: Literal["available", "unavailable"]
    unavailable_reason: str | None
    usable_vendor_modes: tuple[str, ...]
    excluded_dynamic_vendor_modes: tuple[str, ...]
    mappings: tuple[ZendureModeMapping, ...]
    method_version: str = METHOD_VERSION


class HomeAssistantZendureModeCapabilityReader:
    """Read the configured HA selector once and derive observer evidence."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def read(
        self,
        config: StorageModeCapabilityConfig,
        *,
        captured_at: datetime,
    ) -> ZendureModeCapabilityEvidence:
        _validate_identity(
            captured_at,
            config.source_entity_id,
            config.capability_id,
            config.execution_scope_id,
        )
        request = Request(
            "http://supervisor/core/api/states/"
            f"{quote(config.source_entity_id, safe='.')}",
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return _unavailable(
                captured_at=captured_at,
                source_entity_id=config.source_entity_id,
                capability_id=config.capability_id,
                execution_scope_id=config.execution_scope_id,
                current_mode=None,
                reason=type(exc).__name__,
            )
        if not isinstance(payload, Mapping):
            return _unavailable(
                captured_at=captured_at,
                source_entity_id=config.source_entity_id,
                capability_id=config.capability_id,
                execution_scope_id=config.execution_scope_id,
                current_mode=None,
                reason="mode_payload_invalid",
            )
        return derive_zendure_mode_capability_evidence(
            payload,
            captured_at=captured_at,
            source_entity_id=config.source_entity_id,
            capability_id=config.capability_id,
            execution_scope_id=config.execution_scope_id,
        )


def derive_zendure_mode_capability_evidence(
    payload: Mapping[str, object],
    *,
    captured_at: datetime,
    source_entity_id: str,
    capability_id: str,
    execution_scope_id: str,
) -> ZendureModeCapabilityEvidence:
    """Derive capability evidence without inventing unavailable selector options."""

    _validate_identity(captured_at, source_entity_id, capability_id, execution_scope_id)
    current_mode_value = payload.get("state")
    current_mode = current_mode_value if isinstance(current_mode_value, str) else None
    attributes = payload.get("attributes")
    options_value = attributes.get("options") if isinstance(attributes, Mapping) else None

    if options_value is None:
        return _unavailable(
            captured_at=captured_at,
            source_entity_id=source_entity_id,
            capability_id=capability_id,
            execution_scope_id=execution_scope_id,
            current_mode=current_mode,
            reason="mode_options_missing",
        )
    if not isinstance(options_value, (list, tuple)) or not all(
        isinstance(option, str) for option in options_value
    ):
        return _unavailable(
            captured_at=captured_at,
            source_entity_id=source_entity_id,
            capability_id=capability_id,
            execution_scope_id=execution_scope_id,
            current_mode=current_mode,
            reason="mode_options_invalid",
        )

    options = tuple(options_value)
    usable_modes = tuple(mode for mode in options if mode in _MODE_DEFINITIONS)
    dynamic_modes = tuple(mode for mode in options if mode in _DYNAMIC_MODES)
    mappings = tuple(
        ZendureModeMapping(
            vendor_mode=mode,
            primitives=_MODE_DEFINITIONS[mode][0],
            power_semantics=_MODE_DEFINITIONS[mode][1],
            charge_source_semantics=_MODE_DEFINITIONS[mode][2],
            control_semantics=_MODE_DEFINITIONS[mode][3],
            requires_proven_power_limits=_MODE_DEFINITIONS[mode][4],
        )
        for mode in usable_modes
    )
    return ZendureModeCapabilityEvidence(
        captured_at=captured_at,
        source_entity_id=source_entity_id,
        capability_id=capability_id,
        execution_scope_id=execution_scope_id,
        current_vendor_mode=current_mode,
        status="available",
        unavailable_reason=None,
        usable_vendor_modes=usable_modes,
        excluded_dynamic_vendor_modes=dynamic_modes,
        mappings=mappings,
    )


def _unavailable(
    *,
    captured_at: datetime,
    source_entity_id: str,
    capability_id: str,
    execution_scope_id: str,
    current_mode: str | None,
    reason: str,
) -> ZendureModeCapabilityEvidence:
    return ZendureModeCapabilityEvidence(
        captured_at=captured_at,
        source_entity_id=source_entity_id,
        capability_id=capability_id,
        execution_scope_id=execution_scope_id,
        current_vendor_mode=current_mode,
        status="unavailable",
        unavailable_reason=reason,
        usable_vendor_modes=(),
        excluded_dynamic_vendor_modes=(),
        mappings=(),
    )


def _validate_identity(
    captured_at: datetime,
    source_entity_id: str,
    capability_id: str,
    execution_scope_id: str,
) -> None:
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    for name, value in (
        ("source_entity_id", source_entity_id),
        ("capability_id", capability_id),
        ("execution_scope_id", execution_scope_id),
    ):
        if not value.strip():
            raise ValueError(f"{name} must not be blank")
