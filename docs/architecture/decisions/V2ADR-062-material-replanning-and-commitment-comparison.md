# V2ADR-062 — Material replanning and commitment comparison

Status: **Accepted**

Date: 2026-08-31

## Context

Live dev.206 evidence showed that the active-plan stability mechanism can hide
a material change in the physical starting point.  After a plan was calculated
at 43% SoC, household support reduced storage to 21%.  Measurements continued,
but the live signature suppressed SoC, household, price and PV information
while a commitment was active.  No fresh challenger was evaluated against the
remaining incumbent route.

This behavior conflicts with the event-driven replanning contract in ADR-017
and ADR-034.  It also prevents the incumbent-first comparison required by
V2ADR-052 and the canonical Evaluation ownership fixed by V2ADR-055.

## Decision

### Material change remains observable during a commitment

Ordinary telemetry and expected plan progress remain non-material.  An active
commitment does not, however, remove observations from material-change
classification.

The Runtime Monitor is the sole authority that accepts a producer-owned
material threshold.  An accepted material SoC, household-load, PV, price,
forecast, capability or execution-outcome change requests one fresh atomic
Planning Input Snapshot and one canonical Planner Run.

This remains event-driven replanning.  PicoT does not run a full planning cycle
for every power sample or every one-percent SoC update.

### Canonical challenger before commitment influence

Every accepted material replan follows the canonical order:

1. Opportunity Engine derives evidence-only opportunities.
2. MEP generates complete candidate Energy Paths and physical/financial
   outcomes.
3. The valid remaining incumbent is represented as a complete Energy Path.
4. The canonical Evaluation Engine selects exactly one winner from the
   incumbent and challenger outcomes.
5. The Execution Plan Builder converts the winning Energy Path without
   reinterpretation.
6. The canonical Plan Store persists the resulting retain or replace decision.

Commitment stability may not suppress Opportunity, Candidate or Evaluation
work and may not insert an automatically winning synthetic candidate.

### Symmetric remaining-horizon comparison

The incumbent and all challengers are evaluated from the same current snapshot
and over the same remaining horizon.  Past energy, cost and revenue are sunk
results and are not counted again.  Both sides use the same current SoC,
household forecast, PV forecast, prices, capabilities, conversion model,
reserve requirements and user objectives.

An incumbent's persisted historical financial result is provenance only.  It
is not a comparable current outcome until the remaining route has been
re-evaluated from the fresh snapshot.

### Retain or replace rule

The Evaluation Engine owns the decision:

- a strictly better valid and executable winner replaces the incumbent;
- an equivalent winner retains the incumbent;
- a worse challenger retains the incumbent;
- an invalid or infeasible incumbent cannot win over a valid feasible
  challenger;
- Safety, hard limits, manual authority and capability loss remain decisive;
- anti-flipper and control-chain constraints remain hard feasibility inputs,
  not hidden stability preferences.

"Strictly better" follows the transparent objective order and equivalence
rules of ADR-026 and ADR-032.  A financial switching margin may define
equivalence for the financial objective but may not conceal physical
infeasibility, reserve failure or a higher-priority objective.

### Execution remains separate

Crossing a retained segment boundary still triggers execution on the next poll
as required by V2ADR-061.  A clock boundary consumes the retained plan and does
not by itself request replanning.  Material-change replanning and due-segment
execution are independent signals and neither may suppress the other.

## Superseded clauses

This decision supersedes only:

- V2ADR-052's absolute statement that an active phase is fixed until
  completion except for hard abort reasons; an active phase may also be
  replaced after a canonical, symmetric, strictly-better evaluation when the
  control chain permits interruption;
- V2ADR-061 decision 4 insofar as it suppresses observations before the Runtime
  Monitor can classify accepted material changes.

All remaining lifecycle, persistence, clock-boundary, retry and fail-closed
rules of V2ADR-052 and V2ADR-061 remain active.

## Verification

Tests must prove that:

1. expected SoC and power progress does not request replanning;
2. a producer-accepted material SoC or household-load deviation does request a
   fresh snapshot while a commitment is active;
3. the canonical Candidate Set contains the remaining incumbent and
   challengers before Evaluation;
4. every valid Candidate has a comparable canonical outcome;
5. incumbent and challenger use the same current snapshot and remaining
   horizon;
6. a strictly better challenger replaces the incumbent;
7. an equivalent or worse challenger retains the incumbent;
8. an infeasible incumbent cannot be protected by stability;
9. a segment clock boundary still executes without reopening planning merely
   because time advanced;
10. diagnostics expose the pre-commitment candidates, comparable outcomes,
    decisive objective, equivalence margin and final retain/replace result.

## Core principle

> Commitment stabilizes execution after canonical comparison; it never hides
> material knowledge or replaces Evaluation authority.
