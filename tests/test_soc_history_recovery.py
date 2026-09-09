"""Recorder proof, revision provenance and durable historical completion."""

import json
from dataclasses import replace
from datetime import timedelta
from io import BytesIO

import pytest
from test_daily_main_active_pipeline import setup

from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot.v2.soc_history_recovery import HistoricalSOCRecovery


def test_recorder_full_inside_main_recovers_once_after_restart(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    segment = owner.main_segments[0]
    at = segment.starts_at + timedelta(seconds=1)
    now = segment.ends_at + timedelta(minutes=1)
    requests = []

    def read(request, timeout):
        requests.append(request.full_url)
        assert timeout == 5
        return BytesIO(
            json.dumps(
                [
                    [
                        {
                            "entity_id": "sensor.soc",
                            "state": "100",
                            "last_changed": at.isoformat(),
                        }
                    ]
                ]
            ).encode()
        )

    monkeypatch.setattr("picot.v2.soc_history_recovery.urlopen", read)
    recovery = HistoricalSOCRecovery("test-token")
    recovery.recover(store, entity_id="sensor.soc", execution_scope_id="battery", now=now)
    assert recovery.status == "historical_main_completion_recovered"
    complete = store.load_daily_assignments()[0]
    assert complete.completed_at == at
    assert complete.historical_completion_plan_id == owner.route_plan_id
    assert complete.historical_completion_segment == segment
    assert complete.route_plan_id == owner.route_plan_id
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    recovery.recover(restarted, entity_id="sensor.soc", execution_scope_id="battery", now=now)
    assert len(requests) == 1
    assert restarted.load_daily_assignments()[0] == complete


@pytest.mark.parametrize("case", ["99.9", "unavailable", "future", "before_main", "wrong_entity"])
def test_recorder_does_not_invent_completion(tmp_path, monkeypatch, case):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    segment = owner.main_segments[0]
    now = segment.ends_at + timedelta(minutes=1)
    at = segment.starts_at + timedelta(seconds=1)
    if case == "future":
        at = now + timedelta(seconds=1)
    if case == "before_main":
        at = segment.starts_at - timedelta(seconds=1)
    payload = [
        [
            {
                "entity_id": "other" if case == "wrong_entity" else "sensor.soc",
                "state": case if case in ("99.9", "unavailable") else "100",
                "last_changed": at.isoformat(),
            }
        ]
    ]
    monkeypatch.setattr(
        "picot.v2.soc_history_recovery.urlopen",
        lambda *a, **k: BytesIO(json.dumps(payload).encode()),
    )
    HistoricalSOCRecovery("token").recover(
        store,
        entity_id="sensor.soc",
        execution_scope_id="battery",
        now=now,
    )
    assert store.load_daily_assignments()[0] == owner


def test_recorder_failure_is_bounded_and_does_not_complete(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    now = owner.main_segments[0].ends_at + timedelta(minutes=1)
    calls = []

    def fail(*a, **k):
        calls.append(1)
        raise TimeoutError("history unavailable")

    monkeypatch.setattr("picot.v2.soc_history_recovery.urlopen", fail)
    recovery = HistoricalSOCRecovery("token")
    for at in (now, now + timedelta(seconds=60)):
        recovery.recover(store, entity_id="sensor.soc", execution_scope_id="battery", now=at)
    assert calls == [1]
    assert recovery.status.startswith("soc_history_unavailable")
    assert store.load_daily_assignments()[0] == owner


@pytest.mark.parametrize("extra_tomorrow_pv", [False, True])
def test_historical_full_removes_later_retry_through_canonical_pipeline(
    tmp_path,
    monkeypatch,
    extra_tomorrow_pv,
):
    from test_daily_bridge_pipeline import shift

    from picot.domain.execution_primitive import ExecutionPrimitive

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = shift(recover(), timedelta(hours=2))
    start = source.captured_at
    source = replace(
        source,
        daily_charge_context=None,
        price_points=tuple(
            replace(
                source.price_points[0],
                point_id=f"price-{n}",
                starts_at=start + timedelta(minutes=15 * n),
                ends_at=start + timedelta(minutes=15 * (n + 1)),
                value_eur_per_kwh=0.1 if (start + timedelta(minutes=15 * n)).hour >= 22 else 0.3,
            )
            for n in range(144)
        ),
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=tuple(
                replace(
                    source.household_load_forecast.intervals[0],
                    interval_id=f"load-{n}",
                    starts_at=start + timedelta(minutes=15 * n),
                    ends_at=start + timedelta(minutes=15 * (n + 1)),
                    expected_energy_wh=25,
                )
                for n in range(144)
            ),
        ),
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=tuple(
                replace(
                    source.pv_energy_timeline.intervals[0],
                    interval_id=f"pv-{n}",
                    starts_at=start + timedelta(minutes=30 * n),
                    ends_at=start + timedelta(minutes=30 * (n + 1)),
                    pv_energy_wh=1000 if 12 <= (start + timedelta(minutes=30 * n)).hour < 16 else 0,
                    forecast_lower_energy_wh=1000
                    if 12 <= (start + timedelta(minutes=30 * n)).hour < 16
                    else 0,
                    forecast_central_energy_wh=1000
                    if 12 <= (start + timedelta(minutes=30 * n)).hour < 16
                    else 0,
                    forecast_upper_energy_wh=1000
                    if 12 <= (start + timedelta(minutes=30 * n)).hour < 16
                    else 0,
                )
                for n in range(72)
            ),
        ),
    )
    pipeline.run(planning_input=recover(source))
    original = store.load_daily_assignments()[0]
    proof_at = original.main_segments[-1].ends_at - timedelta(seconds=1)
    pipeline.run(planning_input=recover(source))
    now = start + timedelta(hours=6)
    source = replace(
        source,
        captured_at=now,
        daily_charge_context=None,
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=now),
        current_storage_states=tuple(
            replace(s, current_soc=0.89, measured_at=now) for s in source.current_storage_states
        ),
    )
    retry = pipeline.run(planning_input=recover(source))
    assert retry.execution_plan_set.plans, retry.evaluation.reason
    assert any(
        s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
        for s in store.load_active_daily_main_plan("battery").segments
    )
    next_owner = store.load_daily_assignments()[1]
    next_id = next_owner.assignment_id
    recovered = store.recover_historical_main_completion(
        assignment_id=original.assignment_id,
        measured_at=proof_at,
        observed_at=now,
        soc=1,
        evidence_id="ha-soc-history:full-during-outage",
    )
    assert recovered.completed_at == proof_at
    assert recovered.historical_completion_plan_id == original.route_plan_id
    if extra_tomorrow_pv:
        source = replace(
            source,
            pv_energy_timeline=replace(
                source.pv_energy_timeline,
                intervals=tuple(
                    replace(
                        i,
                        pv_energy_wh=i.pv_energy_wh * 3,
                        forecast_lower_energy_wh=i.forecast_lower_energy_wh * 3,
                        forecast_central_energy_wh=i.forecast_central_energy_wh * 3,
                        forecast_upper_energy_wh=i.forecast_upper_energy_wh * 3,
                    )
                    if i.starts_at.date() > start.date()
                    else i
                    for i in source.pv_energy_timeline.intervals
                ),
            ),
        )
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    plan = store.load_active_daily_main_plan("battery")
    assert all(
        s.primitive is not ExecutionPrimitive.CHARGE_AT_POWER
        for s in plan.segments
        if s.starts_at.date() == start.date()
    )
    next_owner = store.load_daily_assignments()[1]
    assert next_owner.assignment_id == next_id
    assert next_owner.completed_at is None
    assert next_owner.main_segments
    assert plan.winning_candidate_id == result.evaluation.winning_candidate_id
    assert store.load_daily_assignments()[0].completed_at == proof_at
    repeated = pipeline.run(planning_input=recover(source))
    assert repeated.evaluation.status == "plan_retained", repeated.evaluation.reason

    # The repaired day goal must not prevent a later market evaluation.
    from test_market_rule_selection import trading_source

    market_source = trading_source(source)
    market_source = replace(
        market_source,
        price_points=tuple(
            replace(
                point,
                value_eur_per_kwh=0.8 if point.starts_at.hour == 18 else 0.1,
            )
            for point in market_source.price_points
        ),
    )
    traded = pipeline.run(planning_input=recover(market_source))
    assert traded.evaluation.reason == "user_market_rule_selected", traded.evaluation.reason
    assert store.load_daily_assignments()[0].completed_at == proof_at
    (binding,) = store.load_market_plan_bindings()
    assert sum(binding.segment_export_wh) == pytest.approx(binding.expected_export_wh)


