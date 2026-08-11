"""Canonical Price Driven v2 migration bridge.

This module turns the Home Assistant price forecast already normalized by the
adapter into the ADR-017/023/024 planner contracts. It deliberately stops at
Candidate Generation. Cost-first charging/export remains excluded by ADR-031
until an accepted energy-target/projected-state/power-allocation contract exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from picot.domain.candidate import CandidateSet
from picot.domain.capability_snapshot import CapabilitySnapshotSet
from picot.domain.forecast import ForecastSeries, ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import OpportunitySet
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.planner.candidate_engine import CandidateEngine
from picot.planner.opportunity_engine import OpportunityEngine
from picot.planner.price_opportunity_detection import PriceOpportunityDetectionConfig

PLANNING_HORIZON_HOURS = 36
MIGRATION_STRATEGY_VERSION = 1
MIGRATION_MAPPING_VERSION = 1
PRICE_DETECTION_CONFIG_VERSION = 1


@dataclass(frozen=True, slots=True)
class CanonicalPricePipelineResult:
    """Traceable canonical outputs produced by one Price Driven v2 planner run."""

    snapshot: PlanningInputSnapshot
    opportunities: OpportunitySet
    candidates: CandidateSet


def run_canonical_price_pipeline(
    forecast: ForecastSeries,
    *,
    evaluated_at: datetime,
    price_margin_eur_per_kwh: float,
) -> CanonicalPricePipelineResult:
    """Run price evidence through Snapshot -> Opportunity -> Candidate.

    The temporary migration strategy/capability envelopes contain no invented
    device capability or user objective. This is sufficient to prove canonical
    pipeline routing while ADR-031 intentionally excludes cost-first control.
    """

    horizon_end = min(
        evaluated_at + timedelta(hours=PLANNING_HORIZON_HOURS),
        forecast.expires_at,
    )
    snapshot_id = f"price-v2:{evaluated_at.isoformat()}"
    snapshot = PlanningInputSnapshot(
        snapshot_id=snapshot_id,
        captured_at=evaluated_at,
        horizon_end=horizon_end,
        strategy=PlannerStrategy(
            strategy_version=MIGRATION_STRATEGY_VERSION,
            source_profile_version=1,
            mapping_version="price-v2-migration-no-objectives-v1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=evaluated_at, phases=()),
        forecasts=ForecastSet(series=(forecast,)),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=MIGRATION_MAPPING_VERSION,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("price_runtime_validation_tick",),
    )
    price_config = PriceOpportunityDetectionConfig(
        config_version=PRICE_DETECTION_CONFIG_VERSION,
        low_price_margin_eur_per_kwh=price_margin_eur_per_kwh,
        high_price_margin_eur_per_kwh=price_margin_eur_per_kwh,
    )
    opportunities = OpportunityEngine().detect(snapshot, price_config=price_config)

    capabilities = CapabilitySnapshotSet(
        snapshot_id=snapshot.snapshot_id,
        mapping_version=MIGRATION_MAPPING_VERSION,
        captured_at=evaluated_at,
        capabilities=(),
    )
    candidates = CandidateEngine().generate(snapshot, opportunities, capabilities)
    return CanonicalPricePipelineResult(
        snapshot=snapshot,
        opportunities=opportunities,
        candidates=candidates,
    )
