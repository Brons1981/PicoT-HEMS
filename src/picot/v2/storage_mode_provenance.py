"""Immutable storage-mode ownership and manual-override provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

StorageModeProvenanceStatus = Literal[
    "unverified",
    "planner_owned",
    "manual_override",
    "released",
]


@dataclass(frozen=True, slots=True)
class StorageModeControlProvenance:
    status: StorageModeProvenanceStatus
    observed_vendor_mode: str
    observed_at: datetime
    last_planner_vendor_mode: str | None
    last_planner_application_id: str | None
    last_planner_applied_at: datetime | None
    manual_override_active: bool
    transition_reason: str
    reset_id: str | None = None

    def __post_init__(self) -> None:
        if not self.observed_vendor_mode.strip():
            raise ValueError("observed_vendor_mode must be explicit")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.transition_reason.strip():
            raise ValueError("transition_reason must be explicit")
        if self.last_planner_applied_at is not None and (
            self.last_planner_applied_at.tzinfo is None
            or self.last_planner_applied_at.utcoffset() is None
        ):
            raise ValueError("last_planner_applied_at must be timezone-aware")
        if self.status == "manual_override" and not self.manual_override_active:
            raise ValueError("manual_override status must activate the override")
        if self.status != "manual_override" and self.manual_override_active:
            raise ValueError("only manual_override status may activate the override")


def initial_storage_mode_provenance(
    *,
    observed_vendor_mode: str,
    observed_at: datetime,
) -> StorageModeControlProvenance:
    return StorageModeControlProvenance(
        status="unverified",
        observed_vendor_mode=observed_vendor_mode,
        observed_at=observed_at,
        last_planner_vendor_mode=None,
        last_planner_application_id=None,
        last_planner_applied_at=None,
        manual_override_active=False,
        transition_reason="no_planner_application_recorded",
    )


def record_planner_mode_application(
    previous: StorageModeControlProvenance,
    *,
    vendor_mode: str,
    applied_at: datetime,
    application_id: str,
) -> StorageModeControlProvenance:
    if previous.manual_override_active:
        raise ValueError(
            "manual override must be cleared through explicit reset"
        )
    if not vendor_mode.strip():
        raise ValueError("vendor_mode must be explicit")
    if not application_id.strip():
        raise ValueError("application_id must be explicit")
    if applied_at.tzinfo is None or applied_at.utcoffset() is None:
        raise ValueError("applied_at must be timezone-aware")
    return StorageModeControlProvenance(
        status="planner_owned",
        observed_vendor_mode=previous.observed_vendor_mode,
        observed_at=previous.observed_at,
        last_planner_vendor_mode=vendor_mode,
        last_planner_application_id=application_id,
        last_planner_applied_at=applied_at,
        manual_override_active=False,
        transition_reason="planner_application_recorded",
    )


def observe_storage_mode(
    previous: StorageModeControlProvenance,
    *,
    observed_vendor_mode: str,
    observed_at: datetime,
) -> StorageModeControlProvenance:
    if previous.status == "manual_override":
        status: StorageModeProvenanceStatus = "manual_override"
        manual_override_active = True
        reason = previous.transition_reason
    elif (
        previous.status == "planner_owned"
        and previous.last_planner_vendor_mode == observed_vendor_mode
    ):
        status = "planner_owned"
        manual_override_active = False
        reason = "observed_mode_matches_planner_mode"
    elif previous.status == "planner_owned":
        status = "manual_override"
        manual_override_active = True
        reason = "observed_mode_differs_from_planner_mode"
    elif (
        previous.status == "released"
        and previous.observed_vendor_mode == observed_vendor_mode
    ):
        status = "released"
        manual_override_active = False
        reason = previous.transition_reason
    elif previous.status == "released":
        status = "manual_override"
        manual_override_active = True
        reason = "observed_mode_changed_after_explicit_reset"
    else:
        status = previous.status
        manual_override_active = False
        reason = previous.transition_reason
    return StorageModeControlProvenance(
        status=status,
        observed_vendor_mode=observed_vendor_mode,
        observed_at=observed_at,
        last_planner_vendor_mode=previous.last_planner_vendor_mode,
        last_planner_application_id=previous.last_planner_application_id,
        last_planner_applied_at=previous.last_planner_applied_at,
        manual_override_active=manual_override_active,
        transition_reason=reason,
        reset_id=previous.reset_id,
    )


def reset_storage_mode_override(
    previous: StorageModeControlProvenance,
    *,
    observed_vendor_mode: str,
    reset_at: datetime,
    reset_id: str,
) -> StorageModeControlProvenance:
    if not reset_id.strip():
        raise ValueError("reset_id must be explicit")
    if reset_at.tzinfo is None or reset_at.utcoffset() is None:
        raise ValueError("reset_at must be timezone-aware")
    return StorageModeControlProvenance(
        status="released",
        observed_vendor_mode=observed_vendor_mode,
        observed_at=reset_at,
        last_planner_vendor_mode=previous.last_planner_vendor_mode,
        last_planner_application_id=previous.last_planner_application_id,
        last_planner_applied_at=previous.last_planner_applied_at,
        manual_override_active=False,
        transition_reason="explicit_user_reset",
        reset_id=reset_id,
    )
