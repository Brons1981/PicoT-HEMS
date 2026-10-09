# Offered EV correction guard — 2026-10-09

Prepared release: Energy Devices 0.4.0-dev.4. Live stability remains unverified. Energy Devices
and its existing read-only P1 interface are in scope; HEMS and original Gielz
code remain unchanged.

## Acceptance evidence

- A deterministic baseline comparison reproduces `stale_source` when the battery
  remains 0 W for an hour. The corrected implementation instead offers 200 W for
  RAW 2500 W and EV 2300 W, while RAW/EV age/skew still gate new measurements.
- Guard tests cover EV start/stop/rapid steps, 2200 W oven cycling, PV changes,
  signed battery changes and consumer delay from zero through five seconds.
  These exercise transfer validation; they do not execute the full Gielz
  automation or prove physical closed-loop stability.
- Wrong offered corrections latch after a continuous 30-second mismatch;
  a matching offer resets that timer. Long missing input latches by ten seconds
  from the last valid source measurement. Missing consumer output uses ten
  seconds from first detection. Already ageing readings cannot restart grace.
- Real-file tests verify restart persistence, explicit disable reset and corrupt
  guard-file fallback. Runtime tests verify actual CT readback and held source
  timestamps through missing input and latched HTTP-value withdrawal.
- Snapshot tests verify bounded holds, immediate valid recovery, no overriding a
  latch, and producer expiry after a crash. Values are never replaced by zero.
- YAML parsing and six Jinja selector boundary checks verify fresh/held correction,
  measured-age expiry, producer-age expiry, blocked status and future timestamps.
  Full HA schema validation is still an installation check.

## Fresh integrated checks

The affected suite comprises Shelly EV acquisition, EV sessions/planning/runtime,
regulation calculation/API/guard, web UI, add-on metadata, HEMS external-load
policy and material replanning. Final result: **92 passed in 4.45 seconds**. Ruff passed for all Energy Devices
source and changed tests. Fresh-cache Mypy passed for all 12 Energy Devices
source files. `git diff --check` passed. No full repository suite or live
Home Assistant/Gielz execution is claimed.

## Deployment seam

Keep correction disabled until the matching HA selector permits API measured age
up to ten seconds while retaining producer report age at three seconds. Existing
entity IDs and original Gielz settings stay in place. Source data in held snapshots
is not redated for HEMS. See Energy Devices DOCS for the exact installation and
manual latch reset. Live EV charging and PV remain practical acceptance checks.
