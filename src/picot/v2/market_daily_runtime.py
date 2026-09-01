"""Synchronous planning boundary for the sole MEP planner.

This module owns no execution, dispatch, commitment or worker lifecycle. One
canonical pipeline cycle invokes it once with one immutable Planning Input.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import sqrt
from time import perf_counter

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.domain.storage_energy_inventory import StorageEnergyInventory
from picot.planner.market_daily_planner import (
    MarketDailyCandidatePortfolio,
    MarketDailyPlanner,
    MarketDailyPlannerDiagnostics,
    MarketTradingPolicy,
)
from picot.v2.contracts import OpportunitySet, PlanningInputSnapshot

METHOD_VERSION = "v2-market-daily-runtime:v3"


@dataclass(frozen=True, slots=True)
class MarketDailyRuntimeOutcome:
    """MEP planner result plus passive timing evidence."""

    snapshot_id: str
    run_id: str
    captured_at: datetime
    status: str
    reason: str | None
    duration_ms: float
    portfolio: MarketDailyCandidatePortfolio | None
    method_version: str
    planner_diagnostics: MarketDailyPlannerDiagnostics | None = None
    required_by: datetime | None = None

    def __post_init__(self) -> None:
        if self.status not in {"completed", "blocked"}:
            raise ValueError("MEP runtime status must be completed or blocked.")
        if (self.portfolio is None) != (self.status == "blocked"):
            raise ValueError("MEP runtime status must match its portfolio.")
        if self.status == "blocked" and not self.reason:
            raise ValueError("Blocked MEP runtime requires a reason.")
        if self.portfolio is not None and self.portfolio.snapshot_id != self.snapshot_id:
            raise ValueError("MEP runtime snapshot lineage must match.")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("MEP runtime capture time must be timezone-aware.")


class MarketDailyPlannerRuntime:
    """Resolve MEP configuration and generate one portfolio synchronously."""

    def __init__(
        self,
        conversion_model: StorageConversionModel,
        *,
        trading_policy: MarketTradingPolicy | None = None,
        micro_charge_suppression_fraction: float = 0.01,
        storage_inventory_provider: (
            Callable[[], StorageEnergyInventory | None] | None
        ) = None,
    ) -> None:
        self.conversion_model = conversion_model
        # DEV.221 restores the bounded physical MEP basis first. Optional
        # market export is reintroduced only through an explicit user rule in
        # a later accepted slice; it must never be an implicit default.
        self.trading_policy = trading_policy or MarketTradingPolicy(
            market_routes_enabled=False
        )
        self.micro_charge_suppression_fraction = micro_charge_suppression_fraction
        self.storage_inventory_provider = storage_inventory_provider

    def planning_configuration(
        self,
        snapshot: PlanningInputSnapshot,
    ) -> tuple[StorageConversionModel, MarketTradingPolicy]:
        evidence = snapshot.storage_round_trip_efficiency
        if (
            evidence is None
            or evidence.status != "available"
            or evidence.round_trip_efficiency is None
        ):
            return self.conversion_model, replace(
                self.trading_policy,
                market_routes_enabled=False,
            )
        directional_efficiency = sqrt(evidence.round_trip_efficiency)
        return (
            StorageConversionModel(
                model_id=f"mep-zendure-rte:{snapshot.snapshot_id}",
                charge_efficiency=directional_efficiency,
                discharge_efficiency=directional_efficiency,
                evidence_ids=(evidence.evidence_id,),
                method_version="measured-zendure-total-rte:v1",
            ),
            self.trading_policy,
        )

    def generate(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        required_by: datetime | None = None,
        opportunities: OpportunitySet | None = None,
        comparison_horizon_end: datetime | None = None,
    ) -> MarketDailyRuntimeOutcome:
        started = perf_counter()
        portfolio: MarketDailyCandidatePortfolio | None = None
        reason: str | None = None
        status = "completed"
        effective_required_by = required_by
        try:
            conversion_model, trading_policy = self.planning_configuration(snapshot)
            maximum_duration = (
                comparison_horizon_end - snapshot.captured_at
                if comparison_horizon_end is not None
                else timedelta(hours=36)
            )
            portfolio, planner_diagnostics = (
                MarketDailyPlanner().generate_with_diagnostics(
                    snapshot=snapshot,
                    conversion_model=conversion_model,
                    trading_policy=trading_policy,
                    micro_charge_suppression_fraction=(
                        self.micro_charge_suppression_fraction
                    ),
                    storage_inventory=(
                        self.storage_inventory_provider()
                        if self.storage_inventory_provider is not None
                        else None
                    ),
                    required_by=effective_required_by,
                    opportunities=opportunities,
                    maximum_duration=maximum_duration,
                )
            )
            effective_required_by = portfolio.required_by
        except Exception as exc:
            status = "blocked"
            reason = str(exc) or exc.__class__.__name__
            planner_diagnostics = None
        return MarketDailyRuntimeOutcome(
            snapshot_id=snapshot.snapshot_id,
            run_id=snapshot.run_id,
            captured_at=snapshot.captured_at,
            status=status,
            reason=reason,
            duration_ms=round((perf_counter() - started) * 1000.0, 3),
            portfolio=portfolio,
            planner_diagnostics=planner_diagnostics,
            method_version=METHOD_VERSION,
            required_by=effective_required_by,
        )
