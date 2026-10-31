from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as N

import pytest

from picot.v2.standby_explanation import standby_comparison


def evidence():
    start = datetime(2026, 10, 31, 19, tzinfo=UTC)
    end = start + timedelta(hours=2)

    def path(identity, primitive):
        segment = N(starts_at=start, ends_at=end, execution_scope_id="battery",
                    primitive=N(value=primitive), requested_power_w=None,
                    charge_source_policy=None, soc_constraint=None)
        return N(path_id=identity, horizon_start=start, horizon_end=end,
                 projected_states=[N(at=end, storage_energy_wh=5000)], segments=(segment,))

    active, other = path("active", "standby"), path("other", "balance_bidirectional")
    run = N(candidate_set=N(candidates=[N(candidate_id="a", energy_path_id="active"),
                                       N(candidate_id="b", energy_path_id="other")],
                            energy_paths=[active, other]),
            execution_plan_set=N(plans=[N(winning_energy_path_id="active")]))
    decision = dict(status="retained", incumbent_candidate_id="a", alternative_candidate_id="b",
                    incumbent_cost_eur=1.9, alternative_cost_eur=2.1)
    return run, decision


def test_only_standby_vs_support_with_same_terminal_energy_gets_total_benefit():
    run, decision = evidence()
    result = standby_comparison(run, decision)
    assert result["benefit_eur"] == pytest.approx(0.2)
    assert result["starts_at"] == "2026-10-31T19:00:00+00:00"


def test_replacement_uses_opposite_cost_direction():
    run, decision = evidence()
    decision.update(status="replaced", incumbent_candidate_id="b", alternative_candidate_id="a",
                    incumbent_cost_eur=2.1, alternative_cost_eur=1.9)
    assert standby_comparison(run, decision)["benefit_eur"] == pytest.approx(0.2)


@pytest.mark.parametrize("case", ["stock", "different_action", "no_cost", "wrong_identity",
                                  "more_expensive", "unpublished"])
def test_unproven_attribution_is_suppressed(case):
    run, decision = evidence()
    if case == "stock":
        run.candidate_set.energy_paths[1].projected_states[0].storage_energy_wh = 4000
    elif case == "different_action":
        run.candidate_set.energy_paths[1].segments[0].primitive.value = "charge_at_power"
    elif case == "no_cost":
        decision["incumbent_cost_eur"] = None
    elif case == "wrong_identity":
        run.execution_plan_set.plans[0].winning_energy_path_id = "unrelated"
    elif case == "more_expensive":
        decision["incumbent_cost_eur"] = 3.0
    else:
        decision["status"] = "publication_failed"
    assert standby_comparison(run, decision) is None
