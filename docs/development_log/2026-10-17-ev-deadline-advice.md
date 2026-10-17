# EV deadline advice — 2026-10-17

Local implementation on released HEMS dev.299 / Energy Devices dev.6 baseline.
Not published, released or installed.

## Outcome

Energy Devices accepts and persists ready-by + grid-side energy estimates.
HEMS evaluates bounded contiguous placements against the retained battery route
using the existing canonical physical model, tariff settlement and Evaluation.
The result returns over dedicated HA sensors and is displayed as advisory only.
Physical EV control and canonical commitment persistence remain unchanged.

See V2ADR-064.5-ev-deadline-advice.md for ownership, contracts and limitations.

## Verification

Fresh integrated run: 70 passed, 1 deselected, exit 0 (28.43 seconds):

```
python -m pytest tests/test_ev_deadline_request.py tests/test_ev_deadline_runtime.py 
  tests/test_ev_deadline_advice.py tests/test_ev_direct_start.py
  tests/test_ev_sessions.py tests/test_ev_direct_start_http.py
  tests/test_soc_expectation.py -q -k 'not over_http_socket'
  --basetemp=.test-deadline-verified
```

The deselected existing real-socket direct-start test requires the network-enabled
CI environment. The real HTTP request handler was exercised through an in-memory
transport. No live HA transport or BMW switching was attempted for this change.

Ruff passed for all eight changed/new source modules and three new test modules.
Mypy `--platform linux` passed for all eight source modules. Extracted dashboard
JavaScript passed `node --check`.

Tests demonstrate:

- Durable request identity/revision, idempotent retry, restart and cancellation.
- No physical session or switch command from an advice request.
- Complete request -> real canonical HEMS assessment -> dashboard state return.
- Cancellation during assessment suppresses publication; stale replies rejected.
- Wrong identity/revision, malformed slot shape and unexpected status rejected.
- Explicit infeasibility, partial tariff coverage and provisional advice.
- PV cashflow through the existing fiscal policy, without an alternate price model.
- Unchanged commitment store and blocked already-active external EV demand.
- Exact non-quarter charging duration and offset-aware DST elapsed time.
- Existing immediate-start/session and SOC expectation behavior still passing.

The initial missing-action test failed before request implementation. A subsequent
partial-quarter test exposed canonical 15-minute normalization; the projection
adapter now accepts optional extra boundaries (default behavior unchanged), and
the final integrated run passes with exact 1234 Wh demand. An initial DST test
used an invalid zero-length window; its fixture was corrected to test the two
distinct elapsed capacities across the fold.

## Release handoff

Changed sources: picot/v2/{ev_deadline_advice,ev_deadline_runtime,live_runtime,
independent_daily_reference_adapter}.py and picot_energy_devices/{charging_advice,
ev_sessions,runtime,web_ui}.py. New tests: test_ev_deadline_{request,advice,runtime}.py.
New architecture document: V2ADR-064.5. No version or release metadata changed.
Both add-ons need a coordinated release to expose this request/response feature.

Release requested by Alex: HEMS 2.0.0-dev.300 and Energy Devices 0.4.0-dev.7.
Published only after PR checks pass; installation/live validation remain separate.
