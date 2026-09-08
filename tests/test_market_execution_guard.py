from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import with_mode
from test_market_plan_binding import prepared

from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.market_execution_guard import guarded_market_primitive
from picot.v2.market_export_measurement import measured_market_export
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot.v2.power_history import PowerHistoryPoint, PowerHistorySeries, PowerHistorySnapshot
from picot.v2.zendure_mode_capabilities import ZendureModeMapping


def history(start, end, battery=2400, export=1200):
    return PowerHistorySnapshot(
        start,
        end,
        "available",
        None,
        tuple(
            PowerHistorySeries(
                role,
                role,
                "sensor." + role,
                "positive",
                (PowerHistoryPoint(start, watts, role + ":measured"),),
            )
            for role, watts in [("battery_discharge", battery), ("grid_export", export)]
        ),
    )


def bound(tmp_path, monkeypatch):
    store, recover, original, args = prepared(tmp_path, monkeypatch)
    assignment = store.load_market_daily_assignments()[0]
    binding = replace(args["binding"], expected_battery_draw_wh=assignment.battery_energy_wh)
    store.bind_market_plan(**dict(args, binding=binding))
    source = recover()
    start = next(s.starts_at for s in args["plan"].segments if s.segment_id in binding.segment_ids)

    def observed(at, soc=0.8, export_mode=True, changed=None, telemetry=True):
        snapshot = replace(
            source,
            captured_at=at,
            daily_charge_context=None,
            capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
            current_storage_states=tuple(
                replace(s, current_soc=soc, measured_at=at) for s in source.current_storage_states
            ),
            market_power_history=history(start, at) if telemetry else None,
        )
        snapshot = with_mode(
            snapshot, Primitive.DISCHARGE_AT_POWER, current_mode="Export" if export_mode else "NOM"
        )
        snapshot = replace(
            snapshot,
            storage_mode_capability_evidence=replace(
                snapshot.storage_mode_capability_evidence,
                state_changed_at=changed or start,
                mappings=(
                    ZendureModeMapping(
                        "Export", (Primitive.DISCHARGE_AT_POWER,), "integration_configured_maximum"
                    ),
                    ZendureModeMapping(
                        "NOM", (Primitive.BALANCE_BIDIRECTIONAL,), "integration_configured_maximum"
                    ),
                ),
            ),
        )
        return recover(snapshot)

    return store, binding, start, observed


def test_measurement_never_counts_household_discharge_as_export(tmp_path, monkeypatch):
    _, _, start, _ = bound(tmp_path, monkeypatch)
    end = start + timedelta(minutes=5)
    assert measured_market_export(history(start, end), start, end) == pytest.approx(100)
    assert measured_market_export(history(start, end, export=0), start, end) == 0
    assert measured_market_export(history(start, end, battery=0), start, end) == 0
    assert measured_market_export(None, start, end) is None
    assert measured_market_export(history(start, end), start, end + timedelta(seconds=1)) is None


def test_insufficient_soc_skips_full_action_and_restart_cannot_reopen(tmp_path, monkeypatch):
    store, binding, start, observed = bound(tmp_path, monkeypatch)
    snapshot = observed(start, soc=0.11, export_mode=False)
    action = guarded_market_primitive(
        snapshot=snapshot,
        store=store,
        scope_id="battery",
        requested=Primitive.DISCHARGE_AT_POWER,
        export_mode_confirmed=False,
    )
    assert action is Primitive.BALANCE_BIDIRECTIONAL
    assert store.load_market_daily_assignments()[0].status == "skipped"
    assert store.load_market_daily_assignments()[0].measured_export_wh is None
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    assert (
        guarded_market_primitive(
            snapshot=observed(start + timedelta(seconds=10)),
            store=restarted,
            scope_id="battery",
            requested=Primitive.DISCHARGE_AT_POWER,
            export_mode_confirmed=True,
        )
        is Primitive.BALANCE_BIDIRECTIONAL
    )
    assert restarted.load_market_plan_bindings() == (binding,)


def test_stop_at_minimum_uses_existing_dispatch_and_waits_for_actual_mode(tmp_path, monkeypatch):
    store, binding, start, observed = bound(tmp_path, monkeypatch)
    goals = store.load_daily_assignments()
    guarded_market_primitive(
        snapshot=observed(start),
        store=store,
        scope_id="battery",
        requested=Primitive.DISCHARGE_AT_POWER,
        export_mode_confirmed=True,
    )
    calls = []
    runtime = CanonicalExecutionRuntime(
        dispatch=lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "stop")
        ),
        commitment_store=store,
    )
    at = start + timedelta(minutes=1)
    result = runtime.advance_committed_boundary(observed(at, soc=0.1), execution_enabled=True)
    assert result.status == "dispatched", result.failure_reason
    assert calls[0].primitive is Primitive.BALANCE_BIDIRECTIONAL
    assert calls[0].requested_power_w is None
    assert store.load_market_daily_assignments()[0].status == "pending"
    runtime.advance_committed_boundary(
        observed(at + timedelta(seconds=1), soc=0.1), execution_enabled=True
    )
    assert len(calls) == 1
    stopped = at + timedelta(seconds=2)
    guarded_market_primitive(
        snapshot=observed(stopped, soc=0.1, export_mode=False, changed=stopped),
        store=store,
        scope_id="battery",
        requested=Primitive.DISCHARGE_AT_POWER,
        export_mode_confirmed=False,
    )
    done = store.load_market_daily_assignments()[0]
    assert done.status == "stopped"
    assert done.measured_export_wh == pytest.approx(1200 * 62 / 3600)
    assert store.load_daily_assignments() == goals


