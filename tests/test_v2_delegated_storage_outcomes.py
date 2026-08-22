from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import PathSegment, ProjectedEnergyState
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import (
    Candidate,
    CandidateSet,
    EnergyPath,
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
)

BASE = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
WINDOW_END = BASE + timedelta(hours=1)
REQUIRED_BY = BASE + timedelta(hours=2)
RUN_ID = "run-delegated-outcome-test"
SNAPSHOT_ID = "snapshot-delegated-outcome-test"
CAPABILITY_ID = "storage-capability-home-battery"
REQUIREMENT_ID = "storage-requirement"


def _candidate_set(
    *,
    source_policy: ChargeSourcePolicy = ChargeSourcePolicy.PV_ONLY,
    required_energy_wh: float = 1200.0,
) -> CandidateSet:
    segment = PathSegment(
        segment_id="segment-pv-charge-only",
        order=1,
        execution_scope_id="home-battery",
        starts_at=BASE,
        ends_at=WINDOW_END,
        primitive=ExecutionPrimitive.BALANCE_CHARGE_ONLY,
        capability_id=CAPABILITY_ID,
        purpose="Acquire required storage energy from forecast PV surplus",
        evidence_ids=(REQUIREMENT_ID, "pv-window-evidence", CAPABILITY_ID),
        requested_power_w=None,
        charge_source_policy=source_policy,
    )
    path = EnergyPath(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        path_id="energy-path-pv-charge-only",
        family="pv_charge_only",
        segment_ids=(segment.segment_id,),
        segments=(segment,),
        projected_states=(
            ProjectedEnergyState(
                at=WINDOW_END,
                confidence=0.7,
                storage_energy_wh=1400.0,
            ),
            ProjectedEnergyState(
                at=REQUIRED_BY,
                confidence=0.7,
                storage_energy_wh=1200.0,
            ),
        ),
        capability_confidence=0.95,
    )
    candidate = Candidate(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        candidate_id="candidate-pv-charge-only",
        energy_path_id=path.path_id,
        family=path.family,
    )
    balance = ProjectedHouseholdEnergyBalance(
        balance_id="projected-balance",
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        storage_state_id="storage-home",
        intervals=(
            ProjectedHouseholdEnergyBalanceInterval(
                starts_at=BASE,
                ends_at=WINDOW_END,
                current_usable_storage_energy_wh=1000.0,
                expected_usable_pv_energy_wh=800.0,
                planned_grid_energy_wh=0.0,
                household_load_forecast_energy_wh=200.0,
                known_future_demand_energy_wh=0.0,
                conversion_losses_wh=0.0,
                other_planned_household_energy_flows_wh=0.0,
                projected_storage_energy_wh=1600.0,
                confidence=0.7,
                evidence_ids=("pv-window-evidence", "load-window-evidence"),
                storage_confidence=1.0,
                pv_confidence=0.8,
                load_confidence=0.7,
                confidence_method_version=(
                    "projected-household-interval-required-input-min:v1"
                ),
            ),
            ProjectedHouseholdEnergyBalanceInterval(
                starts_at=WINDOW_END,
                ends_at=REQUIRED_BY,
                current_usable_storage_energy_wh=1600.0,
                expected_usable_pv_energy_wh=0.0,
                planned_grid_energy_wh=0.0,
                household_load_forecast_energy_wh=200.0,
                known_future_demand_energy_wh=0.0,
                conversion_losses_wh=0.0,
                other_planned_household_energy_flows_wh=0.0,
                projected_storage_energy_wh=1400.0,
                confidence=0.7,
                evidence_ids=("pv-after-evidence", "load-after-evidence"),
                storage_confidence=1.0,
                pv_confidence=None,
                load_confidence=0.7,
                confidence_method_version=(
                    "projected-household-interval-required-input-min:v1"
                ),
            ),
        ),
    )
    requirement = StorageEnergyRequirement(
        requirement_id=REQUIREMENT_ID,
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        storage_state_id="storage-home",
        projected_balance_id=balance.balance_id,
        required_energy_wh=required_energy_wh,
        required_soc=0.15,
        required_by=REQUIRED_BY,
        reason="household_requirement",
        confidence=0.7,
        evidence_ids=("storage-evidence", "load-after-evidence"),
        reserve_contribution_wh=200.0,
    )
    return CandidateSet(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        candidate_set_id="candidate-set-pv-charge-only",
        candidates=(candidate,),
        energy_paths=(path,),
        projected_balances=(balance,),
        storage_requirements=(requirement,),
        derivation_status="constructed",
        derivation_reason=None,
    )


def _simulate(
    candidate_set: CandidateSet,
    *,
    minimum_reserve_energy_wh: float | None = None,
) -> object:
    module = import_module("picot.v2.delegated_storage_outcomes")
    return module.simulate_pv_charge_only_outcomes(
        candidate_set,
        minimum_reserve_energy_wh=minimum_reserve_energy_wh,
    )


