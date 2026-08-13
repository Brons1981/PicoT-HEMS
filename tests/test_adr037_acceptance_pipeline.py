from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.evaluation import CandidateValidity, EvaluationOutcomeStatus
from picot.domain.evidence_confidence_policy import (
    EvidenceConfidenceAssessment,
    EvidenceConfidenceDecision,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries, ForecastSet
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import (
    EvidenceReference,
    Opportunity,
    OpportunityKind,
    OpportunityLifecycle,
    OpportunitySet,
)
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalancePoint,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.domain.storage_energy_requirement import StorageRequirementReason
from picot.planner.adr037_pipeline import ADR037PlannerPipeline

BASE = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
SCOPE = "battery-main"
CAPABILITY_ID = "battery-charge"


def _price_forecast() -> ForecastSeries:
    return ForecastSeries(
        forecast_id="price-forecast",
        kind=ForecastKind.ENERGY_PRICE,
        source="test-price",
        created_at=BASE,
        expires_at=BASE + timedelta(hours=6),
        unit="EUR/kWh",
        points=(
            ForecastPoint(
                starts_at=BASE,
                ends_at=BASE + timedelta(hours=1),
                value=0.20,
                confidence=1.0,
            ),
            ForecastPoint(
                starts_at=BASE + timedelta(hours=1),
                ends_at=BASE + timedelta(hours=2),
                value=0.10,
                confidence=1.0,
            ),
        ),
    )


def _pv_timeline() -> PVEnergyTimeline:
    return PVEnergyTimeline(
        timeline_id="pv-timeline-acceptance",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(hours=6),
        intervals=tuple(
            PVEnergyTimelineInterval(
                starts_at=BASE + timedelta(hours=hour),
                ends_at=BASE + timedelta(hours=hour + 1),
                energy_wh=0.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=1.0,
                evidence_ids=(f"pv:{hour}",),
                method_version="acceptance-v1",
            )
            for hour in range(6)
        ),
    )


def _load_forecast() -> HouseholdLoadForecast:
    return HouseholdLoadForecast(
        forecast_id="load-forecast-acceptance",
        created_at=BASE,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(hours=6),
        intervals=tuple(
            HouseholdLoadForecastInterval(
                starts_at=BASE + timedelta(hours=hour),
                ends_at=BASE + timedelta(hours=hour + 1),
                expected_energy_wh=0.0,
                confidence=1.0,
            )
            for hour in range(6)
        ),
        historical_source_reference="acceptance-fixture",
        method_version="acceptance-v1",
    )


def _snapshot() -> PlanningInputSnapshot:
    return PlanningInputSnapshot(
        snapshot_id="snapshot-adr037-acceptance",
        captured_at=BASE,
        horizon_end=BASE + timedelta(hours=6),
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="objective-map-v1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=(_price_forecast(),)),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("adr037_acceptance",),
        household_load_forecast=_load_forecast(),
        pv_energy_timeline=_pv_timeline(),
    )


def _limit() -> EffectiveStorageLimit:
    return EffectiveStorageLimit(
        limit_id="limit-1",
        execution_scope_id=SCOPE,
        max_soc=0.95,
        usable_capacity_wh=8000.0,
        confidence=1.0,
        evidence_ids=("config:max-soc",),
        method_version="effective-storage-limit-v1",
    )


def _storage_state() -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id="state-1",
        execution_scope_id=SCOPE,
        capability_id=CAPABILITY_ID,
        current_soc=0.25,
        usable_capacity_wh=8000.0,
        measured_at=BASE,
        confidence=0.95,
        evidence_ids=("sensor:soc",),
    )


def _capability(*, maximum_power_w: float = 2000.0) -> LogicalCapabilitySnapshot:
    return LogicalCapabilitySnapshot(
        capability_id=CAPABILITY_ID,
        execution_scope_id=SCOPE,
        supported_primitives=(ExecutionPrimitive.CHARGE_AT_POWER,),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=BASE,
        confidence=0.95,
        source_mapping_id="mapping-1",
        adapter_contract_version="1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
        minimum_power_w=100.0,
        maximum_power_w=maximum_power_w,
        power_step_w=100.0,
    )


