import copy

import pytest
from picot_hc.core import Store
from picot_hc.cv_maintenance import CvMaintenance
from picot_hc.cv_plans import candidates, tail_allowance
from test_cv_energy_model import evidence as warm_evidence
from test_cv_maintenance import collect
from test_delayed_start import evidence as airco_evidence
from test_energy_proposals import NOW


def setup(tmp_path):
    now = NOW + 7200
    startup, steady, standby, sample, view, plan = airco_evidence(tmp_path, now)
    warmup, records, query = warm_evidence(tmp_path)
    warmup.save(records, [])
    maintenance = CvMaintenance(Store(tmp_path / "hc.sqlite"))
    for offset in (0, 1800, 3600):
        collect(maintenance, offset)
    plan["sources"]["cv"] = copy.deepcopy(plan["sources"]["beneden"])
    plan["costs"] = dict(cv=0.15)
    context = dict(
        sample=query,
        warmup=warmup,
        maintenance=maintenance,
        gas_price=1.4,
        modeled_source_id="c" * 64,
        joint_basis=True,
        prior_tail_wh=0,
    )
    return now, sample, view, plan, context, standby.estimate(now)


def test_cv_recipe_covers_complete_comfort_with_gas_and_electricity(tmp_path):
    now, sample, view, plan, context, standby = setup(tmp_path)
    options = candidates(
        sample, view, plan, context, standby, now, now + 120, view["next"]["ends_at"]
    )
    assert options
    for p in options:
        end = view["next"]["ends_at"]
        assert p["slots"][-1]["ends_at"] == end
        assert p["reaches_at"] <= view["next"]["starts_at"]
        assert p["source"] == "cv"
        hours = (end - p["reaches_at"]) / 3600
        assert p["non_electric_cost_eur"] == pytest.approx((0.625 + 0.625 * hours) * 1.4)
        total = sum(s["energy_wh"] for s in p["slots"])
        assert total == pytest.approx(
            standby * (end - now - 120) / 3600 + 100 * 1875 / 3600 + 125 * hours + 50 * 300 / 3600
        )


@pytest.mark.parametrize(
    "fault",
    ["gas", "expired_tariff", "warmup", "maintenance", "dhw", "active_dhw", "owned_upstairs"],
)
def test_missing_evidence_cannot_produce_cheap_cv_alternative(tmp_path, fault):
    now, sample, view, plan, context, standby = setup(tmp_path)
    if fault == "gas":
        context["gas_price"] = None
    elif fault == "expired_tariff":
        plan["costs"]["cv"] = None
    elif fault == "warmup":
        context["warmup"].records = []
    elif fault == "maintenance":
        context["maintenance"].evidence.records = []
    elif fault == "active_dhw":
        context["sample"]["gas_screening"]["active"] = True
    elif fault == "owned_upstairs":
        plan["owned"] = dict(boven=dict(command="other"))
    else:
        context["warmup"].records[0]["gas_screening"]["status"] = "dhw_observed"
    assert (
        candidates(sample, view, plan, context, standby, now, now + 120, view["next"]["ends_at"])
        == []
    )


def test_tail_only_covers_unaccounted_time_before_a_new_cv_start():
    context = dict(prior_tail_until=NOW + 300, prior_tail_power_w=50)
    assert tail_allowance(context, NOW + 120) == pytest.approx(2.5)
    assert tail_allowance(context, NOW + 120, NOW + 180) == pytest.approx(50 / 60)
    assert tail_allowance(context, NOW + 400) == 0


def test_cv_comparison_requires_whole_comfort_window_and_ignores_upstairs_temperature(tmp_path):
    now, sample, view, plan, context, standby = setup(tmp_path)
    end = view["next"]["ends_at"]
    assert candidates(sample, view, plan, context, standby, now, now + 120, end - 60) == []
    before = candidates(sample, view, plan, context, standby, now, now + 120, end)
    plan["zones"]["boven"] = dict(temperature=5, target=25, demand=True)
    assert candidates(sample, view, plan, context, standby, now, now + 120, end) == before


def test_owned_upstairs_allows_cv_after_minimum_run_and_feedback(tmp_path):
    now, sample, view, plan, context, standby = setup(tmp_path)
    plan["owned"] = {"boven": {"command": "upper", "since": now}}
    options = candidates(sample, view, plan, context, standby, now, now + 120,
                         view["next"]["ends_at"])
    assert options
    assert all(p["heat_starts_at"] >= now + 360 for p in options)
    fixed = options[0]["heat_starts_at"]
    # Renewal must not move the transfer deadline forward during off confirmation.
    assert candidates(sample, view, plan, context, standby, fixed - 30, fixed,
                      view["next"]["ends_at"], fixed_start=fixed)


def test_cv_candidate_transfer_budget_tracks_poll_interval(tmp_path):
    now, sample, view, plan, context, standby = setup(tmp_path)
    plan["owned"] = {"boven": {"command": "upper", "since": now - 200}}
    plan["cv_handover_seconds"] = 120
    end = view["next"]["ends_at"]
    assert not candidates(sample, view, plan, context, standby, now, now + 120,
                          end, fixed_start=now + 120)
    assert candidates(sample, view, plan, context, standby, now, now + 220,
                      end, fixed_start=now + 220)
