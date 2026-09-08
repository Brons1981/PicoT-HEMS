"""Measured PV may reduce grid charging once, preserving daily ownership."""

from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

from test_daily_main_active_pipeline import setup
from test_daily_main_charge_selection import snapshot_for_main
from test_daily_main_charge_windows import inputs
from test_daily_main_route_optimisation import fresh
from test_daily_pv_comparison import actual

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import PriceForecastPoint
from picot.v2.daily_charge_assignment import DailyChargeRevisionReason
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def source_with_later_cheap_window():
    source = snapshot_for_main()
    return replace(
        source,
        price_points=tuple(
            PriceForecastPoint(
                f"price:{n}",
                source.captured_at + timedelta(minutes=15 * n),
                source.captured_at + timedelta(minutes=15 * (n + 1)),
                0.1 if 16 <= n < 32 else 0.5,
                1.0,
                f"published:{n}",
            )
            for n in range(96)
        ),
    )


def observed(source, *, soc=0.76, minutes=60, gap=False):
    result = fresh(source, soc=soc, tag=f"observed:{minutes}")
    at = source.captured_at + timedelta(minutes=minutes)
    return replace(
        result,
        captured_at=at,
        current_storage_states=tuple(
            replace(s, measured_at=at) for s in result.current_storage_states
        ),
        capability_snapshot_set=replace(result.capability_snapshot_set, captured_at=at),
        pv_energy_timeline=replace(
            result.pv_energy_timeline,
            intervals=tuple(
                actual(i, 1400) if n < 2 and not (gap and n == 0) else i
                for n, i in enumerate(result.pv_energy_timeline.intervals)
            ),
        ),
    )


def grid_wh(plan, at):
    return sum(
        s.requested_power_w * (s.ends_at - max(at, s.starts_at)).total_seconds() / 3600
        for s in plan.segments
        if s.ends_at > at and s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
    )


def test_surplus_reduces_grid_once_and_keeps_frozen_reference_after_restart(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    original = store.load_daily_assignments()[0]
    basis = store.load_daily_pv_comparison(original.assignment_id).basis
    old_plan = first.execution_plan_set.plans[0]
    observation = observed(source)
    result = pipeline.run(planning_input=recover(observation))
    assert result.evaluation.daily_pv_surplus_trigger is not None, result.evaluation.reason
    assert result.evaluation.daily_main_shortfall is None
    new_plan = result.execution_plan_set.plans[0]
    assert grid_wh(new_plan, observation.captured_at) < grid_wh(old_plan, observation.captured_at)
    revised = store.load_daily_assignments()[0]
    assert revised.assignment_id == original.assignment_id
    assert revised.revision == original.revision + 1
    assert revised.revision_reason is DailyChargeRevisionReason.PV_UPPER
    assert revised.completed_at is None
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    state = restarted.load_daily_pv_comparison(original.assignment_id)
    assert state.basis == basis
    assert result.evaluation.daily_pv_comparison.evidence_id in state.assessed_evidence_ids

    def forbidden(*args, **kwargs):
        raise AssertionError("same closed measurement must not be assessed or repriced again")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", forbidden)
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "pv_surplus_trigger", forbidden)
    pipeline = CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]),
        commitment_store=restarted,
    )
    repeated = pipeline.run(
        planning_input=_restore_daily_charge_context(
            observed(source, minutes=65), restarted, local_timezone=ZoneInfo("UTC")
        )
    )
    assert repeated.execution_plan_set.plans[0] == new_plan


