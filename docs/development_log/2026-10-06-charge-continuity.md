# 2026-10-06 - Main-charge continuity and optional improvement

Status: IMPLEMENTED locally; not published, CI verified or live verified.
Alex approved this first repair at 18:38 Europe/Amsterdam. Baseline main
158c61b051ead19f5ffbfd49754f2b27a2ba5994, installed HEMS dev.285.
Local isolated branch: fix/charge-continuity in charge-continuity-fix.
The local Git baseline is a source materialization, not an ancestor of main;
publish only the selected changes against current remote main when requested.

## Contract and first incorrect boundary

Optional reduction could interrupt running grid charge while normal household
load was reliable. Candidate continuity was restricted to high/unknown load.
Evaluation accepted very small financial improvements; equal-priced duration
reduction could also replace an otherwise valid route. Owning layers are
Candidate Generation and Evaluation, with explicit pipeline composition.
ADR-037.23 supplements ADR-027/032 and ADR-037.12/.15/.16/.21.

All running main grid blocks now keep their admitted end. Actual 100% releases
the constraint; manual recalculation remains explicit. Necessary recovery can
continue/extend the block. Optional PV/SOC/net-balance reduction is deferred.
Evaluation requires EUR 0.01 producer-derived benefit for optional reductions
against a valid incumbent. Rate differences use one shared remaining daily goal;
complete market comparisons use existing EUR differences. Raw outcomes are kept.
The threshold and benefit are explicit in canonical outcomes/evaluation records.
Invalid incumbents bypass the financial gate; missing benefit cannot invent savings.
The evaluation identity includes the minimum-improvement policy.

## Fresh evidence

New regression on original code: running block returned no protection without
extra household load. New API checks also failed before implementation.
Real diagnostic ZIP picot-diagnostics - 2026-10-06T181929.036.zip, original typed
PlanningInputSnapshot and actual conversion evidence, adapter seam replay:

| Local decision | Snapshot | Original removable input | New protected end (local) |
|---|---|---:|---|
| 12:14:25 | snapshot-7a00f531920ad809 | 23.1820547 Wh | 14:15 |
| 14:26:33 | snapshot-63db6a0c4898271d | 137.422572 Wh | 15:00 |
| 14:53:46 | snapshot-6a492d53d8b7c605 | 249.053562 Wh | 15:15 |

All three original triggers reproduce on dev.285; the repaired adapter returns
no optional trigger. This is an exact input replay at the Candidate adapter seam,
not a full-day physical replay or a live claim. Script .tmp-diagnosis-replay.py
remains in the local analysis workspace and imports the untouched baseline.

Broad affected suite: 123 passed in 228.01 s, including main route, shortfall,
market guard/replacement/revision and architecture ownership tests.
Additional guard/net-evidence/duration suite: 42 passed in 16.84 s.
Final evaluation/projection/store contract suite: 43 passed in 6.27 s.
These suites overlap; counts are not a unique-test total. Final affected pipeline
suite: 40 passed in 60.67 s, including material replacement, subcent retention,
necessary shortfall recovery and independent net evidence. Ruff, strict mypy
on all five changed production modules and compileall passed. Diff whitespace
check passed. The final evaluation identity policy is covered by the contract suite.

Test expectations deliberately changed: subcent optional replacements now retain
the route; independent net evidence cannot interrupt an active charge block.
A distinct cheap quarter supplies a material-benefit replacement regression.
The fresh selected outcome is independently checked against the shared goal scale.
An initially missing upstream dev243 fixture was restored unchanged from main;
test failures from that missing file were environment/setup failures.

## Boundaries and next step

No release/version bump, remote push, merge, HA installation or restart.
No changes to Solcast selection, vendor adapter, EV control, daily identities,
financial observer or market-export gap measurement. No stored-plan migration.
Rollback: revert only these selected Candidate/Evaluation/composition changes.
Dev.268 remains the designated project fallback; no automated rollback.

BMS taper is confirmed as a modelling limitation, not repaired by this slice.
No additional SOC percentage tolerance or fabricated 100% completion was added.
Next step: release preparation/PR/CI only when requested; then validate with a
new live diagnostic. Model realistic high-SOC charging as a separate change.

## Release dev.286

Alex explicitly requested release on 6 October. Selected changes and version
alignment are prepared against current main dev.285. Publish via PR and require
Tests, PicoT Core CI and PicoT v2 Rebuild to succeed before merge.
IMPLEMENTED; CI evidence pending. Installation and LIVE_VERIFIED evidence follow
separately. Release version alignment and new regression checks: 22 passed in 1.35 s.
The primary command launcher failed sandbox provisioning; the available Node
runtime executed the existing Python checks. One non-failing pytest cache
permission warning occurred.

### First CI and corrected regression expectations

Tests run 37513886069: 1937 passed, 1 skipped, 5 failed. The five failures
were obsolete expectations in three tests: household-load release, subcent
replacement, equality decisive-step wording and a reduction fixture below the
new threshold. Updated the expectations to ADR-037.23. The freed-NOM regression
uses the material-benefit SOC fixture and retains its full path assertions;
subcent tests require retention while checking shorter alternatives exist.
Local rerun: all 13 tests in those three modules passed in 25.86 s.
Core CI and v2 Rebuild succeeded on the first head; all CI must pass on the
updated head before merge. No production change was needed for these failures.
