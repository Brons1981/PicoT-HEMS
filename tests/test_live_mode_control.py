from __future__ import annotations

from datetime import UTC, datetime

from picot.addon.live_mode_control import LiveModeControl
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import HomeAssistantDispatchMode

NOW = datetime(2026, 8, 12, 20, 0, tzinfo=UTC)


def test_flow_correction_maps_to_nom() -> None:
    desired = LiveModeControl.desired_from_winner(
        "candidate:snapshot:flow-correction:preserve-storage"
    )
    assert desired == (
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        "Nul op de meter",
    )


def test_delegated_discharge_candidate_maps_to_slim_discharge() -> None:
    desired = LiveModeControl.desired_from_winner(
        "candidate:snapshot:delegated-control:slim-discharge"
    )
    assert desired == (
        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
        "Alleen slim ontladen",
    )


def test_dry_run_never_grants_control_authority() -> None:
    calls: list[dict[str, object]] = []

    def dispatch(**kwargs: object) -> str:
        calls.append(kwargs)
        return "dry_run_only"

    result = LiveModeControl().apply(
        {
            "adr037_winning_candidate_id": (
                "candidate:snapshot:delegated-control:slim-discharge"
            ),
            "zendure_requested_mode": "Nul op de meter",
        },
        target_entity="input_select.zendure_2400_ac_modus_selecteren",
        mode=HomeAssistantDispatchMode.DRY_RUN,
        token="token",
        now=NOW,
        dispatch=dispatch,
    )

    assert len(calls) == 1
    assert result["adr037_control_dispatch_status"] == "dry_run_only"
    assert result["control_change_allowed"] is False
    assert result["observer_only"] is True


def test_live_dispatch_is_idempotent_while_feedback_is_pending() -> None:
    calls: list[dict[str, object]] = []

    def dispatch(**kwargs: object) -> str:
        calls.append(kwargs)
        return "dispatched"

    control = LiveModeControl()
    event = {
        "adr037_winning_candidate_id": "candidate:snapshot:delegated-control:nom",
        "zendure_requested_mode": "Alleen slim ontladen",
    }
    first = control.apply(
        event,
        target_entity="input_select.zendure_2400_ac_modus_selecteren",
        mode=HomeAssistantDispatchMode.LIVE,
        token="token",
        now=NOW,
        dispatch=dispatch,
    )
    second = control.apply(
        event,
        target_entity="input_select.zendure_2400_ac_modus_selecteren",
        mode=HomeAssistantDispatchMode.LIVE,
        token="token",
        now=NOW,
        dispatch=dispatch,
    )

    assert len(calls) == 1
    assert first["adr037_control_dispatch_status"] == "dispatched"
    assert second["adr037_control_status"] == "awaiting_mode_feedback"
    assert second["adr037_control_dispatch_status"] == "skipped_duplicate_request"
