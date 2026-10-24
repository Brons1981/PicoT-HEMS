import copy
import hashlib
import json

import pytest
from picot_hc.energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY
from picot_hc.energy_proposals import stamp
from test_energy_proposals import NOW, sample
from test_warmup_plans import setup


def rejected(request, end, kind="end_before"):
    answer = dict(
        contract="hc-energy-assessment:v1",
        status="rejected",
        execution_authorized=False,
        request_id=request["request_id"],
        revision=request["revision"],
        basis_snapshot_id=request["basis_snapshot_id"],
        replacement_basis_id=request["replacement_basis_id"],
        scope="replacement_demand_on_retained_route",
        valid_until=request["valid_until"],
        request_fingerprint=hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        selected_plan_id=None,
        assessments=[
            dict(
                plan_id=p["plan_id"],
                status="rejected",
                constraint=dict(kind=kind, ends_at=stamp(end)),
            )
            for p in request["plans"]
        ],
    )
    return {
        REQUEST_ENTITY: dict(state="requested", attributes=copy.deepcopy(request)),
        RESPONSE_ENTITY: dict(state="rejected", attributes=answer),
    }


@pytest.mark.parametrize("case", ["shorter", "deadline", "scaled", "forged", "partial"])
def test_rejection_rebuilds_only_measured_comfort_valid_profiles(tmp_path, case):
    generator, warmup, view, plan, outlook, sent = setup(tmp_path)
    current = dict(sample(), indoor=18)

    def tick(now, states=None):
        generator.tick(
            None, view, plan, outlook, now, warmup=warmup, warmup_sample=current, states=states
        )

    tick(NOW)
    original = copy.deepcopy(generator.pending)
    end = NOW + (3500 if case == "deadline" else 4200)
    states = rejected(
        original, end, "verified_scaled_profile" if case == "scaled" else "end_before"
    )
    if case == "forged":
        states[RESPONSE_ENTITY]["attributes"]["request_fingerprint"] = "wrong"
    if case == "partial":
        states[RESPONSE_ENTITY]["attributes"]["assessments"].pop()
    tick(NOW + 30, states)
    if case == "shorter":
        new = copy.deepcopy(generator.pending)
        assert new["request_id"] != original["request_id"]
        assert len(new["plans"]) == 3
        assert all(p["slots"][-1]["ends_at"] == stamp(end) for p in new["plans"])
        assert all(p["slots"][0]["energy_wh"] == 800 for p in new["plans"])
        assert new["valid_until"] == original["valid_until"]
        tick(NOW + 60, states)  # late repeat of old reply cannot replace the new request
        assert generator.pending == new
        tick(NOW + 70, rejected(new, end))  # identical rejection must not spin
        assert generator.pending is None
    elif case == "forged":
        assert generator.pending == original
    else:
        assert generator.pending is None
        assert sent[-1]["state"] == "withdrawn"
    assert "cv" not in str(sent[-1]["attributes"])


@pytest.mark.parametrize("case", ["expired", "new_basis", "invalid_end", "foreign_request"])
def test_feedback_is_scoped_to_request_basis_and_validity(tmp_path, case):
    generator, warmup, view, plan, outlook, sent = setup(tmp_path)
    current = dict(sample(), indoor=18)
    generator.tick(None, view, plan, outlook, NOW, warmup=warmup, warmup_sample=current)
    original = copy.deepcopy(generator.pending)
    states = rejected(original, NOW + 4200)
    now = NOW + 30
    if case == "expired":
        now = NOW + 121
    elif case == "new_basis":
        outlook = dict(outlook, snapshot_id="new")
    elif case == "invalid_end":
        for row in states[RESPONSE_ENTITY]["attributes"]["assessments"]:
            row["constraint"]["ends_at"] = "2026-10-23T19:00:00"
    else:
        states[REQUEST_ENTITY]["attributes"]["request_id"] = "foreign"
    changed = generator.feedback.receive(states, original, outlook, now)
    assert changed is (case == "invalid_end")
    assert generator.feedback.end is None
    if case == "invalid_end":
        assert generator.feedback.blocked
        generator.feedback.receive({}, None, dict(outlook, snapshot_id="fresh"), now + 1)
        assert not generator.feedback.blocked
