from dataclasses import replace
from datetime import datetime, timedelta
from importlib import import_module

import pytest
from test_v2_delegated_storage_candidates import (
    BASE,
    _balance,
    _capability_set,
    _requirement,
    _snapshot,
)
from test_v2_delegated_storage_pipeline_integration import (
    _snapshot as pipeline_snapshot,
)

from picot.v2.contracts import ProjectedHouseholdEnergyBalanceInterval
from legacy_cp_pipeline import CanonicalPipeline
from picot.v2.storage_capability_snapshot import (
    build_storage_capability_snapshot_set,
)
from picot.v2.zendure_mode_capabilities import (
    derive_zendure_mode_capability_evidence,
)


def _interval(
    *,
    starts_at: datetime,
    pv_wh: float,
    load_wh: float,
    evidence_id: str,
) -> ProjectedHouseholdEnergyBalanceInterval:
    return ProjectedHouseholdEnergyBalanceInterval(
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        current_usable_storage_energy_wh=1000.0,
        expected_usable_pv_energy_wh=pv_wh,
        planned_grid_energy_wh=0.0,
        household_load_forecast_energy_wh=load_wh,
        known_future_demand_energy_wh=0.0,
        conversion_losses_wh=0.0,
        other_planned_household_energy_flows_wh=0.0,
        projected_storage_energy_wh=1000.0 + pv_wh - load_wh,
        confidence=0.7,
        evidence_ids=(evidence_id,),
    )


def test_active_pv_interval_is_clipped_to_now_and_scaled_proportionally() -> None:
    captured_at = BASE + timedelta(minutes=30)
    required_by = BASE + timedelta(hours=2)
    balance = replace(
        _balance(),
        intervals=(
            _interval(
                starts_at=BASE,
                pv_wh=1000.0,
                load_wh=200.0,
                evidence_id="active-pv",
            ),
            _interval(
                starts_at=BASE + timedelta(hours=1),
                pv_wh=0.0,
                load_wh=200.0,
                evidence_id="later-load",
            ),
        ),
    )
    source_snapshot = _snapshot(_capability_set())
    snapshot = replace(
        source_snapshot,
        captured_at=captured_at,
        horizon_end=required_by,
        capability_snapshot_set=replace(
            source_snapshot.capability_snapshot_set,
            captured_at=captured_at,
        ),
    )
    module = import_module("picot.v2.delegated_storage_candidates")
    outcome_module = import_module("picot.v2.delegated_storage_outcomes")

    candidate_set = module.construct_pv_charge_only_candidate(
        snapshot=snapshot,
        balance=balance,
        requirement=_requirement(),
    )
    outcomes = outcome_module.simulate_pv_charge_only_outcomes(candidate_set)

    assert candidate_set.energy_paths[0].segments[0].starts_at == captured_at
    assert candidate_set.energy_paths[0].segments[0].ends_at == BASE + timedelta(
        hours=1
    )
    assert outcomes.outcomes[0].pv_storage_contribution_wh == pytest.approx(400.0)
    assert outcomes.outcomes[0].requirement_satisfied is True


def test_partial_today_and_tomorrow_windows_form_one_feasible_plan() -> None:
    required_by = BASE + timedelta(hours=26)
    balance = replace(
        _balance(),
        intervals=(
            _interval(
                starts_at=BASE,
                pv_wh=500.0,
                load_wh=200.0,
                evidence_id="partial-today",
            ),
            _interval(
                starts_at=BASE + timedelta(hours=24),
                pv_wh=500.0,
                load_wh=200.0,
                evidence_id="partial-tomorrow",
            ),
            _interval(
                starts_at=BASE + timedelta(hours=25),
                pv_wh=0.0,
                load_wh=100.0,
                evidence_id="load-after",
            ),
        ),
    )
    requirement = replace(
        _requirement(),
        required_energy_wh=1400.0,
        required_soc=0.175,
        required_by=required_by,
    )
    snapshot = replace(
        _snapshot(_capability_set()),
        horizon_end=required_by,
    )
    module = import_module("picot.v2.delegated_storage_candidates")
    outcome_module = import_module("picot.v2.delegated_storage_outcomes")

    candidate_set = module.construct_pv_charge_only_candidate(
        snapshot=snapshot,
        balance=balance,
        requirement=requirement,
    )
    outcomes = outcome_module.simulate_pv_charge_only_outcomes(candidate_set)
    satisfying = [
        outcome for outcome in outcomes.outcomes if outcome.requirement_satisfied
    ]

    assert len(satisfying) == 1
    winning_path = next(
        path
        for path in candidate_set.energy_paths
        if path.path_id == satisfying[0].energy_path_id
    )
    assert len(winning_path.segments) == 2
    assert [segment.starts_at for segment in winning_path.segments] == [
        BASE,
        BASE + timedelta(hours=24),
    ]


