"""Observer-only physical meaning for delegated balancing primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from picot.domain.execution_primitive import ExecutionPrimitive


class DelegatedEnergyIntentKind(StrEnum):
    PV_SURPLUS_ACQUISITION = "pv_surplus_acquisition"
    PV_SURPLUS_WITH_HOUSEHOLD_SUPPORT = "pv_surplus_with_household_support"
    GRID_REQUIREMENT_ACQUISITION = "grid_requirement_acquisition"


@dataclass(frozen=True, slots=True)
class DelegatedEnergyIntent:
    """Versioned energy-flow permission derived without inventing power."""

    segment_id: str
    primitive: ExecutionPrimitive
    kind: DelegatedEnergyIntentKind
    minimum_storage_energy_wh: float | None
    maximum_storage_energy_wh: float
    evidence_ids: tuple[str, ...]
    method_version: str
    storage_requirement_id: str | None = None
    maximum_grid_input_energy_wh: float = 0.0
    maximum_charge_input_power_w: float | None = None

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("Delegated intent Segment ID must not be empty.")
        if self.primitive not in {
            ExecutionPrimitive.BALANCE_CHARGE_ONLY,
            ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        }:
            raise ValueError("Delegated intent requires a balancing primitive.")
        permitted_kinds = (
            {DelegatedEnergyIntentKind.PV_SURPLUS_WITH_HOUSEHOLD_SUPPORT}
            if self.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            else {
                DelegatedEnergyIntentKind.PV_SURPLUS_ACQUISITION,
                DelegatedEnergyIntentKind.GRID_REQUIREMENT_ACQUISITION,
            }
        )
        if self.kind not in permitted_kinds:
            raise ValueError("Delegated intent kind must match its primitive.")
        if self.maximum_storage_energy_wh <= 0.0:
            raise ValueError("Maximum storage energy must be positive.")
        if self.minimum_storage_energy_wh is not None and not (
            0.0 <= self.minimum_storage_energy_wh <= self.maximum_storage_energy_wh
        ):
            raise ValueError("Minimum storage energy must remain within its maximum.")
        if (
            self.kind
            is DelegatedEnergyIntentKind.PV_SURPLUS_WITH_HOUSEHOLD_SUPPORT
            and self.minimum_storage_energy_wh is None
        ):
            raise ValueError("Household support requires explicit minimum storage energy.")
        if self.kind is DelegatedEnergyIntentKind.GRID_REQUIREMENT_ACQUISITION:
            if self.storage_requirement_id is None or not self.storage_requirement_id.strip():
                raise ValueError("Grid acquisition requires a named storage requirement.")
            if self.maximum_grid_input_energy_wh <= 0.0:
                raise ValueError("Grid acquisition requires a positive grid-energy budget.")
            if (
                self.maximum_charge_input_power_w is None
                or self.maximum_charge_input_power_w <= 0.0
            ):
                raise ValueError("Grid acquisition requires proven maximum charge power.")
        elif (
            self.storage_requirement_id is not None
            or self.maximum_grid_input_energy_wh != 0.0
            or self.maximum_charge_input_power_w is not None
        ):
            raise ValueError("PV delegated intents may not carry grid-acquisition bounds.")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("Delegated intent evidence must be explicit.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Delegated intent evidence IDs must be unique.")
        if not self.method_version.strip():
            raise ValueError("Delegated intent method version must be explicit.")
