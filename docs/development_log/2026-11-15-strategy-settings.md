# Four active strategy settings - local implementation

User chose the settings-first option on 15 November 2026: four working positions
on the existing MEP basis; pure Handel visible but disabled. V2ADR-072 records
the contract and responsibility boundaries. Dev.339 is still the rollback base.

## Acceptance evidence

| Requirement | Implementation | Evidence |
|---|---|---|
| Separate configurable ceiling, exact four-position mapping | v2/strategy_settings.py; canonical UserRuleProfile | 37.5 gives 0/12.5/25/37.5; 50 gives 0/16.666../33.333../50 |
| Balanced migration preserves current MEP maximum | Infer ceiling at 1.5 times prior maximum; preserve high legacy maxima at position 3 | Migration/restart tests for 0, 25 and 100; old API unchanged-maximum preservation |
| Self-consumption prevents new trade | Existing effective maximum and market_rule semantics at zero | Real settings store, API and monitor tests with absent market rule |
| Other parameters remain unchanged | Position-only partial update under store lock | Forecast, wear, spread, saldering and PV-preservation assertions; dirty-form JS test |
| Immediate canonical re-evaluation | Existing event and planning barrier; fresh input | Threaded old-cycle exclusion; second capture passed to real monitor execution seam |
| Explainable exact settings | Public server mapping; immutable snapshot revision/setting | UI evidence, persisted round-trip, revision-only material trigger with no market rule |
| No pure-trade workaround | Reject position 4 before persistence | UI disabled control, API400 and unchanged store |
| Rollback readable | Legacy field remains effective maximum, schema stays2 | Actual dev.339 loaders read all four values and financial ledger |

## Verification

Fresh integrated settings, UI, HTTP, runtime, replanning, route-choice, recovery
and ADR037 suite: **187 passed in 18.57 seconds**. Scoped Mypy on five changed
production modules and Ruff on all this increment's production/tests passed.
Additional market-capacity, bonus, tariff, settlement and ledger regressions:
**98 passed in 5.66 seconds**, bringing the two fresh groups to 285 passing tests.

The first combined run had 185 passes and one Windows localhost connection abort
(WinError10053) in an unchanged route-choice HTTP409 test. Its server response
branch is unchanged. The isolated ten-test route-choice file then passed, followed
by the complete 187-test run above without code changes to that path. The exact
cause of the connection abort was not established; no product fix is claimed.

Initial new settings tests failed because strategy fields/mapping did not exist.
Runtime tests likewise first demonstrated the missing serialized update seam.
No tests were weakened to hide those gaps.

No live HA installation, target NUC performance measurement or visual browser
inspection was performed. Node executed the actual dashboard JavaScript, and real
localhost HTTP requests exercised all four positions through the canonical store.

## Preserved behavior and limits

This increment changes only the effective market-capacity parameter through the
slider. Forecast selection, wear, financial thresholds and charge scheduling do
not move with it. A new evaluation may retain the same optimal plan. Existing
bound trade commitments, main-charge ownership and frozen daily budgets retain
their contracts; raising the slider does not refill or enlarge a frozen budget.

An in-progress calculation completes before a setting is acknowledged; the
existing planner then receives a fresh revision. UI acknowledgements distinguish
accepted settings/replanning from a completed replacement plan. Rapid UI changes
serialize and preserve the last queued value.

The preceding verified first increment was separately checkpointed as
market-phase1-verified.zip before modifying its source. Neither that checkpoint
nor this local work replaces the complete dev.339 rollback archive. No commit,
push, version bump, release or live installation occurred.