def test_gap_keeps_plan_and_filling_gap_allows_one_comparison(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    result = pipeline.run(planning_input=recover(observed(source, gap=True)))
    assert result.evaluation.daily_pv_comparison.status == "partial"
    assert result.execution_plan_set.plans[0].plan_id == first.execution_plan_set.plans[0].plan_id
    assert result.execution_plan_set.plans[0].segments == first.execution_plan_set.plans[0].segments
    owner = store.load_daily_assignments()[0]
    assert not store.load_daily_pv_comparison(owner.assignment_id).assessed_evidence_ids
    complete = pipeline.run(planning_input=recover(observed(source, minutes=65)))
    assert complete.evaluation.daily_pv_surplus_trigger is not None


def test_surplus_without_removable_grid_is_assessed_once(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))

    def forbidden(*args, **kwargs):
        raise AssertionError("without a physical benefit there must be no price search")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", forbidden)
    result = pipeline.run(planning_input=recover(observed(source, soc=0.66)))
    assert result.evaluation.daily_pv_comparison.boundary == "above_central"
    assert result.evaluation.daily_pv_surplus_trigger is None
    assert result.execution_plan_set.plans[0].plan_id == first.execution_plan_set.plans[0].plan_id
    owner = store.load_daily_assignments()[0]
    state = store.load_daily_pv_comparison(owner.assignment_id)
    assert result.evaluation.daily_pv_comparison.evidence_id in state.assessed_evidence_ids
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "pv_surplus_trigger", forbidden)
    repeated = pipeline.run(planning_input=recover(observed(source, soc=0.76, minutes=65)))
    assert repeated.execution_plan_set.plans[0].plan_id == first.execution_plan_set.plans[0].plan_id


def test_optional_reference_corruption_keeps_valid_plan(tmp_path, monkeypatch):
    import json

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    path = tmp_path / "plans.json"
    payload = json.loads(path.read_text())
    owner = store.load_daily_assignments()[0]
    payload["daily_pv_comparison"][owner.assignment_id]["basis"] = {"broken": True}
    path.write_text(json.dumps(payload))
    recovered = recover(observed(source))
    assert recovered.daily_charge_context.status == "ready"
    assert recovered.daily_charge_context.pv_comparison_states[0].basis is None
    result = pipeline.run(planning_input=recovered)
    assert result.execution_plan_set.plans[0].plan_id == first.execution_plan_set.plans[0].plan_id
    assert result.evaluation.status == "plan_retained"


def test_optional_assessment_write_failure_keeps_valid_plan_and_does_not_consume_evidence(
    tmp_path,
    monkeypatch,
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))

    def failed_write(*args, **kwargs):
        raise OSError("assessment write failed")

    monkeypatch.setattr(store, "record_daily_pv_assessment", failed_write)
    result = pipeline.run(planning_input=recover(observed(source, soc=0.66)))
    assert result.execution_plan_set.plans[0].plan_id == first.execution_plan_set.plans[0].plan_id
    assert result.evaluation.status == "plan_retained"
    owner = store.load_daily_assignments()[0]
    assert not store.load_daily_pv_comparison(owner.assignment_id).assessed_evidence_ids


def test_poll_signature_sees_corrected_actual_sources_and_future_range(tmp_path, monkeypatch):
    from test_daily_charge_runtime_input import bundle

    from picot.v2.live_runtime import _planning_input_signature

    _, _, recover = setup(tmp_path, monkeypatch)
    source = recover(observed(source_with_later_cheap_window()))
    intervals = source.pv_energy_timeline.intervals
    source = replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=(
                *intervals[:2],
                replace(
                    intervals[2],
                    pv_energy_wh=10,
                    forecast_lower_energy_wh=8,
                    forecast_central_energy_wh=10,
                    forecast_upper_energy_wh=12,
                ),
                *intervals[3:],
            ),
        ),
    )
    original = _planning_input_signature(bundle(source))
    intervals = source.pv_energy_timeline.intervals
    corrected_actual = replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=(
                replace(intervals[0], actual_evidence_ids=("source-correction",)),
                *intervals[1:],
            ),
        ),
    )
    assert _planning_input_signature(bundle(corrected_actual)) != original
    corrected_future = replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=(
                *intervals[:2],
                replace(
                    intervals[2],
                    forecast_lower_energy_wh=0,
                    forecast_central_energy_wh=10,
                    forecast_upper_energy_wh=12,
                ),
                *intervals[3:],
            ),
        ),
    )
    assert _planning_input_signature(bundle(corrected_future)) != original