def test_recovered_goal_cannot_dispatch_stale_charge_before_reconciliation(tmp_path, monkeypatch):
    from test_daily_main_active_pipeline import with_mode

    from picot.v2.canonical_execution_runtime import CanonicalExecutionRuntime

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    segment = owner.main_segments[0]
    plan = store.load_active_daily_main_plan("battery")
    main = next(s for s in plan.segments if s.segment_id == segment.segment_id)
    at = segment.starts_at + timedelta(seconds=2)
    store.recover_historical_main_completion(
        assignment_id=owner.assignment_id,
        measured_at=at - timedelta(seconds=1),
        observed_at=at,
        soc=1,
        evidence_id="ha-history:full",
    )
    source = replace(
        selected.planning_input,
        daily_charge_context=None,
        captured_at=at,
        capability_snapshot_set=replace(
            selected.planning_input.capability_snapshot_set, captured_at=at
        ),
        current_storage_states=tuple(
            replace(s, current_soc=0.8, measured_at=at)
            for s in selected.planning_input.current_storage_states
        ),
    )
    source = with_mode(recover(source), main.primitive, current_mode="Test active")
    commands = []
    runtime = CanonicalExecutionRuntime(lambda *a: commands.append(a), commitment_store=store)
    outcome = runtime.advance_committed_boundary(source, execution_enabled=True)
    assert outcome.failure_reason == "historical_main_completed_waiting_for_reconciliation"
    assert commands == []
