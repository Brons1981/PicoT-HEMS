from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.energy_path import EnergyPath, ProjectedEnergyState
from picot.domain.objectives import ObjectiveKind
from picot.planner.adr037_candidate_outcome_derivation import ADR037CandidateOutcomeDeriver

BASE = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)


def test_simulated_path_derives_self_consumption_and_net_balance() -> None:
    path = EnergyPath(
        path_id="path-1",
        snapshot_id="snapshot-1",
        family=CandidateFamily.RESERVE_FIRST,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(minutes=30),
        segments=(),
        projected_states=(
            ProjectedEnergyState(
                at=BASE + timedelta(minutes=15),
                confidence=0.8,
                household_import_w=0.0,
                household_export_w=2000.0,
                pv_production_w=3000.0,
                household_demand_w=1000.0,
                battery_soc=0.4,
                controllable_load_w=0.0,
            ),
            ProjectedEnergyState(
                at=BASE + timedelta(minutes=30),
                confidence=0.75,
                household_import_w=500.0,
                household_export_w=0.0,
                pv_production_w=500.0,
                household_demand_w=1000.0,
                battery_soc=0.4,
                controllable_load_w=0.0,
            ),
        ),
        opportunity_ids=(),
        constraint_ids=(),
        capability_ids=(),
        strategy_version=1,
        mapping_version=1,
        assumptions=("test",),
        confidence=0.9,
    )
    candidate = Candidate(
        candidate_id="candidate-1",
        snapshot_id="snapshot-1",
        family=CandidateFamily.RESERVE_FIRST,
        energy_path_id="path-1",
        opportunity_ids=(),
        constraint_ids=(),
        strategy_version=1,
        capability_ids=(),
        assumptions=("test",),
        confidence=0.9,
    )
    result = ADR037CandidateOutcomeDeriver().derive(
        candidate_set=CandidateSet(
            snapshot_id="snapshot-1",
            strategy_version=1,
            candidates=(candidate,),
            energy_paths=(path,),
            exclusions=(),
        )
    )

    outcomes = {item.objective: item for item in result.outcomes[0].objective_outcomes}
    assert outcomes[ObjectiveKind.SELF_CONSUMPTION].value == 375.0
    assert outcomes[ObjectiveKind.SELF_CONSUMPTION].unit == "Wh"
    assert outcomes[ObjectiveKind.SELF_CONSUMPTION].confidence == 0.75
    assert outcomes[ObjectiveKind.NET_BALANCE].value == 625.0
    assert outcomes[ObjectiveKind.NET_BALANCE].unit == "Wh"
