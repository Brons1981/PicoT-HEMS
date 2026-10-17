# EV direct start - first approved slice

Status: locally implemented; release 0.4.0-dev.6 authorized, PR/CI pending; not installed.
Baseline main: 542de25f4f0aa29303c1835cbe50d2f13f66ec4a.
Both production file baselines were verified against GitHub blob hashes.

The dashboard saves a fixed power/duration profile, then starts a durable EV
session with one button. User action attests that the cable is connected. The
existing runtime owns the configured switch; no BMW plug-state dependency or
preliminary charging probe is introduced. Restart, duplicate start, cancellation,
missing data, pre-session measurements, manual off/resume, command failure/retry,
natural completion and original hard stop are covered. Profile changes affect
future sessions only. No new production HEMS logic or live configuration changed.

## Fresh evidence

- Before implementation: 5 intended direct-start acceptance tests failed because
  the actions were absent; 5 invalid-input cases passed (not proof of a feature).
- Final pytest: test_ev_direct_start.py, test_ev_direct_start_http.py,
  test_ev_sessions.py, test_ev_session_planning.py and test_energy_device_runtime.py:
  44 passed in 15.19 seconds.
- Real HTTP request parsing and response serialization tested with an in-memory
  transport, real handler, real session store and normal tick dispatch boundary.
- Ruff: Energy Devices source and the two new test files passed.
- mypy --platform linux src/picot_energy_devices: all 13 source files passed.
- Dashboard embedded JavaScript: node --check passed.

An earlier run including test_energy_device_web_ui.py had 41 passed and 3 failed:
all three failures were Windows sandbox WinError 10013 on localhost connections.
Those existing tests were retained unchanged. Actual browser/HTTP socket behavior
has NOT been validated locally and must pass CI before publication. Physical
Shelly/BMW operation requires installation and a live session.

## Remaining roadmap

V2ADR-064.4 records the agreed HEMS scheduling design and uncovered interfaces.
Deadline/price scheduling, BMW source binding and automatic scheduled slots are
not implemented by this first slice. The profile duration is a maximum runtime,
not proof of 100% SOC or the future deadline guard. HEMS currently receives one
confirmed fixed window, not a request it can optimize across multiple days.
