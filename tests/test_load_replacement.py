from dataclasses import replace
from datetime import timedelta

import pytest
from picot.v2.controlled_load_history import paired_forecasts
from picot.v2.energy_portfolio import assess
from picot.v2.load_replacement import build_basis, replace_profile
from picot.v2.planning_input import HouseholdLoadObservation
from test_daily_main_charge_windows import inputs
from test_energy_portfolio import request
from test_ev_deadline_advice import scenario


def basis_for(snapshot):
    # A known attributed component of 40% within a synthetic physical forecast.
    historical = replace(
        snapshot.household_load_forecast, fallback_active=False, fallback_reason=None
    )
    component = replace(
        historical,
        intervals=tuple(
            replace(
                i,
                expected_energy_wh=i.expected_energy_wh * 0.4,
                source_reference="paired-history:" + "a" * 64,
                battery_excluded_energy_wh=0,
            )
            for i in historical.intervals
        ),
    )
    return build_basis(snapshot, historical, dict(total=historical, controlled=component))


def proposal(snapshot, basis, energy=100):
    value = request(
        snapshot,
        [
            dict(
                plan_id="hold",
                non_electric_cost_eur=0,
                slots=[
                    dict(
                        starts_at=(snapshot.captured_at + timedelta(hours=14)).isoformat(),
                        ends_at=(snapshot.captured_at + timedelta(hours=15)).isoformat(),
                        energy_wh=energy,
                    )
                ],
            )
        ],
    )
    value.update(
        contract="hc-energy-proposals:v2",
        demand_basis="replace_controlled_load",
        replacement_basis_id=basis.basis_id,
    )
    return value


def test_replacement_contract_is_evaluated_instead_of_added_twice(tmp_path):
    store, snapshot, _ = scenario(tmp_path, soc=0.9)
    before = store._load_payload()
    basis = basis_for(snapshot)
    answer = assess(
        snapshot, proposal(snapshot, basis), inputs()["conversion_model"], replacement_basis=basis
    )
    assert answer["status"] == "selected", answer
    assert answer["scope"] == "replacement_demand_on_retained_route"
    assert answer["execution_authorized"] is False
    assert store._load_payload() == before