def _assessment(*, lower_allowed: bool = True) -> EvidenceConfidenceAssessment:
    return EvidenceConfidenceAssessment(
        decision=(
            EvidenceConfidenceDecision.LOWER_TARGET_ALLOWED
            if lower_allowed
            else EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED
        ),
        current_confidence=0.8,
        baseline_mean_confidence=0.75,
        baseline_id="baseline-1",
        reason=(
            "current_confidence_at_or_above_own_reliable_mean"
            if lower_allowed
            else "current_confidence_below_own_reliable_mean"
        ),
        evidence_ids=("confidence:evidence",),
    )


def _price_opportunities() -> OpportunitySet:
    opportunity = Opportunity(
        opportunity_id="lowest-price-before-protection",
        snapshot_id="snapshot-adr037-acceptance",
        kind=OpportunityKind.LOWEST_PRICE_WINDOW,
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=2),
        confidence=0.9,
        lifecycle=OpportunityLifecycle.DETECTED,
        evidence=(
            EvidenceReference(source_id="price-forecast", point_indexes=(0, 1)),
        ),
    )
    return OpportunitySet(
        snapshot_id="snapshot-adr037-acceptance", opportunities=(opportunity,)
    )


def _pv_sufficient_balance() -> ProjectedHouseholdEnergyBalance:
    return ProjectedHouseholdEnergyBalance(
        balance_id="balance-pv-sufficient",
        created_at=BASE,
        horizon_end=BASE + timedelta(hours=6),
        execution_scope_id=SCOPE,
        starting_storage_energy_wh=4000.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=BASE + timedelta(hours=1),
                projected_storage_energy_wh=6000.0,
                cumulative_pv_energy_wh=2500.0,
                cumulative_household_load_wh=500.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=BASE + timedelta(hours=2),
                projected_storage_energy_wh=5000.0,
                cumulative_pv_energy_wh=3000.0,
                cumulative_household_load_wh=2000.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=BASE + timedelta(hours=6),
                projected_storage_energy_wh=3000.0,
                cumulative_pv_energy_wh=3000.0,
                cumulative_household_load_wh=4000.0,
            ),
        ),
        confidence=0.85,
        evidence_ids=("balance:pv-sufficient",),
    )


def _pv_shortfall_balance() -> ProjectedHouseholdEnergyBalance:
    return ProjectedHouseholdEnergyBalance(
        balance_id="balance-pv-shortfall",
        created_at=BASE,
        horizon_end=BASE + timedelta(hours=6),
        execution_scope_id=SCOPE,
        starting_storage_energy_wh=2000.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=BASE + timedelta(hours=1),
                projected_storage_energy_wh=3000.0,
                cumulative_pv_energy_wh=1500.0,
                cumulative_household_load_wh=500.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=BASE + timedelta(hours=2),
                projected_storage_energy_wh=4000.0,
                cumulative_pv_energy_wh=3000.0,
                cumulative_household_load_wh=1000.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=BASE + timedelta(hours=6),
                projected_storage_energy_wh=-2000.0,
                cumulative_pv_energy_wh=3000.0,
                cumulative_household_load_wh=7000.0,
            ),
        ),
        confidence=0.8,
        evidence_ids=("balance:pv-shortfall",),
    )


def _run(
    *,
    balance: ProjectedHouseholdEnergyBalance,
    maximum_power_w: float = 2000.0,
    lower_allowed: bool = True,
):
    capability = _capability(maximum_power_w=maximum_power_w)
    return ADR037PlannerPipeline().run(
        requirement_id="storage:req:acceptance",
        evaluated_at=BASE,
        snapshot=_snapshot(),
        balance=balance,
        effective_limit=_limit(),
        confidence_assessment=_assessment(lower_allowed=lower_allowed),
        storage_state=_storage_state(),
        storage_capability=capability,
        opportunities=_price_opportunities(),
        capabilities=CapabilitySnapshotSet(
            snapshot_id="snapshot-adr037-acceptance",
            mapping_version=1,
            captured_at=BASE,
            capabilities=(capability,),
        ),
    )


