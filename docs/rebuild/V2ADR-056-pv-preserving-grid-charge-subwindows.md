# V2ADR-056 — PV-preserving Grid-charge Subwindows

Status: **Accepted**

Date: 2026-08-28

## Controlling decisions

ADR-001 through ADR-037 and the accepted V2 ADR series remain authoritative.
This decision extends MEP Candidate construction only. It does not change the
canonical price Opportunity contract, the validated independent daily physical
simulator, Evaluation ownership, plan commitment, execution or adapter
translation.

## Context

ADR-036 deliberately preserves a complete relative low-price block as objective
Opportunity evidence. Such a block can span most of a solar day even when only
a small amount of explicit grid-supported charging is required. Treating the
complete Opportunity as one `CHARGE_AT_POWER` segment can fill storage before
the expected PV peak, unnecessarily displace later PV to grid export and make
the selected route financially or physically inferior to a later short charge.

The Opportunity Engine may not solve this by selecting a preferred start,
duration, device or primitive. Those decisions belong to complete MEP Candidate
construction and Evaluation under ADR-024, ADR-032, ADR-037, V2ADR-050 and
V2ADR-055.

## Decision

MEP treats a low-price Opportunity as a containing acquisition interval, not as
the duration of an explicit-power command.

For every grid-supported market acquisition MEP:

1. derives the maximum linked charge-input energy from storage limits,
   conversion losses and the complete market route;
2. enumerates only interval-minimal contiguous subwindows on canonical planning
   boundaries whose proven charge-power capacity can supply that energy;
3. does not generate longer variants that are dominated by a shorter subwindow
   with the same start;
4. preserves one canonical interval between the end of an explicit-power
   subwindow and the end of the containing Opportunity when the Opportunity has
   sufficient spare duration;
5. retains the containing Opportunity identifier and bounds as immutable route
   evidence;
6. simulates every retained subwindow as part of a complete household Energy
   Path across every accepted PV scenario.

This is bounded Candidate branching: starts are limited to source intervals in
one accepted Opportunity and each start produces at most one physically minimal
subwindow. MEP does not scan arbitrary minutes or rank raw price points outside
the Candidate pipeline.

## Complete storage-mode lifecycle

For an optional market route, the containing low-price Opportunity uses the
canonical PV-acquisition intent outside the exact explicit-power subwindow.
The complete generic lifecycle is therefore:

```text
BALANCE_DISCHARGE_ONLY
→ BALANCE_BIDIRECTIONAL
→ CHARGE_AT_POWER with PV-preferred/grid-allowed source policy
→ BALANCE_BIDIRECTIONAL
→ BALANCE_DISCHARGE_ONLY
```

Only phases that have positive duration appear in the Energy Path. A later
linked export remains a separate `DISCHARGE_AT_POWER` segment. Vendor mode names
remain adapter-only details.

`BALANCE_BIDIRECTIONAL` allows expected PV surplus to be stored before and after
the explicit grid-supported phase. The complete simulation accounts for its
possible discharge effect during household deficit; Candidate construction
does not assume that balancing only charges.

## Evaluation

Simulation derives signed settlement, PV use, grid-to-storage input, reserve,
target and recoverability for every complete timing alternative. Evaluation
remains the only selection authority.

Financial outcome remains the first comparison for optional market routes. The
objective-specific financial equivalence tolerance is EUR 0.01 over the complete
route. Evaluation first determines the best worst-case incremental result and
retains only admitted routes whose result is at most EUR 0.01 below that best
result. A route outside that cohort cannot win through PV timing. This explicit
tolerance extends ADR-032's exact-value rule and is not the plan-commitment
switching margin.

Within the financially equivalent cohort, ADR-037's PV-first boundary prefers
the route with the most simulated PV-to-storage input during the exact
grid-supported phase on the canonical MEP planning-basis scenario. The daily
PV-basis stage projects the selected basis into the lower simulation lane:
tomorrow initially uses `(source lower + source central) / 2`, while the
remaining current day may explicitly adapt to lower, midpoint or central from
complete actual evidence. Evaluation does not calculate another forecast
average.

If usable PV contribution is equal, Evaluation prefers less grid-to-storage
input during that exact phase on the same MEP basis, then the better minimum
incremental result per exported kWh, then the lexicographically smallest stable
route identifier. Start time is not an objective or tie-break. Lower, central
and upper simulations all remain mandatory for physical and financial
admission. These values and the selected schedule remain reproducible from
stored Candidate evidence.

## Boundaries

- Price Opportunity Detection still emits the complete window unchanged and
  performs no ranking or device allocation.
- MEP Candidate construction owns exact subwindow timing, requested power and
  the complete lifecycle.
- The physical and financial simulators derive outcomes but select nothing.
- Evaluation selects one existing complete Candidate and creates no new timing.
- Execution Plan Builder converts the Winning Energy Path unchanged.
- Execution and adapters do not delay, shorten, extend or economically reinterpret
  the selected subwindow.
- Negative all-in import Opportunities remain complete capacity-acquisition
  routes under V2ADR-054; this decision does not shorten rewarded negative-price
  consumption.
- The frozen native daily-planner simulation and charge-window discovery are not
  modified by this decision.

## Commitment migration

Future commitments selected with either the former full-Opportunity charge
semantics or the former later-subwindow tie-break are not valid incumbents for
the new Candidate contract. The commitment method version is advanced and a
not-yet-started previous-version commitment is cleared during restart recovery
with an explicit incident reason. The next run uses a fresh atomic snapshot and
selects through the normal canonical pipeline.

An explicit-power phase that already started remains fixed under ADR-027 and
V2ADR-052 until its normal end or an accepted hard abort reason. The migration
does not interrupt an active previous-version phase merely to improve timing.

## Verification

Tests must prove that:

1. one broad low-price Opportunity remains one unchanged Opportunity;
2. a smaller linked energy requirement produces multiple physically minimal
   subwindow Candidates rather than one full-window charge;
3. no retained subwindow is longer than required by more than one canonical
   interval;
4. a safety interval is preserved when spare Opportunity duration exists;
5. the selected complete route uses PV acquisition before explicit grid charging
   when that is financially equal or better;
6. only the exact subwindow maps to `CHARGE_AT_POWER` and grid permission;
7. the surrounding Opportunity maps to canonical balancing intents;
8. all three PV scenarios remain part of physical and financial admission;
9. negative-price capacity routes retain their complete-window behaviour;
10. plan commitment and adapter behaviour remain unchanged.
11. routes within EUR 0.01 of the best complete financial result use explicit
    MEP-basis PV contribution to select their charge timing;
12. a route more than EUR 0.01 better remains financially decisive;
13. no later-start preference remains after objective comparison.

## Core principle

> A broad cheap-price Opportunity says when grid acquisition may be attractive;
> MEP decides how little explicit charging is needed and when it best preserves
> PV room, while Evaluation alone selects the complete route.
