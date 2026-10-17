# EV battery isolation and future grid review

Alex approved repair after the 18:02 diagnostic showed tomorrow's 02:30-06:00
grid charge while the current SOC projection reaches 100% around 04:00.
Baseline main: 600b65c1d50b4c947644248b4ca0d25f8da37961 (HEMS dev.300,
Energy Devices dev.8). The initial repair was local; subsequent release
authorization is recorded below. No live action is included.

## Evidence

`picot-diagnostics - 2026-10-17T180256.985.zip` in Downloads contains the native
assignment for 2026-10-18. Its long window originated at 14:59 local, with an
active EV session expecting 11437.44 Wh and storage_support_allowed=true.
At 17:33 the EV session is absent and battery SOC is 100%; at 18:01 the display
projection begins at 98%, reaches 64.77% at the planned 02:30 start and 100%
by 04:00. The bound main window still ends at 06:00.

The session reader ignored the producer's requested exclusion and inherited
physical regulation availability as permission to use storage. RAW fallback
therefore reintroduced EV demand into battery support. The automatic advice
producer's false flag alone did not fix this consumer behavior.

## Repair boundary

All admitted EV measurements and sessions request battery exclusion, including
direct starts and older persisted sessions. Physical availability of the
corrected meter is separate evidence. Missing session measurement preserves the
session identity for physical guarding but cannot add an unseparated demand
profile to the household forecast. Actual grid costs and measured demand remain
physical; history is not rewritten.

The existing canonical executor guards unsafe discharge when exclusion cannot
be physically proven. It remains the only actuator owner; manual ownership
rules are preserved. The existing canonical optional grid-reduction path is the
repair seam for future oversized battery charging; no independent scheduler,
fabricated PV evidence or destructive plan reset is allowed.

The exclusion latch is persisted in the existing commitment store separately
from economic plan replacement/clearing. Missing reports retain it; fresh zero
measurement releases it. Failed persistence is retried before dispatch. Corrected
control evidence expires after three seconds. NOM becomes charge-only (or
Standby when unavailable) without correction; discharge-only becomes Standby.
Fixed discharge is blocked during EV activity even with correction because it
bypasses the corrected meter. The intent simulator likewise credits neither
household discharge nor export during such an excluded-demand export interval.

Future SOC review uses the existing optional grid-reduction proof and canonical
Evaluation, including the EUR 0.01 minimum improvement and all pending goals.
It uses an explicit future-state evidence identity, never invented future PV
actuals, and does not reopen a running owner. Fresh state reads are valid for an
unchanged SOC value. Inactive unknown household guards may use a non-fallback
forecast; active unexplained excess remains protected. Poll timestamps do not
change the review identity; changed EV exclusion does.

Physical protection applies while PicoT owns automatic control. It is a response
to measured/session evidence through the existing polling and actuator boundary,
not an electrical hardware interlock or permission to override manual ownership.

## Canonical diagnostic replay

The final complete Planning Input in the diagnostic is
`snapshot-139ed650793d6ed7`, captured 2026-10-17 17:33:03 local. Its SOC value is
100%, last changed at 16:09 local and explicitly read again at 17:33. The replay
uses the measured snapshot round-trip efficiency 0.8185 through
`MarketDailyPlannerRuntime.planning_configuration`; no fresh measurement or PV
actual was invented. The 18:01 SOC projection is a separate later observation.

The existing gate required completed PV intervals for tomorrow. Future-state
proof now admits the existing physical removable-quarter check, which proves
600 Wh of configured grid input removable while retaining reserve and daily
goals. A second existing gate valued a future acquisition-rate improvement on
the *current* deficit, making every improvement zero at current 100% SOC.
Only the explicit future-state comparison now uses one shared deficit from the
unchanged incumbent projection at the first future grid-charge boundary.
Current-day and ordinary PV/net comparisons retain their previous semantics.

Replaying the unchanged diagnostic input and a local copy of its commitment
store selects a winner through the normal Candidate, Evaluation and Plan Builder:

| Item | Retained plan | Selected plan |
| --- | --- | --- |
| Plan | `plan-62cbf0232de62b23` | `plan-63b46f343f21626f` |
| Grid-charge window, Amsterdam | 02:30–06:00 | 04:15–05:45 |
| Command-window duration | 3.5 hours | 1.5 hours |
| Acquisition value | 0.352581994845 EUR/kWh stored | 0.316179587926 EUR/kWh stored |

Canonical improvement on the shared future refill need is EUR 0.10463215744,
above the unchanged EUR 0.01 admission threshold. Removed grid slots become NOM
through the existing revision rules; the other owned route intervals remain.
Window capacity is not a claim of actual purchased energy: the simulator already
accounts for saturation, household flows, PV and losses. Fresh live inputs may
produce a different window. No live store or control was changed by this replay.

`tests/test_future_grid_reduction.py` exercises actual canonical selection,
completed-owner preservation, future/running/stale-state gates, unchanged value
with fresh HA read, 98% SOC with inactive versus active unknown load guard,
stable evidence and EV-exclusion changes, and future deficit valuation at 100%
current SOC. Existing PV, net-balance and running-load tests cover compatibility.

Final verification: 118 integrated EV policy, session, execution and future-review tests passed; 15 simulator/economic regression tests passed. After the final active-unknown-load guard adjustment, all 10 focused future-review tests passed (including 98% and 100% SOC). Additional existing comparison and retention suites passed. Ruff and mypy checks passed.

## Release authorization

Alex requested release on 2026-10-17. HEMS 2.0.0-dev.301 and Energy Devices
0.4.0-dev.9 will be published together through PR and green CI from unchanged
main 600b65c1d50b4c947644248b4ca0d25f8da37961. Both add-ons need updating.
See V2ADR-064.7 for the accepted isolation and future-state contract.
Installation and live verification remain separate; fresh live inputs may
produce a different window from the diagnostic replay.

The first full PR CI run passed 2209 tests with one skip and exposed one
regression in failed legacy market-window transition atomicity. Optional future
review persisted a no-change assessment before that transition's deliberately
failed write. The repair defers optional grid review while a legacy transition
is pending, preserving the original byte-identical store on failure. The
existing transition regression is retained unchanged; future review can resume
after the transition has completed. Full CI is rerun before publication.
