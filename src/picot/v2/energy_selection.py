"""Validate HC's acknowledgement against the advisor's own current answer."""

from datetime import datetime
from typing import Any

from picot.v2.energy_portfolio import fingerprint, instant

ENTITY = "sensor.picot_hc_energy_selection"
PERMIT_ENTITY = "sensor.picot_hems_hc_start_permit"


def start_permit(selection: dict[str, Any] | None) -> dict[str, Any]:
    """A short-lived permission to initiate the exact confirmed energy profile.

    It is not a reservation or permission to stop an already running load.
    Only call with the result of validate_selection against our own answer.
    """
    if selection is None:
        return dict(state="withdrawn", attributes=dict(execution_authorized=False))
    return dict(
        state="permitted",
        attributes=dict(selection, contract="hc-energy-start-permit:v1", execution_authorized=True),
    )


def validate_selection(
    value: dict[str, Any] | None,
    request: dict[str, Any],
    answer: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any] | None:
    try:
        keys = {
            "contract",
            "request_id",
            "revision",
            "basis_snapshot_id",
            "replacement_basis_id",
            "request_fingerprint",
            "selected_plan_id",
            "generated_at",
            "valid_until",
            "execution_authorized",
        }
        if (
            not isinstance(value, dict)
            or set(value) != keys
            or not answer
            or value["contract"] != "hc-energy-selection:v1"
            or value["execution_authorized"] is not False
            or answer["execution_authorized"] is not False
            or answer["status"] != "selected"
            or value["request_fingerprint"] != fingerprint(request)
            or answer["request_fingerprint"] != value["request_fingerprint"]
            or value["selected_plan_id"] != answer["selected_plan_id"]
            or any(
                value[k] != request.get(k) or value[k] != answer.get(k)
                for k in ("request_id", "revision", "basis_snapshot_id", "replacement_basis_id")
            )
            or not instant(request["generated_at"])
            <= instant(value["generated_at"])
            <= now
            < instant(value["valid_until"])
            <= min(instant(request["valid_until"]), instant(answer["valid_until"]))
        ):
            return None
        return dict(value)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return None
