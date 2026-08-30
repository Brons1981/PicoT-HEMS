# V2ADR-061 — Committed segment clock-boundary execution

Status: **Accepted**

Date: 2026-08-30

## Context

The live loop suppresses a full canonical run while decision-relevant Planning
Input remains unchanged.  During an active commitment it intentionally treats
price, PV, ordinary SoC progress and power telemetry as plan progress rather
than reasons to select a new plan.

Live dev.205 evidence showed that this stability rule also hid the transition
between two segments of the same commitment.  The export segment ended at
22:15 and `BALANCE_DISCHARGE_ONLY` began, but the commitment-level signature
remained unchanged.  The measurement loop stayed healthy while canonical
execution was skipped, leaving Zendure in `Snel ontladen`.  Restarting cleared
the previous signature and immediately applied the correct balance mode.

## Decision

1. The active execution phase of every retained commitment is
   decision-relevant clock input.  Its signature contains the due segment's
   start, end, primitive and source policy.
2. Crossing a segment start or end changes that signature and starts exactly
   one canonical cycle on the next normal poll.
3. This cycle consumes the already retained commitment.  It does not reopen
   Opportunity Detection, move the market window, revise financial selection
   or replace the plan merely because time advanced.
4. Ordinary telemetry remains suppressed while the commitment is active, so
   the fix does not restore continuous full-plan recalculation.
5. A `dispatch_failed` or rejected external command does not commit the new
   input signature.  The next poll therefore retries the same required segment
   transition.  Successful dispatch commits the signature and remains
   idempotent.
6. Manual-override authority and the existing fail-closed adapter boundary
   remain decisive; a clock transition does not bypass either one.

## Verification

Tests must prove that:

1. the signature is stable during one committed segment;
2. it changes exactly at the boundary from `DISCHARGE_AT_POWER` to
   `BALANCE_DISCHARGE_ONLY`;
3. the changed signature starts a canonical cycle without a restart;
4. a failed execution retains the previous signature and retries next poll;
5. a successful execution commits the new signature and subsequent identical
   polls do not execute again;
6. existing commitment stability, fast-mode mapping and manual-override tests
   remain green.

## Core principle

> Planning stability may suppress new decisions, but it may never suppress the
> next action of the plan already in force.
