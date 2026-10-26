import json
from threading import Event

from picot.health_notifications import HealthNotifier


def test_pending_is_durable_and_control_does_not_wait_for_network(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    def send(self, event):
        entered.set()
        release.wait(2)
        raise OSError("offline")
    monkeypatch.setattr(HealthNotifier, "_send", send)
    path = tmp_path / "notifications.json"
    notifier = HealthNotifier("token", "ED", path)
    try:
        notifier.observe("p1", True, "blocked")
        assert entered.wait(1)
        notifier.observe("p1", True, "still blocked")
        notifier.observe("p1", False, "recovered")
        saved = json.loads(path.read_text())
        assert [event["active"] for event in saved["pending"]] == [True, False]
        assert saved["pending"][0]["tag"] == saved["pending"][1]["tag"]
        assert "token" not in path.read_text()
    finally:
        notifier.close()
        release.set()
        notifier._thread.join(2)


def test_restart_replays_unsent_and_deduplicates_active(tmp_path, monkeypatch):
    path = tmp_path / "notifications.json"
    path.write_text(json.dumps({"active": {"p1": True}, "pending": [
        {"key": "p1", "active": True, "message": "blocked"}]}))
    sent, recovered = [], Event()
    def send(self, event):
        sent.append(event)
        if not event["active"]:
            recovered.set()
    monkeypatch.setattr(HealthNotifier, "_send", send)
    notifier = HealthNotifier("token", "ED", path)
    try:
        notifier.observe("p1", True, "duplicate")
        notifier.observe("p1", False, "restored")
        assert recovered.wait(1)
        assert [event["active"] for event in sent] == [True, False]
    finally:
        notifier.close()
        notifier._thread.join(2)
    assert json.loads(path.read_text())["pending"] == []


def test_disabled_and_recovery_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(HealthNotifier, "_run", lambda self: None)
    path = tmp_path / "notifications.json"
    disabled = HealthNotifier("token", "HC", path, enabled=False)
    disabled.observe("fault", True, "fault")
    assert not path.exists()
    notifier = HealthNotifier("token", "HC", path, recovery_enabled=False)
    notifier.observe("fault", False, "initial healthy")
    assert not path.exists()
    notifier.observe("fault", True, "fault")
    notifier.observe("fault", False, "recovered")
    saved = json.loads(path.read_text())
    assert len(saved["pending"]) == 1
    assert saved["active"] == {"fault": False}
    notifier.close()


def test_failed_delivery_retries_without_losing_event(tmp_path, monkeypatch):
    failed, delivered = Event(), Event()
    attempts = []
    def send(self, event):
        attempts.append(event)
        if len(attempts) == 1:
            failed.set()
            raise OSError("HA offline")
        delivered.set()
    monkeypatch.setattr(HealthNotifier, "_send", send)
    notifier = HealthNotifier("token", "HEMS", tmp_path / "state.json")
    try:
        notifier.observe("fallback", True, "fallback")
        assert failed.wait(1)
        # Wake retry worker without waiting for its production backoff.
        for _ in range(100):
            with notifier._condition:
                notifier._condition.notify()
            if delivered.wait(0.01):
                break
        assert delivered.is_set()
        assert attempts[0] == attempts[1]
    finally:
        notifier.close()
        notifier._thread.join(2)


def test_changed_cause_is_reported_once_and_deduplicated_across_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(HealthNotifier, "_run", lambda self: None)
    path = tmp_path / "notifications.json"
    first = HealthNotifier("token", "HEMS", path)
    first.observe("planning_fallback", True, "missing prices", fingerprint="missing:prices")
    first.observe("planning_fallback", True, "same cause, later clock",
                  fingerprint="missing:prices")
    first.close()
    second = HealthNotifier("token", "HEMS", path)
    second.observe("planning_fallback", True, "same after restart", fingerprint="missing:prices")
    second.observe("planning_fallback", True, "missing forecast", fingerprint="missing:forecast")
    second.observe("planning_fallback", False, "valid plan")
    second.observe("planning_fallback", False, "same recovery")
    second.close()
    pending = json.loads(path.read_text())["pending"]
    assert [(e["active"], e["message"]) for e in pending] == [
        (True, "missing prices"), (True, "missing forecast"), (False, "valid plan")]
