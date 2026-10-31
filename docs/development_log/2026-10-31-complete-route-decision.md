# 31 October 2026 - Complete optional route costs and dashboard explanation

Scope approved by Alex: repair the inconsistent optional route comparison and
show why the actual plan was selected/retained. No release requested in this turn.

## Change contract and baseline

Work copy: `plan-explanation-fix`, from local `recovery-continuity-refactor`
dev.322 source snapshot. That snapshot's release metadata records PR732 / merge
967c3b38ff9f297a40fcb2b7721396a0f99d1b40; this is not a claim of a fresh remote checkout.
No source under the read-only `sources/` tree was changed.

First bad boundary: main-charge outcome production supplies acquisition-rate
benefits for optional revisions that also change the overnight bridge.
Controlling contract: frozen canonical pipeline, ADR-017/024/026/027/032/033,
ADR-037.23 as explicitly supplemented by V2ADR-067.

Producer owns physical comparability and complete EUR outcomes; Evaluation keeps
the existing EUR0.01 admission threshold; pipeline wires only optional surplus
reviews to the new comparison. Projection/UI has no planning authority.
Initial selection, market recovery, safety, daily goal, device adapter and EV
control remain outside scope. No new threshold or global quarter optimizer.
Rollback consists solely of the changed source/UI files; no plan migration.

## Implemented behavior

- Optional revisions with a valid incumbent use complete fresh-horizon cash in
  EUR, including household import/export and refill cost.
- Same-horizon and equal-terminal-inventory checks prevent fictitious savings.
  Invalid/incomparable candidates expose no commitment benefit.
- Negative, equal and subcent improvements retain the valid incumbent. Invalid
  incumbents can still be repaired; the financial gate cannot hide infeasibility.
- Directly visible dashboard explanation reports actual admission/retention,
  signed benefit and threshold when comparable, assessment time, horizon, SOC,
  selected solar forecast and household/confirmed EV assumptions.
- Acquisition rates are not displayed as whole-route savings. Failed publication
  is not displayed as a newly active plan. Unequal-stock exclusions are explicit.
- Normal ticks and process restart preserve dated evidence only for identical
  admitted plan/path identities. A separate bounded display cache uses a sibling
  path of the existing SOC cache without changing its format. Cache failure has
  no planning/dispatch effect. Pre-upgrade plans without saved explanation report
  its absence until a new evaluation; no historic financial rationale is invented.

## Regression evidence

Exact diagnostic replay: `tmp_diagnose_1031b/replay_total_cost.py`, recorded input
run-982dae8688e2077d (31 October 18:45 local). Original acquisition comparison
selects a route costing EUR2.144169394, reporting rate-scaled benefit EUR0.010278706,
against an incumbent costing EUR1.976045799. Complete comparison retains the
exact incumbent with `commitment:minimum_improvement_incumbent_retained`.

Five focused producer cases cover rate/cash inversion, real saving at equal
acquisition price, unequal stock, invalid-incumbent recovery and EUR0.004 benefit.
The pre-fix producer fails the intended regressions. A further red/green assertion
prevents invalid unequal-stock candidates reporting a monetary benefit.
Existing pipeline tests now assert actual EUR differences rather than the retired
rate-times-goal formula.

UI tests cover visible placement, cents, absent evidence, escaping, failed
publication, same-plan retention and rejection on new identity/fallback/restart.
Pure projection tests exercise actual pipeline records and canonical explanation
values. Independent review found the exclusion wording and restart continuity
gaps; both were addressed within the display-only boundary.

## Verification and limitations

Integrated planner/Evaluation/Builder/market comparison and UI/projection suite:
284 passed, 1 deselected (the separately reproduced loopback restriction), 324s.
Command: pytest all `tests/test_daily*.py`, `test_main_revision_total_cost.py`,
`test_plan_decision_explanation.py`, `test_plan_decision_dashboard.py`,
`test_market_revision_comparison.py`, `test_evaluation_engine.py`,
`test_execution_plan_builder.py`, excluding only
`test_request_recalculates_bound_route_and_is_consumed_once`.
Use PYTHONUTF8=1, bundled Node on PATH and explicit workspace --basetemp.
Focused UI/attention/market-projection suite: 41 passed; broader existing web UI,
redesign and payload suite: 65 passed. Final explanation/UI tests: 20 passed.
Final integrated display/cache/projection/SOC/payload suite after persistence:
66 passed in 12.36s. Tests include malformed/deep/oversized/nonfinite data, I/O
failure, fresh-comparison priority, timestamp and identity guards across restart.
Ruff changed files passed. Mypy changed five source files with imports silent
passed; normal transitive checking reports two existing errors in unchanged
controlled_load_history.py:132, reproduced on the original source snapshot.

One local HTTP recalculation test cannot connect to loopback (WinError10013),
also reproduced on the unmodified source. It is not claimed passing.
Embedded JavaScript syntax and DOM behavior passed; visual browser screenshot
could not run because installed Chromium is absent and Edge launch is denied.
Remote CI, full release suite and live Home Assistant behavior remain unverified.

No version bump, commit, push, deployment, release, plan reset or live command.

## Release authorization

Alex requested release after local implementation. Prepared HEMS dev.323 on
31 October 2026 against verified main 967c3b38ff9f297a40fcb2b7721396a0f99d1b40.
Runtime, add-on manifest and version regression advance together. PR full CI
is the publication gate; installation and live verification are separate.
