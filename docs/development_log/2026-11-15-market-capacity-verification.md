# Market capacity as a maximum - implementation evidence

Scope: locally implement the approved first increment on HEMS dev.339, main
`68503d888892a132febd1faa936809700e10466a`. Parent coordinator owns settings,
tariffs, integration, rollback archive and the new architecture decision. No
release, live installation, commit, reset or second daily assignment is made here.

## Responsibility and behavior

- `MarketUserRule` accepts a capacity maximum from zero to one. Zero is an explicit
  disabled instruction; new-candidate generation rejects it. Pipeline/settings
  wiring prevents creating a new zero-capacity day assignment. Existing completed
  or bound assignments keep their existing lifecycle and cannot obtain a new budget.
- `market_export_windows.export_volume_targets` supplies five unranked volumes:
  20/40/60/80/100% of the effective maximum. At a 25% maximum these are
  5/10/15/20/25% of usable storage capacity. The exact effective maximum is retained.
- Candidate generation bounds a waiting assignment by the smaller of its frozen
  maximum and the currently configured maximum. Existing transition export limits
  remain additional bounds. No assignment is rewritten or replenished.
- Every maximum-volume timing remains available. For each of the four smaller
  volumes, three representative highest-price timings are retained, with explicit
  deterministic start/end tie order. This bounded branching is not a claim of a
  continuous global optimum. Omitted timing count and search limits are in candidate
  assumptions alongside effective maximum and selected energy.
- Each volume gets its own energy-weighted fictitious charge reference, including
  charge/discharge efficiencies. It is not charged as a real acquisition cost.
- Exact user-spread and conservative necessary SOC checks can reject impossible
  candidates before physical/recovery simulations. The SOC precheck assumes no house
  consumption and uses the larger retained interval endpoint stock, so it is only
  an upper bound, not a new reservation or dispatch decision.
- Admission accepts a positive explicit requested volume below the frozen maximum.
  A physically truncated request remains rejected; smaller routes are independently
  constructed and fully simulated. Shared canonical capability validation also
  checks complete smaller paths that require no charge revision.
- Final spread evidence uses the complete candidate's annual bonus consumption,
  including preceding PV export. Within an interval, the effective bonus rate is
  allocated proportionally to PV and storage export. Imported energy does not
  reduce the export bonus allowance or bonus quantity. Financial settlement owns
  actual complete-path money; Evaluation alone selects between admissible outcomes.

ADR-019.4 already defines a daily maximum. ADR-019.6/.7 recovery, post-main window,
one-per-day identity, protected charging and current revision/execution rules remain.
No changes to Store economics, execution commands or main charge selection.

## Files owned by this increment

`src/picot/domain/market_user_rule.py`
`src/picot/planner/market_export_windows.py`
`src/picot/planner/market_price_windows.py`
`src/picot/planner/market_route_admission.py`
`src/picot/v2/market_rule_planning.py`
`tests/test_market_capacity_maximum.py`
`tests/test_market_complete_recovery_candidates.py`

## Fresh evidence

Four initial regressions failed for the intended missing behavior: zero rejected;
smaller volume rejected by exact allocation equality; no smaller-volume price-reference
argument; and a profitable 10% route hidden by a 25% spread rejection. All four passed
after implementation. Additional tests cover bounded deterministic search, frozen
maximum admission, a lower current maximum, zero on a waiting assignment, bonus cap
and preceding PV exports, and simultaneous imported excluded household energy.

Final fresh affected suite: **66 passed in 161.97s**. It comprises
`test_market_rule_selection.py`, `test_market_capacity_maximum.py`,
`test_market_price_windows.py`, `test_market_daily_assignment.py`,
`test_market_route_admission.py` and `test_market_complete_recovery_candidates.py`.
The rolling household boundary case took 100.52s; all lifecycle, commitment budget,
zero/lower-cap, smaller route, recovery and bonus quantity cases passed.
Captured output: `scratch/market-capacity-final-tests.log` in the parent workspace.
Fresh Ruff on the five production files and both changed test files passed;
scoped Mypy on all five production files passed with `--follow-imports=silent`.
Broader cross-layer integration remains the coordinator's verification scope.

Existing complete-recovery test assumptions were updated to permit smaller complete
requests and retained recovery without a new charge window. Its exact maximum-volume
winning financial result and all capability/recovery invariants are retained.

## Runtime measurements and bounded search choice

Actual archived snapshots, current 25% maximum, central forecast, existing 2027 tariff
policy, EUR0.05/internal-discharge-kWh wear, identical historical commitments:

| Case | Baseline | Bounded candidate generation | Selected result |
|---|---|---|---|
| November 10, `snapshot-e24c88314dca55c3` | 4.68s, 97 bridge calls, no admitted route | 1.78s, 55 bridge calls, 12 complete alternatives | 816Wh battery allocation (10%); EUR0.035512 incremental net |
| September 16, `snapshot-3f502078440cb24d` | 31.29s, 103 bridge calls, 36 alternatives | 43.68s, 45 bridge calls, 116 complete alternatives | 1224Wh (15%); EUR0.070121 versus old 2040Wh (25%), EUR0.043631 |

These local wall times are indicative and include some concurrent verification;
they are not a NUC runtime guarantee. Full recovery alternatives explain why bridge
call count alone does not predict time. Sunny case remains a material latency increase.

An intermediate exhaustive five-volume implementation took 226.62s on the sunny case
and selected the same winner; it was replaced by bounded representative timing search.
An earlier ten-volume broad suite was stopped as superseded, not reported as passing.
Final implementation has no new timeout, partial-result publication or hidden pruning
of original maximum-volume timings. Benchmark scripts/results remain in workspace
`scratch/benchmark_market_capacity.py` and corresponding JSON outputs.
