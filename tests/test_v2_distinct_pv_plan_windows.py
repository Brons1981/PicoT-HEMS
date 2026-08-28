from dataclasses import replace
from datetime import timedelta
from importlib import import_module

from legacy_cp_pipeline import CanonicalPipeline
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


def _interval(
    *,
    starts_at_offset: timedelta,
    pv_wh: float,
    load_wh: float,
    evidence_id: str,
) -> ProjectedHouseholdEnergyBalanceInterval:
    starts_at = BASE + starts_at_offset
    ends_at = starts_at + timedelta(hours=1)
    return ProjectedHouseholdEnergyBalanceInterval(
        starts_at=starts_at,
        ends_at=ends_at,
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


def test_each_feasible_pv_window_becomes_a_distinct_candidate() -> None:
    required_by = BASE + timedelta(hours=26)
    balance = replace(
        _balance(),
        intervals=(
            _interval(
                starts_at_offset=timedelta(0),
                pv_wh=800.0,
                load_wh=200.0,
                evidence_id="pv-today",
            ),
            _interval(
                starts_at_offset=timedelta(hours=24),
                pv_wh=800.0,
                load_wh=200.0,
                evidence_id="pv-tomorrow",
            ),
            _interval(
                starts_at_offset=timedelta(hours=25),
                pv_wh=0.0,
                load_wh=200.0,
                evidence_id="load-after",
            ),
        ),
    )
    requirement = replace(_requirement(), required_by=required_by)
    snapshot = replace(
        _snapshot(_capability_set()),
        horizon_end=required_by,
    )
    module = import_module("picot.v2.delegated_storage_candidates")

    candidate_set = module.construct_pv_charge_only_candidate(
        snapshot=snapshot,
        balance=balance,
        requirement=requirement,
    )

    assert len(candidate_set.candidates) == 2
    assert [candidate.family for candidate in candidate_set.candidates] == [
        "pv_charge_only",
        "pv_charge_only",
    ]
    assert [
        (path.segments[0].starts_at, path.segments[-1].ends_at)
        for path in candidate_set.energy_paths
    ] == [
        (BASE, BASE + timedelta(hours=1)),
        (BASE + timedelta(hours=24), BASE + timedelta(hours=25)),
    ]
    assert len(
        {candidate.candidate_id for candidate in candidate_set.candidates}
    ) == 2


def test_plain_language_labels_distinguish_today_and_tomorrow() -> None:
    run = CanonicalPipeline().run(planning_input=pipeline_snapshot())
    candidate = next(
        item for item in run.candidate_set.candidates if item.family == "pv_charge_only"
    )
    path = next(
        item
        for item in run.candidate_set.energy_paths
        if item.path_id == candidate.energy_path_id
    )
    outcome = run.outcomes.outcomes[0]
    tomorrow_path = replace(
        path,
        path_id=f"{path.path_id}-tomorrow",
        segments=tuple(
            replace(
                segment,
                segment_id=f"{segment.segment_id}-tomorrow",
                starts_at=segment.starts_at + timedelta(days=1),
                ends_at=segment.ends_at + timedelta(days=1),
            )
            for segment in path.segments
        ),
        segment_ids=tuple(
            f"{segment.segment_id}-tomorrow" for segment in path.segments
        ),
        projected_states=tuple(
            replace(state, at=state.at + timedelta(days=1))
            for state in path.projected_states
        ),
    )
    tomorrow_candidate = replace(
        candidate,
        candidate_id=f"{candidate.candidate_id}-tomorrow",
        energy_path_id=tomorrow_path.path_id,
    )
    tomorrow_outcome = replace(
        outcome,
        outcome_id=f"{outcome.outcome_id}-tomorrow",
        candidate_id=tomorrow_candidate.candidate_id,
        energy_path_id=tomorrow_path.path_id,
        charge_window_starts_at=outcome.charge_window_starts_at + timedelta(days=1),
        charge_window_ends_at=outcome.charge_window_ends_at + timedelta(days=1),
    )
    expanded_run = replace(
        run,
        candidate_set=replace(
            run.candidate_set,
            candidates=(*run.candidate_set.candidates, tomorrow_candidate),
            energy_paths=(*run.candidate_set.energy_paths, tomorrow_path),
        ),
        outcomes=replace(
            run.outcomes,
            candidate_ids=(*run.outcomes.candidate_ids, tomorrow_candidate.candidate_id),
            outcomes=(*run.outcomes.outcomes, tomorrow_outcome),
        ),
    )
    module = import_module("picot.v2.web_ui")

    explanation = module._build_plan_explanation(expanded_run)

    pv_labels = [
        plan["label_nl"]
        for plan in explanation["plans"]
        if plan["family"] == "pv_charge_only"
    ]
    assert pv_labels == [
        "Vandaag laden met verwachte zonne-energie",
        "Morgen laden met verwachte zonne-energie",
    ]


def test_refresh_preserves_open_plan_explanation_details_by_stable_key() -> None:
    html = import_module("picot.v2.web_ui").DASHBOARD_HTML
    capture = html[
        html.index("function captureDashboardState") :
        html.index("function restoreDashboardState")
    ]
    restore = html[
        html.index("function restoreDashboardState") :
        html.index("function shouldDeferRenderForSelection")
    ]

    assert 'details.className = "plan-explanation-detail"' in html
    assert "details.dataset.explanationKey" in html
    assert 'document.querySelectorAll("details.plan-explanation-detail")' in capture
    assert "openPlanExplanationDetails" in capture
    assert 'document.querySelectorAll("details.plan-explanation-detail")' in restore
    assert "state.openPlanExplanationDetails" in restore
