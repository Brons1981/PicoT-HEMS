# V2ADR-059 — Financially bounded late grid fallback

Status: **Accepted**

Date: 2026-08-30

## Context

V2ADR-056 correctly preserves a broad low-price Opportunity and enumerates
minimal explicit grid-charge subwindows inside it.  Its Evaluation amendment
then preferred the subwindow with the most forecast PV inside
`CHARGE_AT_POWER`.  That local measurement ignores that preceding NOM can
already store the same PV and that early explicit charging can consume battery
headroom before later solar production.

Live dev.203 evidence exposed this on a broad nearly flat price window.  MEP
reserved grid charging around the forecast PV peak even though moving the same
fallback to the end of the Opportunity had no material complete-route cost.

## Decision

Physical completeness, reserve and target feasibility remain mandatory.
Evaluation then selects market charge timing in this order:

1. determine the best worst-case incremental financial result;
2. retain only admitted complete routes no more than EUR 0.01 below that best
   result;
3. inside that cohort prefer the least total simulated grid-to-storage input
   over the complete route on the canonical MEP planning-basis scenario;
4. only when route-wide grid input is equal, prefer the latest feasible
   explicit grid-charge start;
5. use the stable schedule identifier only as the final deterministic tie.

The EUR 0.01 value applies to the complete route, not to an individual price or
quarter.  A materially cheaper earlier route therefore remains decisive.  The
late preference is only a tie-break inside the financially equivalent cohort.

Peak-anchored export construction from V2ADR-058 remains unchanged: every
export candidate already includes the absolute best marginal export interval.
Charge timing does not reinterpret or move that anchor.

## Superseded clauses

This decision supersedes V2ADR-056's Evaluation preference for PV contribution
inside the explicit charge phase, its explicit-phase grid-input comparison and
its statement that start time is never a tie-break.  Candidate generation,
broad Opportunity preservation, the canonical trailing safety interval,
negative-price capacity acquisition and adapter behavior remain unchanged.

## Commitment migration

The planner method advances to v5 and the commitment contract to v6.  A future
or balance-only v5 commitment selected with the former timing rule must be
replanned.  An explicit charge or export primitive already in progress remains
fixed until its normal boundary; timing improvement alone is not a hard-abort
reason.

## Verification

Tests must prove that:

1. routes outside the complete-route EUR 0.01 cohort cannot win by starting
   later;
2. lower total route-wide grid energy wins inside that cohort;
3. equal financial result and equal grid energy select the latest safe charge
   window;
4. the trailing canonical safety interval remains present;
5. every generated export window still includes the absolute export peak;
6. an already active explicit-power phase is not interrupted by migration.

## Core principle

> MEP pays for real value, not clock position: only financially equivalent
> recovery is delayed so NOM can use available PV before the grid fallback.
