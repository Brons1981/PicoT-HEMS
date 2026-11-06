# Market-bound standby stability and comparison delivery

Alex requested repair after dev.333 still added two evening standby quarters and
the dashboard reported oversized detail. Scope: HEMS; no HC edits, live commands,
plan reset, version bump or release. Isolated workdir: `market-standby-fix`.
Baseline: HEMS dev.333, including its ordinary bridge repair; the pipeline baseline
was compared to current main before editing. Concurrent HC work is separate.

## Evidence and policy

The 6 November diagnostic export records market-bound bridge revisions with valid
incumbents. Stored canonical comparisons show route improvements of:

- 13:29 local: EUR 0.000441718626; adds standby 22:45-23:00.
- 14:00 local: EUR 0.002904163711; adds standby 14:45-15:00.
- 17:29 local: EUR 0.000248552502; adds standby 21:45-22:00.

The market-revision branch bypassed the dev.333 financial stability option.
Alex explicitly approved applying the existing one-cent boundary here on 6 November.
This defines financial equivalence for this extension of ADR-019.5/019.6; frozen
ADR text is not edited, and no new trigger or Store-owned economic rule is introduced.
It now enables the same strict-below-EUR-0.01 equivalence policy, including the
unrestricted comparison used for route consent and the published evaluation record.
An invalid incumbent is still rejected before comparison. Meaningful improvements,
common recovery, terminal-stock checks, trade ownership and main goals stay intact.

Re-evaluation of all stored financial tables (4,415 / 7,152 / 7,200 candidates)
retains the valid incumbent. This is an evaluation-table check using recorded
financial outcomes and validity, not a full historical simulator replay: the
original incident records had discarded their snapshots because of size.

## Dashboard

Only observer presentation is reduced. The web store copies the incoming view and
shows at most 50 candidate examples, always retaining winner and incumbent, plus
examples of each market variant/rejection state and then original-order examples.
No new financial ranking or selection is performed. The comparison reports total
and omitted counts; the displayed evidence dictionary includes required raw bases.
Active plan, execution status, narrative, SOC timeline and canonical decision remain.
Small comparisons keep their existing presentation. The input view is not mutated.

## Diagnostic format

Existing market diagnostic records remain `market-revision-compact:v1` when they
fit the unchanged 8 MiB budget. Oversized market records archive their candidate
set, outcomes, full evaluation, evidence dictionary and original format into an
inline `comparison_archive` using `gzip-base64-json:v1`. Compression uses level 1
to limit CPU overhead. The outer poll is labelled `market-revision-archive:v1`;
snapshot, execution evidence and a compact evaluation
summary remain directly readable. Byte length and SHA-256 validate restoration.

`picot.v2.comparison_archive.expand_comparison_record(record)` restores the complete
original JSON record, including every candidate, value, validity reason and evidence
reference. This adds no sidecar file or retention policy. Existing rotation and
age-based retention still apply. Exceptional records that still exceed the budget
keep the existing bounded fallback; the UI no longer promises all evidence exists
unconditionally. Already-discarded historical input cannot be reconstructed.

## Verification

The pipeline margin regression and both 7,200-candidate delivery regressions failed
on baseline for the reported reasons. Initial focused suite: 12 passed.
Final delivery/archive/browser-rendering suite: 17 passed. A 7,200-candidate
diagnostic is 1,035,510 bytes and round-trips to the exact original record. Its dashboard
is 851,391 characters, displays 50 alternatives and drops no whole section.
Ruff passed; strict Mypy for five changed modules passed with Linux target (the
native Windows check reports existing POSIX-only flags in passive_history/export.py).
The full dashboard JavaScript syntax test passes under Python UTF-8 mode.
The native Windows cp1252 subprocess pipe could not encode U+2212 in the existing
HTML (also on baseline); no product change was needed for this environment issue.
Broader market, failed-goal, bridge, incident-history and web regressions: 121 passed
in 303.25 seconds; the one deselected JavaScript syntax test passed separately with
UTF-8 mode (1 passed). Final Ruff check passed for all changed production/test files.
No release, version bump or live installation has been performed.

## Release integration

Alex requested publication as HEMS dev.335. Integrates on top of dev.334 / HC dev.32
(PR749), preserving all partial-load and shorter-standby changes. The shared incident
writer archives before the final bounded fallback. When archived details age out,
retention expands the comparison to derive the dev.334 compact financial summary;
a 7,200-candidate regression checks exact equivalence with the original record.
No HC/ED source changes or live installation in this release.