def test_joint_basis_requires_explicit_model_identity_from_the_proposer(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    basis = replace(basis_for(snapshot), modeled_source_id="c" * 64)
    value = proposal(snapshot, basis)
    model = inputs()["conversion_model"]
    assert assess(snapshot, value, model, replacement_basis=basis)["status"] == "blocked"
    value["modeled_source_id"] = "c" * 64
    assert assess(snapshot, value, model, replacement_basis=basis)["status"] == "selected"
    value["modeled_source_id"] = "d" * 64
    assert assess(snapshot, value, model, replacement_basis=basis)["status"] == "blocked"


def test_replacement_preserves_other_load_and_only_changes_explicit_window(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    basis = basis_for(snapshot)
    start = snapshot.captured_at + timedelta(hours=14, minutes=3)
    end = start + timedelta(minutes=20)
    modified = replace_profile(snapshot, basis, [dict(start=start, end=end, energy=100)])

    def integral(forecast, left, right):
        return sum(
            i.expected_energy_wh
            * max(timedelta(), min(right, i.ends_at) - max(left, i.starts_at))
            / (i.ends_at - i.starts_at)
            for i in forecast.intervals
        )

    total = snapshot.household_load_forecast
    old = integral(total, start, end)
    assert integral(modified.household_load_forecast, start, end) == pytest.approx(old * 0.6 + 100)
    assert integral(modified.household_load_forecast, snapshot.captured_at, start) == pytest.approx(
        integral(total, snapshot.captured_at, start)
    )
    assert integral(modified.household_load_forecast, end, basis.ends_at) == pytest.approx(
        integral(total, end, basis.ends_at)
    )


def test_missing_attribution_cannot_hide_behind_equal_total():
    from datetime import UTC, datetime

    now = datetime(2026, 10, 22, 18, tzinfo=UTC)
    samples = [
        HouseholdLoadObservation(
            1000,
            now - timedelta(days=d) + timedelta(minutes=m),
            ("balance",),
            "test",
            controlled_power_w=500,
            controlled_source_id="a" * 64,
        )
        for d in (1, 2)
        for m in (0, 8, 14)
    ]
    kwargs = dict(
        source_id="a" * 64,
        run_id="r",
        snapshot_id="s",
        starts_at=now,
        horizon_end=now + timedelta(minutes=15),
    )
    assert paired_forecasts(samples, require_complete=True, **kwargs) is not None
    samples.append(
        HouseholdLoadObservation(
            1000, now - timedelta(days=1) + timedelta(minutes=4), ("balance",), "legacy"
        )
    )
    assert paired_forecasts(samples, **kwargs) is not None
    assert paired_forecasts(samples, require_complete=True, **kwargs) is None


def test_identity_replacement_has_zero_incremental_cost(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    basis = basis_for(snapshot)
    point = snapshot.captured_at + timedelta(hours=14)
    interval = next(i for i in basis.component if i.starts_at <= point < i.ends_at)
    value = proposal(snapshot, basis)
    value["plans"][0]["slots"] = [
        dict(
            starts_at=interval.starts_at.isoformat(),
            ends_at=interval.ends_at.isoformat(),
            energy_wh=interval.expected_energy_wh,
        )
    ]
    answer = assess(snapshot, value, inputs()["conversion_model"], replacement_basis=basis)
    assert answer["status"] == "selected", answer
    assert answer["assessments"][0]["total_incremental_cost_eur"] == 0


def test_replacement_batch_compares_electricity_and_non_electric_costs(tmp_path):
    import copy

    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    basis = basis_for(snapshot)
    value = proposal(snapshot, basis)
    other = copy.deepcopy(value["plans"][0])
    other.update(plan_id="other", non_electric_cost_eur=10)
    other["slots"][0]["energy_wh"] = 0
    value["plans"].append(other)
    answer = assess(snapshot, value, inputs()["conversion_model"], replacement_basis=basis)
    assert answer["selected_plan_id"] == "hold"
    assert len(answer["assessments"]) == 2
    assert answer["assessments"][1]["non_electric_cost_eur"] == 10


def test_smaller_replacement_constraint_is_actually_feasible(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    basis = basis_for(snapshot)
    value = proposal(snapshot, basis, 15000)
    slot = value["plans"][0]["slots"][0]
    slot.update(
        starts_at=(snapshot.captured_at + timedelta(hours=8)).isoformat(),
        ends_at=(snapshot.captured_at + timedelta(hours=9)).isoformat(),
    )
    answer = assess(snapshot, value, inputs()["conversion_model"], replacement_basis=basis)
    assert answer["status"] == "rejected", answer
    constraint = answer["assessments"][0]["constraint"]
    assert constraint["demand_basis"] == "replace_controlled_load"
    assert constraint["requires_hc_comfort_recheck"] is True
    slot["energy_wh"] *= constraint["verified_profile_scale"]
    revised = assess(snapshot, value, inputs()["conversion_model"], replacement_basis=basis)
    assert revised["status"] == "selected", revised


@pytest.mark.parametrize(
    "change", ["missing", "wrong_id", "changed_forecast", "gap", "different_windows", "negative"]
)
def test_replacement_rejects_ambiguous_or_stale_input(tmp_path, change):
    import copy

    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    basis = basis_for(snapshot)
    value = proposal(snapshot, basis)
    if change == "missing":
        basis = None
    elif change == "wrong_id":
        value["replacement_basis_id"] = "f" * 64
    elif change == "changed_forecast":
        f = snapshot.household_load_forecast
        snapshot = replace(
            snapshot,
            household_load_forecast=replace(
                f,
                intervals=(
                    replace(
                        f.intervals[0], expected_energy_wh=f.intervals[0].expected_energy_wh + 1
                    ),
                    *f.intervals[1:],
                ),
            ),
        )
    elif change == "gap":
        slot = copy.deepcopy(value["plans"][0]["slots"][0])
        slot["starts_at"] = (snapshot.captured_at + timedelta(hours=16)).isoformat()
        slot["ends_at"] = (snapshot.captured_at + timedelta(hours=17)).isoformat()
        value["plans"][0]["slots"].append(slot)
    elif change == "different_windows":
        p = copy.deepcopy(value["plans"][0])
        p["plan_id"] = "other"
        p["slots"][0]["ends_at"] = (snapshot.captured_at + timedelta(hours=16)).isoformat()
        value["plans"].append(p)
    else:
        value["plans"][0]["slots"][0]["energy_wh"] = -1
    answer = assess(snapshot, value, inputs()["conversion_model"], replacement_basis=basis)
    assert answer["status"] == "blocked", answer
    assert answer["assessments"] == [] and answer["execution_authorized"] is False


def test_current_excess_is_preserved_and_earliest_replacement_is_explicit(tmp_path):
    from picot.v2.household_load_guard import (
        HouseholdLoadGuardAssessment,
        apply_household_load_guard,
    )

    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    raw = snapshot.household_load_forecast
    guard = HouseholdLoadGuardAssessment(True, "reliable", 1000, snapshot.captured_at)
    guarded = replace(
        snapshot,
        household_load_guard=guard,
        household_load_forecast=apply_household_load_guard(raw, guard),
    )
    historical = replace(raw, fallback_active=False, fallback_reason=None)
    component = replace(
        historical,
        intervals=tuple(
            replace(
                i,
                expected_energy_wh=i.expected_energy_wh * 0.4,
                source_reference="paired-history:" + "a" * 64,
            )
            for i in historical.intervals
        ),
    )
    basis = build_basis(guarded, historical, dict(total=historical, controlled=component))
    assert basis.starts_at == snapshot.captured_at + timedelta(minutes=15)
    value = proposal(guarded, basis)
    value["plans"][0]["slots"][0]["starts_at"] = snapshot.captured_at.isoformat()
    result = assess(guarded, value, inputs()["conversion_model"], replacement_basis=basis)
    assert result["reason"] == "replacement_window_not_covered"
    assert result["condition"]["starts_at"] == basis.starts_at.isoformat()
    changed = replace_profile(
        guarded,
        basis,
        [dict(start=basis.starts_at, end=basis.starts_at + timedelta(minutes=10), energy=0)],
    )

    def early(f):
        return sum(i.expected_energy_wh for i in f.intervals if i.ends_at <= basis.starts_at)

    assert early(changed.household_load_forecast) == pytest.approx(
        early(guarded.household_load_forecast)
    )


def test_ev_energy_cannot_be_removed_by_replacement(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    historical = replace(
        snapshot.household_load_forecast, fallback_active=False, fallback_reason=None
    )
    component = replace(
        historical,
        intervals=tuple(
            replace(
                i,
                expected_energy_wh=i.expected_energy_wh * 0.4,
                source_reference="paired-history:" + "a" * 64,
            )
            for i in historical.intervals
        ),
    )
    active = replace(
        historical,
        intervals=tuple(
            replace(
                i, expected_energy_wh=i.expected_energy_wh + 100, battery_excluded_energy_wh=100
            )
            for i in historical.intervals
        ),
    )
    snapshot = replace(snapshot, household_load_forecast=active)
    basis = build_basis(snapshot, historical, dict(total=historical, controlled=component))
    changed = replace_profile(
        snapshot, basis, [dict(start=basis.starts_at, end=basis.ends_at, energy=0)]
    )
    assert sum(
        i.battery_excluded_energy_wh for i in changed.household_load_forecast.intervals
    ) == pytest.approx(sum(i.battery_excluded_energy_wh for i in active.intervals))
    assert sum(
        i.expected_energy_wh for i in changed.household_load_forecast.intervals
    ) == pytest.approx(
        sum(i.expected_energy_wh for i in historical.intervals) * 0.6 + 100 * len(active.intervals)
    )


def test_ingestion_publishes_basis_only_for_complete_actual_history(tmp_path, monkeypatch):
    from picot.v2.planning_input import (
        HomeAssistantStateReader,
        SourceBinding,
        SourceEvidence,
        assemble_planning_input,
    )
    from test_controlled_load_history import NOW, reading

    payload = reading()
    powers = dict(
        grid_power="2000",
        pv_power="0",
        storage_power_signed="0",
        storage_power_to_house="0",
        storage_power_from_house="0",
    )
    sources = {
        role: SourceEvidence(
            role, "test", role, "sensor." + role, power, "W", NOW, "available", "mapping"
        )
        for role, power in powers.items()
    }
    sources["controlled_load_measurement"] = SourceEvidence(
        "meter",
        "energy_devices",
        "controlled_load_measurement",
        "sensor.picot_hc_load_measurement",
        "available",
        None,
        NOW,
        "available",
        "meter",
        external_load_payload=payload,
    )
    monkeypatch.setattr(HomeAssistantStateReader, "read", lambda self, b: sources[b.semantic_role])
    options = tmp_path / "options.json"
    options.write_text("{}")
    samples = [
        HouseholdLoadObservation(
            2000,
            NOW - timedelta(minutes=minute),
            ("balance",),
            "test",
            controlled_power_w=1500,
            controlled_source_id=payload["source_id"],
        )
        for minute in range(1, 4 * 24 * 60)
        if minute % 15 in (0, 7)
    ]
    kwargs = dict(
        token="test",
        bindings=tuple(
            SourceBinding(s.category, s.semantic_role, s.entity_id) for s in sources.values()
        ),
        captured_at=NOW,
        options_path=str(options),
        household_load_observations=tuple(samples),
    )
    result = assemble_planning_input(**kwargs)
    assert result.load_replacement_basis is not None
    assert result.load_replacement_basis.matches(result.snapshot)
    assert result.load_replacement_basis.source_id == payload["source_id"]
    samples.append(
        HouseholdLoadObservation(
            2000, NOW - timedelta(days=1) + timedelta(minutes=4), ("balance",), "legacy"
        )
    )
    incomplete = assemble_planning_input(**dict(kwargs, household_load_observations=tuple(samples)))
    assert incomplete.controlled_load_summary["status"] == "history_ready"
    assert incomplete.load_replacement_basis is None


def test_published_basis_roundtrip_and_previous_snapshot_retention(tmp_path):
    from picot.v2.energy_outlook_runtime import EnergyOutlookPublisher
    from picot.v2.energy_portfolio_runtime import PortfolioAdvisor
    from picot_hc.energy_outlook import ENTITY, read_outlook
    from picot_hc.energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY, read_assessment

    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    basis = basis_for(snapshot)
    value = proposal(snapshot, basis)
    sent, answers = [], []
    now = snapshot.captured_at
    advisor = PortfolioAdvisor(
        lambda: value, answers.append, lambda s: inputs()["conversion_model"], now=lambda: now
    )
    worker = EnergyOutlookPublisher(
        sent.append, lambda s: inputs()["conversion_model"], now=lambda: now, portfolio=advisor
    )
    worker.refresh(snapshot, replacement_basis=basis)
    view = read_outlook(
        {ENTITY: dict(state=sent[0]["status"], attributes=sent[0])}, now.timestamp()
    )
    assert view["replacement_basis"]["basis_id"] == basis.basis_id
    assert answers[-1]["status"] == "selected"
    states = {
        REQUEST_ENTITY: dict(state="requested", attributes=value),
        RESPONSE_ENTITY: dict(state=answers[-1]["status"], attributes=answers[-1]),
    }
    assert read_assessment(states, now.timestamp())["status"] == "selected"
    answers[-1]["replacement_basis_id"] = "f" * 64
    assert read_assessment(states, now.timestamp())["status"] == "waiting"
    # The next publication may lack attribution; a request on the prior basis remains valid.
    now += timedelta(seconds=30)
    value = dict(value, revision=2, generated_at=now.isoformat())
    worker.refresh(
        replace(
            snapshot,
            snapshot_id="next",
            captured_at=now,
            daily_charge_context=None,
            pv_energy_timeline=None,
            household_load_forecast=None,
            capability_snapshot_set=None,
            storage_mode_capability_evidence=None,
        )
    )
    assert answers[-1]["status"] == "selected"
    assert answers[-1]["replacement_basis_id"] == basis.basis_id
    now += timedelta(seconds=100)
    value = dict(
        value,
        revision=3,
        generated_at=now.isoformat(),
        valid_until=(now + timedelta(seconds=30)).isoformat(),
    )
    worker.refresh(
        replace(
            snapshot,
            snapshot_id="third",
            captured_at=now,
            daily_charge_context=None,
            pv_energy_timeline=None,
            household_load_forecast=None,
            capability_snapshot_set=None,
            storage_mode_capability_evidence=None,
        )
    )
    assert answers[-1]["status"] == "blocked"
    assert answers[-1]["reason"] == "refresh_outlook_and_resubmit"
