"""Observer-only capability evidence for the Zendure HA mode selector."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from picot.domain.execution_primitive import ExecutionPrimitive

METHOD_VERSION: Final = "zendure-mode-capability-evidence:v1"

_MODE_DEFINITIONS: Final[dict[str, tuple[tuple[ExecutionPrimitive, ...], str | None]]] = {
    "Standby": ((ExecutionPrimitive.STANDBY,), None),
    "Handmatig": (
        (ExecutionPrimitive.CHARGE_AT_POWER, ExecutionPrimitive.DISCHARGE_AT_POWER),
        "explicit_signed_power",
    ),
    "Nul op de meter": ((ExecutionPrimitive.BALANCE_BIDIRECTIONAL,), None),
    "Alleen slim ontladen": ((ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,), None),
    "Alleen slim opladen": ((ExecutionPrimitive.BALANCE_CHARGE_ONLY,), None),
    "Snel opladen": (
        (ExecutionPrimitive.CHARGE_AT_POWER,),
        "integration_configured_maximum",
    ),
    "Snel ontladen": (
        (ExecutionPrimitive.DISCHARGE_AT_POWER,),
        "integration_configured_maximum",
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
