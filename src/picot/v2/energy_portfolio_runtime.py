"""Bounded proposal assessment on recently published outlook snapshots."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.accepted_loads import EXECUTION_ENTITY, RESERVATION_ENTITY, AcceptedLoads
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY, assess, fingerprint, instant
from picot.v2.energy_selection import ENTITY as SELECTION_ENTITY
from picot.v2.energy_selection import PERMIT_ENTITY, start_permit, validate_selection
from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.load_replacement import LoadReplacementBasis
from picot.v2.projection import Card


class PortfolioAdvisor:
    def __init__(
        self,
        read: Callable[[], dict[str, Any] | None],
        publish: Callable[[dict[str, Any]], None],
        configuration: Callable[[PlanningInputSnapshot], StorageConversionModel],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        read_selection: Callable[[], dict[str, Any] | None] = lambda: None,
        publish_permit: Callable[[dict[str, Any]], None] = lambda value: None,
        accepted_loads: AcceptedLoads | None = None,
        read_execution: Callable[[], dict[str, Any] | None] = lambda: None,
        read_reservation: Callable[[], dict[str, Any] | None] = lambda: None,
    ) -> None:
        self.read, self.publish, self.configuration, self.now = read, publish, configuration, now
        self.bases: dict[str, PlanningInputSnapshot] = {}
        self.replacement_bases: dict[str, LoadReplacementBasis] = {}
        self.last_fingerprint: str | None = None
        self.read_selection = read_selection
        self.publish_permit = publish_permit
        self.accepted_loads, self.read_execution = accepted_loads, read_execution
        self.read_reservation = read_reservation
        self.last_answer: dict[str, Any] | None = None
        self.confirmed_selection: dict[str, Any] | None = None

    def confirm_selection(self, request: dict[str, Any]) -> None:
        self.confirmed_selection = None
        try:
            value = validate_selection(self.read_selection(), request, self.last_answer, self.now())
            if (
                value is not None
                and self.last_answer is not None
                and self.read() == request
                and validate_selection(value, request, self.last_answer, self.now()) is not None
            ):
                if self.accepted_loads is not None:
                    self.accepted_loads.issue(
                        request,
                        value,
                        (
                            self.replacement_bases.get(request["basis_snapshot_id"])
                            if isinstance(request.get("basis_snapshot_id"), str)
                            else None
                        ),
                        self.now(),
                        reservation_only=bool(self.last_answer.get("requires_route_commitment")),
                        terminal_requirement=self.last_answer.get("terminal_requirement"),
                    )
                    if (
                        self.read() != request
                        or validate_selection(value, request, self.last_answer, self.now()) is None
                    ):
                        value = None
                if self.last_answer.get("requires_route_commitment"):
                    value = None  # Reservation may feed planning; no hypothetical start permission.
                self.confirmed_selection = value
        except Exception:
            pass  # A failed advisory acknowledgement cannot affect energy planning.
        self.publish_permit(start_permit(self.confirmed_selection))

    def poll_selection(self) -> None:
        self.observe_execution()
        self.confirmed_selection = None
        request = self.read()
        if isinstance(request, dict) and fingerprint(request) == self.last_fingerprint:
            self.confirm_selection(request)
        else:
            self.publish_permit(start_permit(None))

    def observe_execution(self) -> None:
        if self.accepted_loads is not None:
            try:
                self.accepted_loads.observe(self.read_execution(), self.now())
                self.accepted_loads.reserve(self.read_reservation(), self.now())
            except Exception as error:
                print(
                    json.dumps(
                        dict(event="accepted_load_receipt_failed", error=type(error).__name__)
                    ),
                    flush=True,
                )

    def refresh(
        self, snapshot: PlanningInputSnapshot, replacement_basis: LoadReplacementBasis | None = None
    ) -> None:
        # Called exclusively by the outlook worker, after successful publication.
        now = self.now()
        self.observe_execution()
        self.confirmed_selection = None
        self.publish_permit(start_permit(None))
        self.bases = {
            key: value
            for key, value in self.bases.items()
            if 0 <= (now - value.captured_at).total_seconds() <= 120
        }
        if not 0 <= (now - snapshot.captured_at).total_seconds() <= 120:
            return
        self.bases[snapshot.snapshot_id] = snapshot
        self.bases = dict(list(self.bases.items())[-2:])
        self.replacement_bases = {
            key: value for key, value in self.replacement_bases.items() if key in self.bases
        }
        self.replacement_bases.pop(snapshot.snapshot_id, None)
        if replacement_basis is not None and replacement_basis.matches(snapshot):
            self.replacement_bases[snapshot.snapshot_id] = replacement_basis
        request = self.read()
        if not isinstance(request, dict):
            return
        digest = fingerprint(request)
        if digest == self.last_fingerprint:
            self.confirm_selection(request)
            return
        if not instant(request["generated_at"]) <= now < instant(request["valid_until"]):
            return
        basis = (
            self.bases.get(request["basis_snapshot_id"])
            if isinstance(request.get("basis_snapshot_id"), str)
            else None
        )
        answer: dict[str, Any]
        if basis is None:
            answer = dict(
                contract="hc-energy-assessment:v1",
                status="blocked",
                request_id=request.get("request_id"),
                revision=request.get("revision"),
                request_fingerprint=digest,
                basis_snapshot_id=request.get("basis_snapshot_id"),
                valid_until=(now + timedelta(seconds=60)).isoformat(),
                execution_authorized=False,
                reason="refresh_outlook_and_resubmit",
                selected_plan_id=None,
                assessments=[],
            )
        else:
            replacement = self.replacement_bases.get(basis.snapshot_id)
            answer = assess(
                basis,
                request,
                self.configuration(basis),
                replacement_basis=replacement,
                terminal_requirement=(
                    self.accepted_loads.terminal_requirement(replacement.source_id, now)
                    if self.accepted_loads is not None and replacement is not None
                    else None
                ),
            )
            answer["valid_until"] = min(
                instant(request["valid_until"]), basis.captured_at + timedelta(seconds=120)
            ).isoformat()
        if basis is None and request.get("contract") == "hc-energy-proposals:v2":
            answer.update(
                replacement_basis_id=request.get("replacement_basis_id"),
                scope="replacement_demand_on_retained_route",
            )
        # Do not publish a result for replaced/cancelled proposals or expired data.
        current = self.read()
        if current != request or not instant(request["generated_at"]) <= self.now() < instant(
            answer["valid_until"]
        ):
            return
        self.publish(answer)
        self.last_fingerprint = digest
        self.last_answer = answer
        self.confirm_selection(request)


def home_assistant_portfolio(
    token: str,
    configuration: Callable[[PlanningInputSnapshot], StorageConversionModel],
    accepted_loads: AcceptedLoads | None = None,
) -> PortfolioAdvisor:
    def read_entity(entity: str, state: str | tuple[str, ...]) -> dict[str, Any] | None:
        request = Request(
            "http://supervisor/core/api/states/" + entity,
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                value = json.loads(response.read(16001))
        except HTTPError as error:
            if error.code == 404:
                return None  # HC has not published proposals yet.
            raise
        allowed = (state,) if isinstance(state, str) else state
        if not isinstance(value, dict) or value.get("state") not in allowed:
            return None
        attributes = value.get("attributes")
        if (
            entity in (EXECUTION_ENTITY, RESERVATION_ENTITY)
            and isinstance(attributes, dict)
            and attributes.get("status") != value["state"]
        ):
            return None
        return attributes if isinstance(attributes, dict) else None

    sink = HomeAssistantProjectionSink(token)
    return PortfolioAdvisor(
        lambda: read_entity(REQUEST_ENTITY, "requested"),
        lambda value: sink.publish(Card(RESPONSE_ENTITY, value["status"], value)),
        configuration,
        read_selection=lambda: read_entity(SELECTION_ENTITY, "confirmed"),
        accepted_loads=accepted_loads,
        read_execution=lambda: read_entity(EXECUTION_ENTITY, ("running", "finished")),
        read_reservation=lambda: read_entity(RESERVATION_ENTITY, ("reserved", "cancelled")),
        publish_permit=lambda value: sink.publish(
            Card(PERMIT_ENTITY, value["state"], value["attributes"])
        ),
    )