def test_plain_language_combined_plan_shows_today_and_tomorrow_phases() -> None:
    run = CanonicalPipeline().run(planning_input=pipeline_snapshot())
    candidate = next(
        item for item in run.candidate_set.candidates if item.family == "pv_charge_only"
    )
    path = next(
        item
        for item in run.candidate_set.energy_paths
        if item.path_id == candidate.energy_path_id
    )
    tomorrow_segment = replace(
        path.segments[0],
        segment_id=f"{path.segments[0].segment_id}-tomorrow",
        order=2,
        starts_at=path.segments[0].starts_at + timedelta(days=1),
        ends_at=path.segments[0].ends_at + timedelta(days=1),
    )
    combined_path = replace(
        path,
        segment_ids=(path.segments[0].segment_id, tomorrow_segment.segment_id),
        segments=(path.segments[0], tomorrow_segment),
    )
    combined_run = replace(
        run,
        candidate_set=replace(
            run.candidate_set,
            energy_paths=tuple(
                combined_path if item.path_id == path.path_id else item
                for item in run.candidate_set.energy_paths
            ),
        ),
        outcomes=replace(
            run.outcomes,
            outcomes=tuple(
                replace(
                    outcome,
                    charge_window_ends_at=outcome.charge_window_ends_at
                    + timedelta(days=1),
                )
                for outcome in run.outcomes.outcomes
            ),
        ),
    )
    module = import_module("picot.v2.web_ui")

    explanation = module._build_plan_explanation(combined_run)
    combined = next(
        plan for plan in explanation["plans"] if plan["family"] == "pv_charge_only"
    )

    assert combined["label_nl"] == (
        "Vandaag en morgen laden met verwachte zonne-energie"
    )
    assert [phase["label_nl"] for phase in combined["phases"]] == [
        "Nu laden met PV",
        "Morgen aanvullen met PV",
    ]


def test_standby_with_nom_capability_builds_active_pv_charge_plan() -> None:
    source = pipeline_snapshot()
    mode_evidence = derive_zendure_mode_capability_evidence(
        {
            "state": "Standby",
            "attributes": {"options": ["Standby", "Nul op de meter"]},
        },
        captured_at=source.captured_at,
        source_entity_id="input_select.zendure_mode",
        capability_id="storage-capability-home-battery",
        execution_scope_id="home-battery",
    )
    snapshot = replace(
        source,
        storage_mode_capability_evidence=mode_evidence,
        capability_snapshot_set=build_storage_capability_snapshot_set(
            mode_evidence,
            snapshot_id=source.snapshot_id,
        ),
    )

    run = CanonicalPipeline().run(planning_input=snapshot)

    assert run.evaluation.status == "winner_selected"
    assert next(
        candidate.family
        for candidate in run.candidate_set.candidates
        if candidate.candidate_id == run.evaluation.winning_candidate_id
    ) == "pv_charge_only"
    assert run.execution_plan_set.plans[0].planned_primitive.value == (
        "balance_bidirectional"
    )
    assert run.execution_plan_set.plans[0].planned_vendor_mode == "Nul op de meter"
