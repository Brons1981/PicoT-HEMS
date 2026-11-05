# HEMS standby stability repair — 5 November 2026

Scope: HEMS only. Local isolated workdir `standby-margin-fix`, source baseline
HEMS dev.332 from `hc-day-ahead-work`. Do not copy this whole directory over
concurrent HC work. Apply only the files in `standby-margin-status.json`.
Release dev.333 authorized by Alex; publication via PR and green CI.
No live command, installation or live plan reset.

## Behavior

For ordinary bridge comparisons (not market revisions), differences below EUR 0.01
in total route cash are financially equivalent. Evaluation first retains a valid
unchanged incumbent within that band. Otherwise it prefers fewer expected switches
before lower-priority objectives. EUR 0.01 or more remains a meaningful difference.
All existing physical/capability/goal validity checks precede selection.
The baseline's identity is carried from bridge generation; actual retained commands
must match the freshly simulated candidate before it receives incumbent preference.
The equivalence policy, margin and decisive tie-break are recorded in evaluation.
Other evaluation callers retain the prior default behavior.

Retained bridge evidence is recorded without replacing the plan, including when an
earlier main segment has already elapsed. The ownership check uses the next future
main segment. This prevents repeated reviews after restart without reopening a
completed goal or altering a later charge window.

## Evidence

Original 5 November diagnostic replay reproduced both exact historical plan IDs:
- 18:33 local: added 23:45–00:00, advantage EUR 0.0000305167049822.
- 19:26 local: added 21:45–22:00, advantage EUR 0.0000808135959300.

With repair, both historical inputs produce `plan_retained` /
`daily_main_incumbent_retained`; the original plan identity and every command are
unchanged. First replay adds no standby. Second retains the already-owned 23:45
standby but does not add 21:45. Existing live plans are not retroactively reset.

Verification (Python 3.14, Windows; existing local dependency set):
- New regression tests fail on baseline because stability behavior is absent.
- 97 affected/regression tests passed, including daily bridges, elapsed main blocks,
  local recovery, main-route changes, supplemental repair/retirement, and market revisions.
- Final cent-boundary refinement: 52 tests passed (evaluation, bridge pipeline,
  elapsed-main, and 9 new stability cases). Includes exactly EUR 0.01, invalid
  incumbent, secondary objective versus switching, and changed command rejection.
- Ruff passed for all changed Python files; strict targeted Mypy passed for six
  production files. Final engine refinement also passed Ruff and Mypy.
- Two historical pipeline replays plus exact identity/command assertions passed.

Tests expecting redundant baseline republication were updated to require retained
identity and persisted deficit evidence. Existing publication-tampering tests now
use a materially cheaper bridge so they still exercise real replacement guards.

No live HA integration or installation was executed. Release CI must pass before merge.
