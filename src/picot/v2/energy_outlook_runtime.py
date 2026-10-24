"""Bounded background publication, independent of heating demand and control."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Any

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.accepted_loads import AcceptedLoads
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.energy_outlook import ENTITY, outlook
from picot.v2.energy_portfolio import instant
from picot.v2.energy_portfolio_runtime import PortfolioAdvisor, home_assistant_portfolio
from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.load_replacement import LoadReplacementBasis
from picot.v2.projection import Card


class EnergyOutlookPublisher:
    def __init__(
        self,
        publish: Callable[[dict[str, Any]], None],
        configuration: Callable[[PlanningInputSnapshot], StorageConversionModel],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        portfolio: PortfolioAdvisor | None = None,
    ) -> None:
        self.publish, self.configuration, self.now = publish, configuration, now
        self.portfolio = portfolio
        self.lock = Lock()
        self.last_attempt: datetime | None = None
        self.last_selection_attempt: datetime | None = None

    def refresh(
        self,
        snapshot: PlanningInputSnapshot,
        controlled_load_summary: dict[str, object] | None = None,
        replacement_basis: LoadReplacementBasis | None = None,
    ) -> None:
        if not 0 <= (self.now() - snapshot.captured_at).total_seconds() <= 120:
            return
        value = outlook(snapshot, self.configuration(snapshot))
        if controlled_load_summary is not None:
            value["controlled_load_history"] = controlled_load_summary
        value["replacement_basis"] = (
            replacement_basis.public()
            if replacement_basis is not None and replacement_basis.matches(snapshot)
            else dict(
                status="blocked", reason="complete_attribution_required", execution_authorized=False
            )
        )
        if 0 <= (self.now() - snapshot.captured_at).total_seconds() <= 120:
            self.publish(value)
            if self.portfolio is not None:
                self.portfolio.refresh(snapshot, replacement_basis)

    def submit(
        self,
        snapshot: PlanningInputSnapshot,
        controlled_load_summary: dict[str, object] | None = None,
        replacement_basis: LoadReplacementBasis | None = None,
    ) -> None:
        if not self.lock.acquire(blocking=False):
            return
        now = self.now()
        confirmation_only = (
            self.last_attempt is not None and 0 <= (now - self.last_attempt).total_seconds() < 60
        )
        if confirmation_only:
            if (
                self.portfolio is None
                or self.portfolio.last_answer is None
                or self.portfolio.last_answer.get("status") != "selected"
                or now >= instant(self.portfolio.last_answer["valid_until"])
                or self.last_selection_attempt is not None
                and 0 <= (now - self.last_selection_attempt).total_seconds() < 15
            ):
                self.lock.release()
                return
        else:
            self.last_attempt = now
        self.last_selection_attempt = now

        def work() -> None:
            try:
                if confirmation_only:
                    assert self.portfolio is not None
                    self.portfolio.poll_selection()
                else:
                    self.refresh(snapshot, controlled_load_summary, replacement_basis)
            except Exception as error:
                print(
                    json.dumps(dict(event="energy_outlook_failed", error=type(error).__name__)),
                    flush=True,
                )
            finally:
                self.lock.release()

        try:
            Thread(target=work, name="energy-outlook", daemon=True).start()
        except Exception:
            self.lock.release()
            # Thread creation failure must also remain isolated from control.


def home_assistant_outlook(
    token: str,
    configuration: Callable[[PlanningInputSnapshot], StorageConversionModel],
    accepted_loads: AcceptedLoads | None = None,
) -> EnergyOutlookPublisher:
    sink = HomeAssistantProjectionSink(token)
    return EnergyOutlookPublisher(
        publish=lambda value: sink.publish(Card(ENTITY, value["status"], value)),
        configuration=configuration,
        portfolio=home_assistant_portfolio(token, configuration, accepted_loads),
    )
