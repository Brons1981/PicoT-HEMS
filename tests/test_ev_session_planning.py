from dataclasses import replace
from datetime import timedelta

from test_external_load_policy import AT
from test_v2_material_replanning import _bundle

from picot.v2.external_load_policy import apply_external_load_policy, read_session_demand


def payload(state="planned", actual=0, remaining=8000):
    return {
        "contract": "energy-device-session-demand:v1",
        "source_id": "energy-devices:ev-session",
        "generated_at": AT.isoformat(),
        "session": {
            "session_id": "ev-one",
            "version": 1,
            "state": state,
            "confirmed": True,
            "planned_start": (AT + timedelta(hours=1)).isoformat(),
            "expected_power_w": 2000,
            "expected_duration_seconds": 14400,
            "remaining_energy_wh": remaining,
            "current_power_w": actual,
            "last_measured_at": AT.isoformat(),
        },
    }


def test_future_session_is_demand_without_claiming_regulation_authority():
    policy = read_session_demand(payload(), captured_at=AT, execution_scope_id="home")
    assert policy is not None
    assert policy.power_w == 0
    assert policy.storage_support_allowed is True
    assert policy.remaining_energy_wh == 8000


def test_cancelled_completed_unconfirmed_stale_malformed_are_isolated():
    for state in ("cancelled", "completed", "recognized"):
        assert (
            read_session_demand(payload(state), captured_at=AT, execution_scope_id="home") is None
        )
    for mutate in (
        lambda p: p.update(generated_at=(AT - timedelta(seconds=16)).isoformat()),
        lambda p: p["session"].update(confirmed=False),
        lambda p: p["session"].update(expected_power_w=float("nan")),
        lambda p: p["session"].update(planned_start="not-a-date"),
        lambda p: p["session"].update(expected_duration_seconds=-1),
    ):
        p = payload()
        mutate(p)
        assert read_session_demand(p, captured_at=AT, execution_scope_id="home") is None


def test_session_added_once_in_future_window_and_edit_replaces_contribution():
    from picot.v2.contracts import HouseholdLoadForecast, HouseholdLoadForecastInterval

    base = HouseholdLoadForecast(
        "base",
        "run",
        "snapshot",
        (
            HouseholdLoadForecastInterval(
                "interval", AT, AT + timedelta(hours=6), 1200, 1, "history", "test"
            ),
        ),
        False,
        None,
    )
    policy = read_session_demand(payload(), captured_at=AT, execution_scope_id="home")
    revised = read_session_demand(
        payload(remaining=4000), captured_at=AT, execution_scope_id="home"
    )
    first = apply_external_load_policy(base, policy, captured_at=AT)
    second = apply_external_load_policy(base, revised, captured_at=AT)
    assert sum(i.expected_energy_wh for i in first.intervals) == 9200
    assert sum(i.expected_energy_wh for i in second.intervals) == 5200
    assert first == apply_external_load_policy(base, policy, captured_at=AT)
    assert all(i.battery_excluded_energy_wh == 0 for i in first.intervals)


def test_planned_session_enters_existing_material_monitor_but_heartbeat_does_not(tmp_path):
    from picot.v2.household_load_history import HouseholdLoadHistoryStore
    from picot.v2.material_replanning import MaterialReplanningObservationProducer

    producer = MaterialReplanningObservationProducer(
        history=HouseholdLoadHistoryStore(tmp_path / "history")
    )
    base = _bundle(energy_wh=3900)
    p = read_session_demand(payload(), captured_at=AT, execution_scope_id="home")

    def observe(seconds, policy):
        snapshot = replace(
            base.snapshot,
            captured_at=AT + timedelta(seconds=seconds),
            external_load_policy=policy,
            active_plan_commitments=(),
            daily_charge_context=None,
        )
        return producer._external_policy_observations(replace(base, snapshot=snapshot))

    assert observe(0, p) == ()
    assert observe(29, p) == ()
    assert len(observe(30, p)) == 1
    assert observe(31, replace(p, revision="2", remaining_energy_wh=7900)) == ()
    changed = replace(p, planned_start=AT + timedelta(hours=2), revision="3")
    assert observe(60, changed) == ()
    assert len(observe(90, changed)) == 1
    assert observe(120, None) == ()
    assert len(observe(150, None)) == 1


