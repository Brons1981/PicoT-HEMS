# Active plan owner restoration - 24 October 2026

Baseline: main `9696708` / HEMS dev.313. Local implementation only; no release.

## Final agreed scope

Alex explicitly narrowed this repair to the programming defect after reviewing
the risks of extending main charging beyond midnight. The earlier local
continuous-midnight implementation, lifecycle changes, extra charging policy,
execution handoff, historical recovery changes and associated tests/docs have
been removed from this branch. They were never published or installed.

The original calendar-day and completion rules in ADR-037.2/.3 remain unchanged.
No schema change, automatic extension, new completion policy or rollback-format
requirement is introduced. Only daily input restoration changes in production.

## Failure and owning boundary

The October 24 diagnosis records `active_daily_main_plan_owner_not_restored`
at 00:40:18 Europe/Amsterdam. The incomplete October 23 assignment expired at
midnight, but its active execution plan `plan-77cef0dbb602a5f8` still contained
valid October 24 actions. Restoration filtered the owner out before validating
the active plan. The morning manual reset happened to remove that inconsistency.

Restoration now validates the active plan first and retains its explicit owner,
including original ownership proven by shared market-plan segment lineage.
This happens in both restoration filters. Invalid pointers/origins still block;
expired execution plans do not revive old owners. Restoration does not write
the store, select a plan, create an action or infer completion.

At midnight with actual SOC below 100%, charging still ends at the original
scheduled time. The prior day remains incomplete and the admitted subsequent
route stays usable. This prevents this specific restoration fallback; it is not
a guarantee against unrelated safety/data/planning fallbacks.

## Verification

Six focused regressions cover direct ownership, shared market ownership, invalid
pointer/origin rejection, expired execution plans and a full canonical pipeline
case: main ends at midnight, SOC is 97% at 00:40, the same plan is retained,
BALANCE_DISCHARGE_ONLY is due, no extension/completion/store write occurs.

Fresh verification: 54 tests passed (owner restoration, runtime input, horizon retention, market binding and active pipeline). Ruff passed for the changed source and regression tests; mypy with Linux target passed for live_runtime.py; git diff --check passed. CI and live operation
remain separate. All other production files equal the dev.313 baseline.

