# V2ADR-068: Joint EV and battery advice

Status: implemented locally, awaiting release verification.

Alex requested on 2026-11-01 that an explicit ED charging request minimise the
combined household, EV and battery bill. The retained battery route may change
when the combination costs less. The existing intermediate-SOC preservation
constraint excluded cheaper EV windows that consumed PV intended for storage.

## Decision

For each assessed contiguous EV window, compare the retained battery route and
canonical daily-main recalculation candidates. Existing discovery, physical
simulation, tariff settlement, Candidate validity, Evaluation and Plan Builder
remain authoritative. Advice itself never writes commitments or dispatches.

Use the same fully priced battery horizon and required terminal reserve for all
routes. The reserve must be at least the baseline projection's terminal stock;
additional stock receives no speculative financial credit. Preserve the daily
100% obligation, other owners, and market/supplemental binding checks. The total
cash cost includes flows after EV charging ends. A missing full battery price
horizon blocks comparison. An EV deadline extending beyond available prices or
the battery horizon gives a specific provisional reason. All start/end tariff
boundaries and exact capacity edges inside the published horizon are assessed;
the old 200-start sampling limit is removed.
Earliest scheduling includes a 120-second calculation and acceptance lead.
Immediately before final Evaluation, the live worker supplies a fresh earliest
execution time (now plus 60 seconds). Starts that elapsed during computation are
invalid candidates; their costs remain visible in diagnostics.

Financial pruning settles every discovered window and only skips strictly more
expensive validity groups after finding a valid cheaper group. Zero-PV reuse is
limited to physically equivalent placements with no retained-export conflict and
a shared interval grid; every reused winner is simulated and validated again for
the actual EV placement. A failed reuse falls back to ordinary discovery.

Selecting advice creates a pending EV session. User-accepted planned demand is
visible to HEMS immediately, but ED cannot energise the charger before a matching
HEMS commitment receipt. A main-loop callback revalidates fresh inputs, ownership
and reserve, then the existing Store atomically binds the canonical route and
receipt. No worker writes the Store; no new direct device-control path is added.
The main loop reloads ownership after adoption even when receipt publication
fails. ED ignores wrong identities and late confirmations. Durable receipts
support retries/restarts only while the selected battery plan remains active.

This explicit acceptance authorises revision of the selected daily owner only.
It does not relax ordinary autonomous replanning or substitute a second planner.
Pending manual recalculation, changed ownership, stale selection and invalid fresh
physical proof fail closed with an explicit reason.

## Evidence and presentation

ED exports request, candidate costs/rejections, comparison horizon, terminal
reserve, selection identity and acceptance status. Full advice events are retained
for 48 hours and repeated identical exchanges are deduplicated. The dashboard
distinguishes combined total cost from incremental EV cost, names missing evidence,
and shows waiting/failed confirmation. Legacy advice remains readable.

Tests cover cheaper joint routing, reserve and daily-goal preservation, passive
advice, atomic publication, wrong/stale/cancelled receipts, publication failure,
pending-demand accounting, restart and the full request-to-execution chain.