def test_missing_final_measurement_never_turns_old_partial_reading_into_completion(
    tmp_path, monkeypatch
):
    store, _, start, observed = bound(tmp_path, monkeypatch)
    guarded_market_primitive(
        snapshot=observed(start),
        store=store,
        scope_id="battery",
        requested=Primitive.DISCHARGE_AT_POWER,
        export_mode_confirmed=True,
    )
    at = start + timedelta(minutes=1)
    guarded_market_primitive(
        snapshot=observed(at),
        store=store,
        scope_id="battery",
        requested=Primitive.DISCHARGE_AT_POWER,
        export_mode_confirmed=True,
    )
    stopped = at + timedelta(seconds=1)
    guarded_market_primitive(
        snapshot=observed(stopped, export_mode=False, changed=stopped, telemetry=False),
        store=store,
        scope_id="battery",
        requested=Primitive.BALANCE_BIDIRECTIONAL,
        export_mode_confirmed=False,
    )
    assert store.load_market_daily_assignments()[0].status == "pending"
    progress = store.load_market_progress(store.load_market_daily_assignments()[0].assignment_id)
    assert progress.stopped_at == stopped and progress.measured_export_wh is None
    guarded_market_primitive(
        snapshot=observed(stopped + timedelta(seconds=1), export_mode=False, changed=stopped),
        store=store,
        scope_id="battery",
        requested=Primitive.BALANCE_BIDIRECTIONAL,
        export_mode_confirmed=False,
    )
    assert store.load_market_daily_assignments()[0].status == "stopped"
    assert store.load_market_daily_assignments()[0].measured_export_wh == pytest.approx(
        1200 * 61 / 3600
    )


def test_invalid_readiness_and_recorded_gap_never_fabricate_export(tmp_path, monkeypatch):
    store, _, start, observed = bound(tmp_path, monkeypatch)
    invalid = history(start, start, battery=float("nan"))
    assert measured_market_export(invalid, start, start) is None
    empty = replace(invalid, series=tuple(replace(s, points=()) for s in invalid.series))
    assert measured_market_export(empty, start, start) is None
    guarded_market_primitive(
        snapshot=observed(start),
        store=store,
        scope_id="battery",
        requested=Primitive.DISCHARGE_AT_POWER,
        export_mode_confirmed=True,
    )
    stopped = start + timedelta(minutes=1)
    snapshot = observed(stopped, export_mode=False, changed=stopped)
    telemetry = snapshot.market_power_history
    gap = replace(
        telemetry,
        series=tuple(
            replace(
                s,
                points=s.points
                + (
                    PowerHistoryPoint(start + timedelta(seconds=20), float("nan"), "unavailable"),
                    PowerHistoryPoint(start + timedelta(seconds=40), 1200, "resumed"),
                ),
            )
            for s in telemetry.series
        ),
    )
    assert measured_market_export(gap, start, stopped) is None
    guarded_market_primitive(
        snapshot=replace(snapshot, market_power_history=gap),
        store=store,
        scope_id="battery",
        requested=Primitive.BALANCE_BIDIRECTIONAL,
        export_mode_confirmed=False,
    )
    done = store.load_market_daily_assignments()[0]
    assert done.status == "stopped"
    assert done.measured_export_wh is None
    assert store.load_market_progress(done.assignment_id).measurement_unavailable


def test_full_measured_budget_closes_only_after_confirmed_stop(tmp_path, monkeypatch):
    store, binding, start, observed = bound(tmp_path, monkeypatch)
    goals = store.load_daily_assignments()
    guarded_market_primitive(
        snapshot=observed(start),
        store=store,
        scope_id="battery",
        requested=Primitive.DISCHARGE_AT_POWER,
        export_mode_confirmed=True,
    )
    at = start + timedelta(seconds=binding.expected_export_wh * 3600 / 1200)
    action = guarded_market_primitive(
        snapshot=observed(at),
        store=store,
        scope_id="battery",
        requested=Primitive.DISCHARGE_AT_POWER,
        export_mode_confirmed=True,
    )
    assert action is Primitive.BALANCE_BIDIRECTIONAL
    assert store.load_market_daily_assignments()[0].status == "pending"
    stopped = observed(at, export_mode=False, changed=at)
    guarded_market_primitive(
        snapshot=stopped,
        store=store,
        scope_id="battery",
        requested=Primitive.BALANCE_BIDIRECTIONAL,
        export_mode_confirmed=False,
    )
    done = store.load_market_daily_assignments()[0]
    assert done.status == "completed"
    assert done.measured_export_wh == binding.expected_export_wh
    assert store.load_daily_assignments() == goals
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    assert (
        guarded_market_primitive(
            snapshot=observed(at + timedelta(seconds=1)),
            store=restarted,
            scope_id="battery",
            requested=Primitive.DISCHARGE_AT_POWER,
            export_mode_confirmed=True,
        )
        is Primitive.BALANCE_BIDIRECTIONAL
    )
