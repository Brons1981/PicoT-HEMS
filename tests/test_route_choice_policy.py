"""Use real simulated alternatives; consent never makes invalid physics valid."""

from dataclasses import replace
from datetime import timedelta

from test_daily_main_charge_selection import portfolio_fixture
from test_daily_main_charge_windows import inputs

from picot.domain.evaluation import CandidateValidity
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.daily_charge_assignment import DailyChargeAssignment
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.route_choice_policy import (
    constrain,
    locked_candidates,
    main_signature,
    prepare_offer,
    requested_candidates,
)


def test_offer_contains_a_feasible_more_pv_route_and_expires_before_difference():
    snapshot, assignment, _, tariffs, _ = portfolio_fixture()
    pv = snapshot.pv_energy_timeline
    snapshot = replace(
        snapshot,
        pv_energy_timeline=replace(
            pv,
            intervals=tuple(
                replace(
                    row,
                    pv_energy_wh=1000.0 if index in (6, 7) else 0.0,
                    forecast_lower_energy_wh=1000.0 if index in (6, 7) else 0.0,
                    forecast_central_energy_wh=1000.0 if index in (6, 7) else 0.0,
                    forecast_upper_energy_wh=1000.0 if index in (6, 7) else 0.0,
                )
                for index, row in enumerate(pv.intervals)
            ),
        ),
    )
    windows = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot, assignment=assignment, conversion_model=inputs()["conversion_model"]
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows, tariffs=tariffs, opportunity_ids=("prices",)
    )
    at = snapshot.captured_at - timedelta(minutes=1)
    owner = DailyChargeAssignment("battery", snapshot.captured_at.date(), "Pacific/Honolulu", at)
    first = portfolio.sources[0]
    offer, expiry = prepare_offer(portfolio, first.candidate_id, owner, at)
    assert offer["alternative"] is not None
    assert offer["alternative"]["pv_storage_kwh"] > offer["automatic"]["pv_storage_kwh"]
    assert at < expiry <= snapshot.captured_at
    assert requested_candidates(portfolio, {"offer": offer}, at)


def test_only_the_chosen_owners_grid_windows_are_restricted():
    snapshot, owner, _, _, portfolio = portfolio_fixture()
    chosen = portfolio.sources[5]
    record = {
        "assignment_id": owner.assignment_id,
        "offer": {"alternative": {"main_signature": main_signature(chosen.window)}},
    }
    allowed = locked_candidates(portfolio, [record], snapshot.captured_at)
    assert chosen.candidate_id in allowed
    assert portfolio.sources[0].candidate_id not in allowed
    other = {**record, "assignment_id": "different-day"}
    assert len(locked_candidates(portfolio, [other], snapshot.captured_at)) == len(
        portfolio.sources
    )
    # A safely repaired incumbent may stay even when it needed extra grid charging.
    repaired = replace(portfolio, incumbent_candidate_id=portfolio.sources[0].candidate_id)
    assert portfolio.sources[0].candidate_id in locked_candidates(
        repaired, [record], snapshot.captured_at
    )


def test_consent_cannot_resurrect_an_invalid_candidate():
    _, _, _, _, portfolio = portfolio_fixture()
    first = portfolio.outcome_set.outcomes[0]
    invalid = replace(first, validity=CandidateValidity.INVALID, invalidity_reasons=("reserve",))
    portfolio = replace(
        portfolio,
        outcome_set=replace(
            portfolio.outcome_set, outcomes=(invalid, *portfolio.outcome_set.outcomes[1:])
        ),
    )
    restricted = constrain(portfolio, {first.candidate_id}, "user_choice")
    assert restricted.outcome_set.outcomes[0] == invalid
    assert all(o.validity is CandidateValidity.INVALID for o in restricted.outcome_set.outcomes)