def test_outcome_records_bounded_pv_and_zero_grid_contribution() -> None:
    outcome_set = _simulate(_candidate_set())

    assert outcome_set.candidate_ids == ("candidate-pv-charge-only",)
    assert len(outcome_set.outcomes) == 1
    outcome = outcome_set.outcomes[0]
    assert outcome.pv_storage_contribution_wh == pytest.approx(400.0)
    assert outcome.grid_storage_contribution_wh == pytest.approx(0.0)
    assert outcome.conversion_losses_wh == pytest.approx(0.0)
    assert outcome.storage_energy_at_window_end_wh == pytest.approx(1400.0)
    assert outcome.storage_energy_at_requirement_wh == pytest.approx(1200.0)
    assert outcome.required_energy_wh == pytest.approx(1200.0)


def test_outcome_preserves_confidence_recoverability_and_lineage() -> None:
    outcome_set = _simulate(_candidate_set())

    outcome = outcome_set.outcomes[0]
    assert outcome.run_id == RUN_ID
    assert outcome.snapshot_id == SNAPSHOT_ID
    assert outcome.candidate_id == "candidate-pv-charge-only"
    assert outcome.energy_path_id == "energy-path-pv-charge-only"
    assert outcome.storage_requirement_id == REQUIREMENT_ID
    assert outcome.capability_ids == (CAPABILITY_ID,)
    assert outcome.charge_window_starts_at == BASE
    assert outcome.charge_window_ends_at == WINDOW_END
    assert outcome.requirement_satisfied is True
    assert outcome.recoverability == pytest.approx(0.7)
    assert outcome.confidence == pytest.approx(0.7)
    assert set(outcome.evidence_ids) >= {
        REQUIREMENT_ID,
        "pv-window-evidence",
        CAPABILITY_ID,
        "storage-evidence",
    }
    assert outcome.method_version == "delegated-storage-outcome:v4"
    assert outcome.confidence_assessment is not None
    assert outcome.confidence_assessment.result == pytest.approx(0.7)
    assert outcome.confidence_assessment.limiting_component == "charge_window"
    assert outcome.confidence_assessment.method_version == (
        "delegated-storage-outcome-confidence:v2"
    )
    components = {
        item.name: item.value
        for item in outcome.confidence_assessment.components
    }
    assert components == pytest.approx(
        {
            "requirement": 0.7,
            "charge_window": 0.7,
            "capability": 0.95,
            "storage_state": 1.0,
            "pv_source": 0.8,
            "household_load": 0.7,
        }
    )


def test_full_charge_target_and_later_minimum_reserve_are_separate() -> None:
    outcome = _simulate(
        _candidate_set(required_energy_wh=1400.0),
        minimum_reserve_energy_wh=1000.0,
    ).outcomes[0]

    assert outcome.storage_energy_at_window_end_wh == pytest.approx(1400.0)
    assert outcome.storage_energy_at_requirement_wh == pytest.approx(1200.0)
    assert outcome.charge_target_satisfied is True
    assert outcome.reserve_satisfied is True
    assert outcome.reserve_energy_required_wh == pytest.approx(1000.0)
    assert outcome.requirement_satisfied is True


def test_outcome_accepts_sub_microwatt_hour_rounding_at_requirement() -> None:
    outcome_set = _simulate(
        _candidate_set(required_energy_wh=1200.0000005)
    )

    outcome = outcome_set.outcomes[0]
    assert outcome.requirement_satisfied is True
    assert outcome.storage_energy_at_requirement_wh == pytest.approx(1200.0)
    assert outcome.required_energy_wh == pytest.approx(1200.0000005)


def test_pv_only_simulation_rejects_grid_supported_source_policy() -> None:
    with pytest.raises(ValueError, match="PV_ONLY"):
        _simulate(
            _candidate_set(
                source_policy=ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED,
            )
        )


def test_grid_requirement_outcome_separates_pv_grid_and_charge_loss() -> None:
    module = import_module("picot.v2.delegated_storage_outcomes")
    source = _candidate_set(required_energy_wh=1600.0)
    source_path = source.energy_paths[0]
    grid_path = replace(
        source_path,
        family="grid_requirement",
        segments=(
            replace(
                source_path.segments[0],
                charge_source_policy=ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT,
            ),
        ),
        projected_states=(
            replace(source_path.projected_states[0], storage_energy_wh=1800.0),
            replace(source_path.projected_states[1], storage_energy_wh=1600.0),
        ),
    )
    grid_candidate = replace(
        source.candidates[0],
        family="grid_requirement",
        energy_path_id=grid_path.path_id,
    )
    candidate_set = replace(
        source,
        candidates=(grid_candidate,),
        energy_paths=(grid_path,),
    )

    outcome = module.simulate_grid_requirement_outcomes(
        candidate_set,
        charge_efficiency=0.80,
    ).outcomes[0]

    assert outcome.requirement_satisfied is True
    assert outcome.pv_storage_contribution_wh == pytest.approx(600.0)
    assert outcome.grid_storage_contribution_wh == pytest.approx(200.0)
    assert outcome.conversion_losses_wh == pytest.approx(50.0)
