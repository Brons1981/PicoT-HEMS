# Market policy first increment: integration and rollback

Local implementation on HEMS dev.339, commit
`68503d888892a132febd1faa936809700e10466a`. Not released or installed.
Decision: V2ADR-071. Frozen ADRs and HC/ED source are unchanged.

## Implemented

- Maximum trading capacity accepts fractional percentages, including 37.5 and 0.
  Smaller admissible routes are evaluated within the frozen day maximum.
- Advanced settings expose capacity, spread, recovery margin and wear, plus
  explicit optional Zonneplan export bonus configuration. Settings request the
  existing planning recalculation without resetting commitments or day budgets.
- Existing configured wear migrates into the canonical user profile. Subsequent
  changes are prospective in financial history and available to the passive review.
- Shared daylight bonus calculation applies to positive eligible export value,
  actual gross export and the annual allowance. Each alternative has independent
  allowance state; PV opportunity valuation has a separate cumulative allowance.
- Annual allowance begins with an explicit timestamped export reading and is
  extended only from raw export evidence. Unknown evidence is visible and does
  not block the base planner. Financial estimates never become planner facts.

## Responsibility review

Input preparation carries policy and source facts. Candidate and Outcome
production calculate alternatives. Evaluation selects the economic winner.
Builder/Store/execution retain their existing responsibilities. The dashboard
projects settings and evidence. Main charge selection, protected PV choice,
physical recovery and one daily assignment remain under existing contracts.

Independent review found and resolved three issues: ordinary edits must not
re-anchor a prior-year export reading on January 1; consecutive PV charges must
not reuse the same counterfactual bonus budget; corrupt optional evidence must
not interrupt ordinary planning. Regression tests cover all three.

## Fresh verification

- Settings/UI/material-replanning/passive-review group: 129 passed.
- Bonus/tariff/settlement/ledger/measurement group: 140 passed.
- Market capacity/admission/recovery group: 66 passed (161.97 seconds).
- Scoped Mypy and Ruff checks passed for changed production code and tests.
- Actual archived November and September snapshots replayed under the 2027
  tariff scenario. See the capacity verification report for exact assumptions,
  results and bounded-search limitations.
- Sunny combined bonus replay uses an explicitly synthetic location/annual
  anchor, not an inferred user reading. It verifies the complete portfolio and
  that every candidate remains within its maximum. Final replay: 174 complete
  alternatives, 1632 Wh selected (20%), EUR0.112416 incremental net, 50.78 seconds.
  Output: `scratch/replay-bonus-market-policy-work-snapshot-3f502078440cb24d.json`.

This is targeted verification, not a claim that every repository test or a live
HA installation was exercised. The sunny no-bonus replay took approximately
44 seconds versus 31 seconds on the baseline; target NUC latency remains unmeasured.

## Rollback

Complete original 1179-file snapshot: `rollback-hems339-20261115.zip`, with Git
blob verification before editing and a per-file SHA256 manifest. Archive SHA256:
`7915b3a9ef29666778e9b7f27b838f79029b92c0274d270b776f514ad33ff2fc`.

Original dev.339 user-rule and financial-ledger loaders were executed against
newly saved records and both succeeded. User-rule schema 2 and ledger schema 1
remain compatible through additive fields. No original source files were removed.

## Remaining scope

The five-position slider and multiple daily trade strategies are deferred.
Bonus starts inactive and needs explicit location and annual export evidence.
The bounded five-volume search is deterministic, not a continuous global optimum.
No version increment, commit, push, release or installation was performed.
