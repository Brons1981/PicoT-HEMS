from picot.addon.runtime_performance_dashboard import runtime_performance_state


def test_runtime_performance_state_exposes_stage_timings() -> None:
    state = runtime_performance_state(
        {
            "captured_at": "2026-08-13T08:00:00+02:00",
            "snapshot_id": "live-1",
            "runtime_perf_base_evidence_ms": 1.0,
            "runtime_perf_flow_observer_ms": 2.0,
            "runtime_perf_canonical_pv_deviation_ms": 3.0,
            "runtime_perf_snapshot_build_ms": 4.0,
            "runtime_perf_actual_pv_integration_ms": 5.0,
            "runtime_perf_price_fetch_ms": 6.0,
            "runtime_perf_adr037_planner_ms": 7.0,
            "runtime_perf_tab001_mode_control_ms": 8.0,
            "runtime_perf_total_composed_cycle_ms": 36.0,
        }
    )

    assert state["state"] == 36.0
    attributes = state["attributes"]
    assert attributes["observer_only"] is True
    assert attributes["actual_pv_integration_ms"] == 5.0
    assert attributes["adr037_planner_ms"] == 7.0
    assert attributes["total_composed_cycle_ms"] == 36.0