def test_pv_sufficient_path_needs_no_grid_supported_candidate() -> None:
    result = _run(balance=_pv_sufficient_balance())
    assert result.pv_only_feasibility.energy_sufficient is True
    assert all(
        path.family.value != "cost_first" for path in result.candidate_set.energy_paths
    )
    assert result.evaluation.status is EvaluationOutcomeStatus.WINNER_SELECTED
    assert result.evaluation.winning_candidate is not None
    assert result.evaluation.winning_candidate.family.value == "reserve_first"


def test_pv_shortfall_makes_grid_supported_path_the_only_valid_winner() -> None:
    result = _run(balance=_pv_shortfall_balance())
    assert result.requirement.protection_starts_at == BASE + timedelta(hours=2)
    assert result.requirement.protected_through == BASE + timedelta(hours=6)
    assert result.requirement.required_energy_wh == pytest.approx(6000.0)
    assert result.pv_only_feasibility.energy_sufficient is False
    assert result.technical_recoverability.technically_recoverable is True
    cost_paths = [
        path
        for path in result.candidate_set.energy_paths
        if path.family.value == "cost_first"
    ]
    assert len(cost_paths) == 1
    assert cost_paths[0].segments[0].starts_at == BASE + timedelta(hours=1)
    assert cost_paths[0].segments[0].ends_at == BASE + timedelta(hours=2)
    assert (
        cost_paths[0].segments[0].charge_source_policy
        is ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED
    )
    validity = {
        item.candidate_id: item.validity
        for item in result.candidate_outcomes.outcomes
    }
    baseline = next(
        candidate
        for candidate in result.candidate_set.candidates
        if candidate.family.value == "reserve_first"
    )
    grid = next(
        candidate
        for candidate in result.candidate_set.candidates
        if candidate.family.value == "cost_first"
    )
    assert validity[baseline.candidate_id] is CandidateValidity.INVALID
    assert validity[grid.candidate_id] is CandidateValidity.VALID
    assert result.evaluation.winning_candidate is not None
    assert result.evaluation.winning_candidate.candidate_id == grid.candidate_id


def test_degraded_confidence_raises_requirement_to_effective_maximum() -> None:
    result = _run(
        balance=_pv_shortfall_balance(),
        maximum_power_w=3000.0,
        lower_allowed=False,
    )
    assert result.requirement.reason is StorageRequirementReason.CONSERVATIVE_RESERVE
    assert result.requirement.required_energy_wh == pytest.approx(7600.0)
    assert result.requirement.reserve_energy_wh == pytest.approx(1600.0)
    assert result.requirement.protection_starts_at == BASE + timedelta(hours=2)
    assert result.requirement.protected_through == BASE + timedelta(hours=6)
    cost_paths = [
        path
        for path in result.candidate_set.energy_paths
        if path.family.value == "cost_first"
    ]
    assert len(cost_paths) == 1
    assert len(cost_paths[0].segments) == 2


def test_unrecoverable_shortfall_returns_explicit_no_valid_candidate() -> None:
    result = _run(balance=_pv_shortfall_balance(), maximum_power_w=1000.0)
    assert result.pv_only_feasibility.energy_sufficient is False
    assert result.technical_recoverability.technically_recoverable is False
    assert all(
        path.family.value != "cost_first" for path in result.candidate_set.energy_paths
    )
    assert all(
        outcome.validity is CandidateValidity.INVALID
        for outcome in result.candidate_outcomes.outcomes
    )
    assert result.evaluation.status is EvaluationOutcomeStatus.NO_VALID_CANDIDATE
    assert result.evaluation.winning_candidate is None
