# Execution result ordering and durable command ownership

Status: locally implemented and verified; dev.299 release requested via PR and CI. Live verification follows installation.
Baseline: dev.298, commit 270a2a08d0cde6622b53af4f6845e97df5665b70.

## Contract

The live log terminates in `_observe_execution_status` with `Runtime observations
may not precede the last processed observation`. HA attributes the NOM change at
14:16:25 Europe/Amsterdam to Supervisor. The ZIP retains the prior fast-charge
provenance and reports a manual override after restart.

The owning boundary is live execution-result production and provenance recording.
ADR-034's strict ordered observation validation remains unchanged. The canonical
planning/dispatch ownership and V2ADR-060 adapter failure semantics remain intact.
No EV policy, MEP selection, fallback policy, plan, reset, or live setting changes.
The original reason for the incident's fallback is not established by this fix.

## Change

After the canonical execution adapter returns, capture the execution result time
from the runtime clock instead of reusing the original planning snapshot time.
Cooperative checks during planning may already have advanced the monitor beyond
that snapshot. Source snapshots and execution-input evidence remain unchanged.

Persist successful command ownership and its switch-history event before passing
the result to the monitor. A later monitor error cannot prevent this persistence.
Failed dispatches do not acquire ownership. Genuine manual changes remain blocked.
This is not a transaction across HA and local storage and does not claim immunity
to process termination or disk failure during the actual persistence operation.

## Fresh verification

- Baseline regression: 3 failed, 1 passed. Two failures reproduce the exact live
  exception; the third proves lost successful-command provenance on monitor error.
- Repaired regression: 4 passed, including failed dispatch, injected monitor error,
  restart recognition, and a subsequent genuine manual change.
- Affected suites: 84 passed (66.45 s): execution-result ordering, Runtime Monitor,
  fresh execution evidence, cooperative planning, provenance, canonical execution,
  live poll/single cycle, and web publication.
- Ruff: both changed Python files passed.
- mypy --platform linux src/picot/v2/live_runtime.py: passed. Native Windows target
  reports nine pre-existing Linux-only API errors in two unchanged modules.
- Source comparison: only src/picot/v2/live_runtime.py differs from fetched baseline;
  the regression test and this note are additions.

Verification used Python 3.12.14 with locally cached test tools and real canonical
pipeline, monitor, adapter runtime and file-backed provenance. Only external HA
dispatch/publication and the wall clock were controlled. No live battery commands.

Rollback of this patch restores the baseline live_runtime.py and removes the new
test; operational rollback remains the user's separately agreed dev.268 baseline.
Publication, CI and installation are separate steps.
