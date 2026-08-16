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
            ),
        ),
    )
    requirement = StorageEnergyRequirement(
        requirement_id=REQUIREMENT_ID,
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        storage_state_id="storage-home",
        projected_balance_id=balance.balance_id,
        required_energy_wh=1200.0,
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


def _simulate(candidate_set: CandidateSet) -> object:
    module = import_module("picot.v2.delegated_storage_outcomes")
    return module.simulate_pv_charge_only_outcomes(candidate_set)


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
    assert outcome.method_version == "delegated-storage-outcome:v1"


def test_pv_only_simulation_rejects_grid_supported_source_policy() -> None:
    with pytest.raises(ValueError, match="PV_ONLY"):
        _simulate(
            _candidate_set(
                source_policy=ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED,
            )
        )
