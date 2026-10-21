import json
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from picot.v2.route_choice_notifications import RouteChoiceNotifier, publish_choice_status


def notifier(tmp_path, callback=None):
    return RouteChoiceNotifier(
        "supervisor-secret",
        tmp_path / "notifications.json",
        mailbox_entity="input_text.picot_route_choice_response",
        on_choice=callback or (lambda value: {"status": "accepted"}),
    )


def test_outgoing_offer_survives_restart_and_deduplicates(tmp_path, monkeypatch):
    first = notifier(tmp_path)
    assert first.publish("offer-a", "Voorstel", "Kies route", offer_id="opaque-a")
    assert first.publish("offer-a", "Voorstel", "Kies route", offer_id="opaque-a")
    sent = []
    second = notifier(tmp_path)
    monkeypatch.setattr(second, "_poll", lambda: None)
    monkeypatch.setattr(second, "_send", sent.append)
    second.refresh()
    second.refresh()
    assert len(sent) == 1
    assert sent[0]["offer_id"] == "opaque-a"
    assert sent[0]["response_entity"] == "input_text.picot_route_choice_response"
    assert second.publish("offer-a", "Voorstel", "Kies route", offer_id="opaque-a")
    second.refresh()
    assert len(sent) == 1
    assert "supervisor-secret" not in second.path.read_text()


def test_delivery_failure_preserves_queue_and_incoming_is_still_processed(tmp_path, monkeypatch):
    received = []
    item = notifier(tmp_path, lambda value: received.append(value) or {"status": "accepted"})
    item.publish("a", "Title", "Body")
    value = {"token": "opaque-a", "action": "pv", "request_id": "request-1"}
    monkeypatch.setattr(item, "_request", lambda *args: {"state": json.dumps(value)})
    monkeypatch.setattr(item, "_send", lambda event: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError, match="offline"):
        item.refresh()
    assert received == [value]
    assert len(json.loads(item.path.read_text())["pending"]) == 1
    sent = []
    monkeypatch.setattr(item, "_send", sent.append)
    item.refresh()
    assert len(sent) == 1
    assert received == [value]


def test_mailbox_not_cleared_and_response_deduplicated_after_restart(tmp_path, monkeypatch):
    received, requests = [], []
    value = {"token": "opaque-a", "action": "pv", "request_id": "request-1"}

    def request(path, data=None):
        requests.append((path, data))
        return {"state": json.dumps(value)}

    for _ in range(2):
        item = notifier(
            tmp_path,
            lambda response: received.append(response) or {"status": "accepted"},
        )
        monkeypatch.setattr(item, "_request", request)
        item.refresh()
    assert received == [value]
    assert all(path.startswith("states/input_text.") and data is None for path, data in requests)


def test_callback_failure_retries_same_request(tmp_path, monkeypatch):
    received = []

    def callback(value):
        received.append(value)
        if len(received) == 1:
            raise OSError("core state not persisted")
        return {"status": "accepted"}

    item = notifier(tmp_path, callback)
    value = {"token": "opaque-a", "action": "automatic", "request_id": "request-1"}
    monkeypatch.setattr(item, "_request", lambda *args: {"state": json.dumps(value)})
    item.refresh()
    item.refresh()
    item.refresh()
    assert received == [value, value]


@pytest.mark.parametrize(
    "raw",
    [
        "unavailable",
        "unknown",
        "",
        "not json",
        "[]",
        "{}",
        '{"token":"a","action":"pv"}',
        '{"token":"a","action":"delete","request_id":"r"}',
        '{"token":1,"action":"pv","request_id":"r"}',
        "x" * 256,
    ],
)
def test_invalid_mailbox_does_not_reach_planner(tmp_path, monkeypatch, raw):
    received = []
    item = notifier(tmp_path, lambda response: received.append(response) or {})
    monkeypatch.setattr(item, "_request", lambda *args: {"state": raw})
    item.refresh()
    assert received == []


def test_expired_offer_is_not_sent_and_missing_mailbox_has_no_buttons(tmp_path, monkeypatch):
    item = notifier(tmp_path)
    item.publish(
        "old",
        "Voorstel",
        "Old",
        offer_id="expired",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    sent = []
    monkeypatch.setattr(item, "_poll", lambda: None)
    monkeypatch.setattr(item, "_send", sent.append)
    item.refresh()
    assert sent == []
    info = RouteChoiceNotifier("token", tmp_path / "info.json")
    info.publish("info", "Voorstel", "Body", offer_id="unusable")
    monkeypatch.setattr(info, "_send", sent.append)
    info.refresh()
    assert sent[0]["offer_id"] is None


def test_network_worker_does_not_block_publish(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    item = notifier(tmp_path)
    monkeypatch.setattr(item, "_poll", lambda: None)

    def send(event):
        entered.set()
        release.wait(2)

    monkeypatch.setattr(item, "_send", send)
    item.start()
    try:
        item.publish("first", "Voorstel", "Body")
        assert entered.wait(1)
        assert item.publish("second", "Herstel", "Body")
        assert len(json.loads(item.path.read_text())["pending"]) == 2
    finally:
        item.close()
        release.set()
        item._thread.join(2)


def test_publish_storage_failure_returns_false_and_retries(tmp_path, monkeypatch):
    item = notifier(tmp_path)
    original = item._save
    monkeypatch.setattr(item, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    assert not item.publish("first", "Voorstel", "Body")
    monkeypatch.setattr(item, "_save", original)
    assert item.publish("first", "Voorstel", "Body")
    assert len(json.loads(item.path.read_text())["pending"]) == 1


def test_persisted_selection_and_repair_are_published_once(tmp_path):
    item = notifier(tmp_path)
    record = {
        "token": "one",
        "assignment_id": "today",
        "status": "selected",
        "offer": {"delivery_date": "2026-10-21"},
        "last_notice": {"key": "repair:one", "message": "Noodzakelijk herstel"},
    }
    publish_choice_status(item, {"choices": [record]})
    publish_choice_status(item, {"choices": [record]})
    queued = json.loads(item.path.read_text())["pending"]
    assert len(queued) == 2
    assert queued[0]["title"] == "PV-route bevestigd"
    assert queued[1]["message"] == "Noodzakelijk herstel"
    assert all(event["offer_id"] is None for event in queued)
