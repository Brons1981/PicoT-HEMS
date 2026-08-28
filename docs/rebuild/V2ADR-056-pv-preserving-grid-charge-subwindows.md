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

Financial outcome remains the first comparison for optional market routes.
When admitted routes have equal financial outcomes, ADR-037's PV-first boundary
prefers the route with less worst-scenario grid-to-storage input. A remaining
tie prefers the later recoverable explicit-power subwindow, then the stable
route identifier. These values and the selected schedule remain reproducible
from stored Candidate evidence.

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

Future commitments selected with the former full-Opportunity charge semantics
are not valid incumbents for the new Candidate contract. The commitment method
version is advanced and a not-yet-started previous-version commitment is
cleared during restart recovery with an explicit incident reason. The next run
uses a fresh atomic snapshot and selects through the normal canonical pipeline.

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

## Core principle

> A broad cheap-price Opportunity says when grid acquisition may be attractive;
> MEP decides how little explicit charging is needed and when it best preserves
> PV room, while Evaluation alone selects the complete route.
