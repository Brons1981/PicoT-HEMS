"""Narrow live-control bridge for the first ADR-042 delegated storage modes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import HomeAssistantDispatchMode

DispatchFn = Callable[..., str]


@dataclass(slots=True)
class LiveModeControl:
    """Dispatch only NOM or Slim ontladen from an evaluated winning Candidate."""

    _last_requested_option: str | None = None

    @staticmethod
    def desired_from_winner(candidate_id: object) -> tuple[ExecutionPrimitive, str] | None:
        if not isinstance(candidate_id, str):
            return None
        if (
            ":flow-correction:preserve-storage" in candidate_id
            or ":delegated-control:nom" in candidate_id
        ):
            return ExecutionPrimitive.BALANCE_BIDIRECTIONAL, "Nul op de meter"
        if ":delegated-control:slim-discharge" in candidate_id:
            return ExecutionPrimitive.BALANCE_DISCHARGE_ONLY, "Alleen slim ontladen"
        return None

    def apply(
        self,
        event: dict[str, object],
        *,
        target_entity: str,
        mode: HomeAssistantDispatchMode,
        token: str,
        now: datetime,
        dispatch: DispatchFn,
    ) -> dict[str, object]:
        """Return execution evidence and perform at most one idempotent mode request."""

        candidate_id = event.get("adr037_winning_candidate_id")
        desired = self.desired_from_winner(candidate_id)
        current = event.get("zendure_requested_mode")
        if desired is None:
            return {
                "adr037_control_status": "no_executable_winner",
                "adr037_control_requested_option": None,
                "adr037_control_dispatch_status": "not_attempted",
                "control_change_allowed": False,
                "observer_only": mode is HomeAssistantDispatchMode.DRY_RUN,
            }

        primitive, desired_option = desired
        if current == desired_option:
            self._last_requested_option = desired_option
            return {
                "adr037_control_status": "already_active",
                "adr037_control_requested_option": desired_option,
                "adr037_control_dispatch_status": "skipped_already_active",
                "control_change_allowed": mode is HomeAssistantDispatchMode.LIVE,
                "observer_only": mode is HomeAssistantDispatchMode.DRY_RUN,
            }

        if self._last_requested_option == desired_option:
            return {
                "adr037_control_status": "awaiting_mode_feedback",
                "adr037_control_requested_option": desired_option,
                "adr037_control_dispatch_status": "skipped_duplicate_request",
                "control_change_allowed": mode is HomeAssistantDispatchMode.LIVE,
                "observer_only": mode is HomeAssistantDispatchMode.DRY_RUN,
            }

        status = dispatch(
            primitive=primitive,
            desired_option=desired_option,
            target_entity=target_entity,
            mode=mode,
            token=token,
            now=now,
        )
        if status in {"dispatched", "dry_run_only"}:
            self._last_requested_option = desired_option
        return {
            "adr037_control_status": "requested",
            "adr037_control_requested_option": desired_option,
            "adr037_control_dispatch_status": status,
            "control_change_allowed": mode is HomeAssistantDispatchMode.LIVE,
            "observer_only": mode is HomeAssistantDispatchMode.DRY_RUN,
        }
