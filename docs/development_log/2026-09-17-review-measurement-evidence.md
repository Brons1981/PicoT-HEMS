# 2026-09-17 — Passive review measurement evidence (dev.262)

## Scope

Preserve measurement evidence for future replay and explain missing data without
changing MEP decisions, commitments, forecasts or actuation. Release dev.262 requested by Alex after implementation; no live deployment by Codex.

## Confirmed cause and limits

The September 17 diagnostic contains an unavailable SOC observation at
09:31:02.207330 Amsterdam time, restored at 09:31:03.215624 at 30%.
The existing strict review rejects this actual source interruption. It also
previously reported only `measurement_unavailable`, hiding the affected source
and interval. Full raw power histories were not included in diagnostics.

An actual HA source outage cannot be reconstructed from this export. This change
does not relax evidence requirements, interpolate unavailable values, or change
Recorder settings. Household polling gaps and true sensor outages remain explicit
blockers; restoring those sources needs evidence from the new capture.

## Changes

- Passive review opts into the existing two-hour history cache bootstrap, then
  fetches only the unseen tail. Failures retry the uncollected chunk, retaining
  unavailable markers. Other cache consumers retain their original defaults.
- Save the current and previous review day as atomic gzip JSON snapshots including
  raw points, source entity, timestamps, evidence IDs, and history semantics.
  Nonfinite values remain explicit JSON nulls. Failed transport reads do not
  overwrite a previously saved snapshot. Both files join the diagnostic allow-list.
- Report missing series, missing anchors, invalid-value spans, household sampling
  gaps, and missing household tails per required role. Limit displayed details to
  twenty gaps per role, with explicit omitted counts. State-held unchanged values
  are not treated as missing heartbeats.
- Show source and interval details beneath incomplete review rows.

## Verification

81 targeted tests passed across review, measurement archives, history cache and
integration, diagnostic downloads, and web UI. Added regression coverage for a
one-second SOC outage, missing anchors/roles, state-hold semantics, strict JSON
gap preservation, archive retention after failures, and bounded history retry.
The real September 17 SOC export reports the exact 1.008294-second interruption.
No live HA/NUC execution has been performed; deployment and live data completeness
remain unverified.
