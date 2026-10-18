from picot_energy_devices.runtime import regulation_health, session_health


class Recorder:
    def __init__(self):
        self.events = []

    def observe(self, key, active, message):
        self.events.append((key, active, message))


def test_p1_blockage_recovery_requires_verified_receiver():
    notifier = Recorder()
    regulation_health(notifier, {"status": "blocked", "correction_guard": "latched"},
                      control_enabled=True)
    regulation_health(notifier, {"status": "ready", "correction_guard": "recovering"},
                      control_enabled=True)
    regulation_health(notifier, {"status": "ready", "correction_guard": "checking"},
                      control_enabled=True)
    assert [e[1] for e in notifier.events] == [True, True]
    regulation_health(notifier, {"status": "ready", "correction_guard": "matched"},
                      control_enabled=True)
    assert notifier.events[-1][1] is False


def test_observer_only_p1_failure_does_not_claim_control_failure():
    notifier = Recorder()
    regulation_health(notifier, {"status": "blocked"}, control_enabled=False)
    assert not notifier.events


def test_ev_command_failure_notifies_and_clear_recovers():
    notifier = Recorder()
    session = {"state": "active", "error": "switch service unavailable"}
    session_health(notifier, {"session": session})
    assert notifier.events[-1][1] is True
    session["error"] = None
    session_health(notifier, {"session": session})
    assert notifier.events[-1][1] is False


def test_manual_pause_and_deadline_are_not_failures():
    notifier = Recorder()
    session_health(notifier, {"session": {"state": "interrupted", "manual_pause": True}})
    session_health(notifier, {"session": {"state": "completed",
                                         "completion_reason": "scheduled_deadline"}})
    assert not any(e[1] for e in notifier.events)


def test_missing_start_measurement_needs_two_minutes():
    notifier = Recorder()
    snapshot = {"generated_at": "2026-10-18T04:01:00+00:00", "session": {
        "state": "active", "start_status": "measurement_unavailable",
        "switch_on_observed_at": "2026-10-18T04:00:00+00:00",
    }}
    session_health(notifier, snapshot)
    assert notifier.events[-1][1] is False
    snapshot["generated_at"] = "2026-10-18T04:02:00+00:00"
    session_health(notifier, snapshot)
    assert notifier.events[-1][1] is True
