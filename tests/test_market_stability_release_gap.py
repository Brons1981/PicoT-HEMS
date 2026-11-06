"""A market-bound bridge uses the same one-cent stability policy."""
import pytest
from test_bridge_financial_stability import evaluate
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario

from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline


@pytest.mark.parametrize("benefit", [0.000441718626, 0.002904163711, 0.000248552502])
def test_recorded_6_november_subcent_changes_retain_valid_plan(benefit):
    assert evaluate(benefit, stable=False).record.winning_candidate_id == "candidate-b"
    assert evaluate(benefit).record.winning_candidate_id == "candidate-a"


def test_market_revision_records_one_cent_equivalence(tmp_path):
    store, snapshot, _ = scenario(tmp_path)
    run = CanonicalPipeline(
        commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]),
    ).run(planning_input=snapshot, control_change_allowed=False)
    assert run.outcomes.market_revision_evidence
    assert run.evaluation.financial_equivalence_margin_eur == 0.01
    assert run.evaluation.status in {"winner_selected", "plan_retained"}
