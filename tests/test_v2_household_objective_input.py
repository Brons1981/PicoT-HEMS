from dataclasses import replace
from datetime import UTC, datetime

from legacy_cp_pipeline import CanonicalPipeline

from picot.v2.household_objective_input import (
    attach_household_objectives,
)
from picot.v2.household_planning_regime import (
    AdaptiveHouseholdObjectivePolicy,
    UserObjectiveProfile,
)
from picot.v2.live_runtime import _planning_input_signature
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.projection import project


def _profile() -> UserObjectiveProfile:
    return UserObjectiveProfile(
        profile_id="profile:household:v1",
        version=1,
        cost_optimization_weight=80,
        self_consumption_weight=70,
        reserve_availability_weight=60,
        trading_enabled=False,
        adaptive_priority_enabled=True,
    )


def test_household_objectives_are_part_of_immutable_planning_input() -> None:
    snapshot = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
    ).planning_input

    enriched = attach_household_objectives(
        snapshot,
        profile=_profile(),
        policy=AdaptiveHouseholdObjectivePolicy(),
        forecast_confidence=0.35,
        cumulative_forecast_energy_wh=4000.0,
        cumulative_actual_energy_wh=2500.0,
        underperformance_duration_seconds=3600,
        evidence_ids=("solcast-1", "goodwe-1"),
    )

    assert enriched is not snapshot
    assert enriched.strategy_id == "profile:household:v1:1"
    assert enriched.user_objective_profile == _profile()
    assert enriched.household_planning_regime is not None
    assert enriched.household_planning_regime.regime == (
        "self_consumption_first"
    )


def test_regime_change_is_a_material_planning_input_change() -> None:
    snapshot = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
    ).planning_input
    cost_first = attach_household_objectives(
        snapshot,
        profile=_profile(),
        policy=AdaptiveHouseholdObjectivePolicy(),
        forecast_confidence=0.90,
        cumulative_forecast_energy_wh=4000.0,
        cumulative_actual_energy_wh=3900.0,
        underperformance_duration_seconds=3600,
        evidence_ids=("solcast-1", "goodwe-1"),
    )
    self_first = attach_household_objectives(
        snapshot,
        profile=_profile(),
        policy=AdaptiveHouseholdObjectivePolicy(),
        forecast_confidence=0.35,
        cumulative_forecast_energy_wh=4000.0,
        cumulative_actual_energy_wh=2500.0,
        underperformance_duration_seconds=3600,
        evidence_ids=("solcast-1", "goodwe-2"),
    )
    now = datetime(2026, 8, 17, 8, 1, tzinfo=UTC)
    first = PlanningInputBundle(
        cost_first,
        (),
        (),
        now,
        now,
    )
    second = replace(first, snapshot=self_first)

    assert _planning_input_signature(first) != _planning_input_signature(second)


def test_planning_input_card_projects_profile_regime_and_evidence() -> None:
    snapshot = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
    ).planning_input
    enriched = attach_household_objectives(
        snapshot,
        profile=_profile(),
        policy=AdaptiveHouseholdObjectivePolicy(),
        forecast_confidence=0.35,
        cumulative_forecast_energy_wh=4000.0,
        cumulative_actual_energy_wh=2500.0,
        underperformance_duration_seconds=3600,
        evidence_ids=("solcast-1", "goodwe-1"),
    )
    run = CanonicalPipeline().run(planning_input=enriched)

    attributes = project(run).cards[0].attributes

    assert attributes["strategy_id"] == "profile:household:v1:1"
    assert attributes["household_planning_regime"] == (
        "self_consumption_first"
    )
    assert attributes["household_objective_order"] == [
        "self_consumption",
        "cost_optimization",
        "reserve_availability",
    ]
    assert attributes["household_regime_forecast_confidence"] == 0.35
    assert attributes["household_regime_deviation_energy_wh"] == -1500.0
    assert attributes["household_regime_evidence_ids"] == [
        "solcast-1",
        "goodwe-1",
    ]