def test_real_ingestion_keeps_raw_and_removes_identified_ev_from_residual(tmp_path, monkeypatch):
    import json

    from picot.v2 import planning_input as module

    opts = tmp_path / "options"
    opts.write_text(json.dumps({"energy_device_sessions_enabled": True}))
    values = {
        "grid_power": 2200,
        "pv_power": 0,
        "storage_power_signed": 0,
        "storage_power_to_house": 0,
        "storage_power_from_house": 0,
    }
    demand = payload("active", actual=2000)
    demand["session"]["planned_start"] = AT.isoformat()
    demand["session"]["remaining_energy_wh"] = 2000

    def read(_self, binding):
        return module.SourceEvidence(
            evidence_id=binding.semantic_role,
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state=str(values.get(binding.semantic_role, "ready")),
            raw_unit="W",
            observed_at=AT,
            availability="available",
            mapping_version="test",
            external_load_payload=demand if binding.semantic_role == "ev_session_demand" else None,
        )

    monkeypatch.setattr(module.HomeAssistantStateReader, "read", read)
    bindings = tuple(
        module.SourceBinding("test", role, "sensor." + role)
        for role in (*values, "ev_session_demand")
    )
    bundle = module.assemble_planning_input(
        "token",
        bindings=bindings,
        options_path=str(opts),
        captured_at=AT,
        storage_state_config=module.StorageStateConfig("home", "battery", 8160),
        household_load_fallback_power_w=200,
        household_load_observations=(
            module.HouseholdLoadObservation(
                2200, AT - timedelta(minutes=5), ("old",), "unattributed-history"
            ),
        ),
    )
    assert bundle.household_load_observation.external_power_observed is True
    assert bundle.household_load_observation.power_w == 2200
    assert bundle.household_load_observation.identified_external_power_w == 2000
    assert next(f for f in bundle.facts if f.semantic_role == "grid_power").value == 2200
    intervals = bundle.snapshot.household_load_forecast.intervals
    first = next(i for i in intervals if i.starts_at == AT)
    assert first.expected_energy_wh == 550
    assert first.battery_excluded_energy_wh == 0  # correction is off, never invent protection
    opts.write_text(json.dumps({"energy_device_sessions_enabled": False}))
    ignored = module.assemble_planning_input(
        "token",
        bindings=bindings,
        options_path=str(opts),
        captured_at=AT,
        storage_state_config=module.StorageStateConfig("home", "battery", 8160),
        household_load_fallback_power_w=200,
    )
    assert ignored.snapshot.external_load_policy is None


def test_session_forecast_passes_through_real_mep_evaluation_and_plan_builder(tmp_path):
    from test_v2_mep_canonical_pipeline import _pipeline, _snapshot

    base = _snapshot(maximum_soc=1.0, current_soc=0.51)
    p = payload(remaining=2000)
    p["generated_at"] = base.captured_at.isoformat()
    p["session"]["planned_start"] = (base.captured_at + timedelta(hours=2)).isoformat()
    p["session"]["last_measured_at"] = base.captured_at.isoformat()
    policy = read_session_demand(p, captured_at=base.captured_at, execution_scope_id="battery")
    forecast = apply_external_load_policy(
        base.household_load_forecast, policy, captured_at=base.captured_at
    )
    assert sum(i.expected_energy_wh for i in forecast.intervals) == (
        sum(i.expected_energy_wh for i in base.household_load_forecast.intervals) + 2000
    )
    pipeline, _store = _pipeline(tmp_path)
    run = pipeline.run(
        planning_input=replace(base, household_load_forecast=forecast, external_load_policy=policy)
    )
    assert run.planning_input.external_load_policy.session_id == "ev-one"
    assert run.evaluation.winning_candidate_id
    assert run.evaluation.winning_energy_path_id
    assert run.execution_plan_set.plans
    assert run.evaluation.run_id == run.execution_plan_set.run_id == run.planning_input.run_id
    assert run.evaluation.snapshot_id == run.execution_plan_set.snapshot_id


def test_missing_ev_measurement_cannot_double_count_an_active_session():
    p = payload("active")
    p["session"]["current_power_w"] = None
    assert read_session_demand(p, captured_at=AT, execution_scope_id="home") is None
    p["session"]["state"] = "planned"
    p["session"]["switch_state"] = "off"
    policy = read_session_demand(p, captured_at=AT, execution_scope_id="home")
    assert policy is not None and policy.physical_evidence_available
