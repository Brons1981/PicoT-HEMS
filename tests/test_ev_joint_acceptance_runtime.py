from datetime import UTC, datetime
from types import SimpleNamespace

from picot.v2.ev_deadline_runtime import EVDeadlineAdvisor


def setup_advisor(*, receipt=None, adopt=None):
    now = datetime(2026, 11, 1, 6, tzinfo=UTC)
    selected = {"selection_id": "selection", "session_id": "session", "request_revision": 1}
    envelope = {"generated_at": now.isoformat(), "selected_advice": selected,
                "request": {"state": "accepted", "session_id": "session", "request_revision": 1}}
    published = []
    advisor = EVDeadlineAdvisor(read=lambda: envelope, publish=published.append,
                                configuration=lambda _: None, now=lambda: now,
                                adopt=adopt, receipt=receipt)
    return advisor, SimpleNamespace(captured_at=now), selected, published, envelope


def test_ack_only_after_successful_adoption():
    calls = []
    advisor, snapshot, selected, published, _ = setup_advisor(
        adopt=lambda proof, current: calls.append((proof, current)) or {
            "selection_id": "selection", "session_id": "session", "request_revision": 1,
            "battery_plan_id": "battery"})
    advisor.selections["selection"] = "proof"
    assert advisor.accept_pending(snapshot)
    assert calls == [("proof", snapshot)]
    assert published[0]["execution_status"] == "committed"


def test_restart_republishes_durable_receipt_without_adopting_again():
    advisor, snapshot, selected, published, _ = setup_advisor(
        adopt=lambda *_: (_ for _ in ()).throw(AssertionError("duplicate adoption")),
        receipt=lambda _: {"selection_id": "selection", "session_id": "session",
                           "request_revision": 1, "battery_plan_id": "battery"})
    assert advisor.accept_pending(snapshot)
    assert published[0]["battery_plan_id"] == "battery"


def test_failed_adoption_never_confirms():
    advisor, snapshot, _, published, _ = setup_advisor(
        adopt=lambda *_: (_ for _ in ()).throw(ValueError("owner changed")))
    advisor.selections["selection"] = "proof"
    assert not advisor.accept_pending(snapshot)
    assert published[0]["execution_status"] == "blocked"
    assert published[0]["reason"] == "owner changed"


def test_cancelled_request_never_adopts():
    advisor, snapshot, _, published, envelope = setup_advisor(
        adopt=lambda *_: (_ for _ in ()).throw(AssertionError("cancelled")))
    envelope["request"]["state"] = "cancelled"
    assert not advisor.accept_pending(snapshot)
    assert not published


def test_ack_transport_failure_still_requests_fresh_committed_context():
    advisor, snapshot, selected, _, _ = setup_advisor(
        adopt=lambda *_: {"selection_id": "selection", "session_id": "session",
                          "request_revision": 1, "battery_plan_id": "battery"})
    advisor.selections["selection"] = "proof"
    advisor.publish = lambda _: (_ for _ in ()).throw(OSError("transport failed"))
    assert advisor.accept_pending(snapshot)
