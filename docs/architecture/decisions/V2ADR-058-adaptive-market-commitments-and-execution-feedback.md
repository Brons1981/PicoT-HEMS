# V2ADR-058 — Adaptive market commitments and execution feedback

Status: Accepted

## Context

A complete MEP route can contain NOM acquisition, explicit grid-supported
charging and a later storage export.  Live dev.201 evidence showed that measured
PV could make explicit grid charging unnecessary while the later export remained
valuable.  The execution boundary correctly withheld charging, but MEP retained
the due primitive without consuming that result.  The durable commitment also
expired at the end of its first action phase, silently discarding its later
export phase.  Finally, the complete-route EUR 0.01 equivalence tolerance could
place a short export outside the absolute price peak.

## Decision

### Complete commitment lifecycle

A durable MEP commitment spans its complete coalesced segment timeline.  Its
top-level expiry is the end of the final segment, not the end of the first
explicit-power phase.  Reaching an acquisition target cannot clear a commitment
that still contains a future `discharge_at_power` segment.

Acquisition, household support and export remain separately identifiable
segments.  Removing or deferring acquisition does not implicitly cancel export.

### Measured-progress execution result

When V2ADR-057 proves that NOM plus measured PV covers the remaining acquisition,
the primitive boundary records `execution_deferred` with blocker
`measured_pv_progress_covers_grid_charge`.  `dry_run_blocked` is reserved for an
actual authority, provenance, calibration or capability blocker.  A deferred
result is normal execution feedback and remains visible with its plan lineage.

MEP must consume deferred feedback on its next revision: elapsed acquisition is
removed, the remaining grid fallback is shortened from the front and moved no
earlier than necessary, and the last safe completion interval remains reserved.
When no grid energy remains necessary, only the acquisition segment disappears.

Acquisition completion is order-sensitive.  It applies only to charge segments
that precede a still-future export and contribute energy to that export.  A
charge segment after export is recovery, not acquisition, and cannot be removed
because the pre-export SoC already exceeds the safe post-export target.

Every commitment revision coalesces contiguous segments with the same primitive
and source policy.  Revision history remains visible in provenance, while the
executable timeline exposes one continuous NOM window rather than artificial
adjacent fragments.

Commitments written by dev.202 use the defective v4 ordering semantics and are
not recoverable from their persisted segments after an incorrect recovery
removal.  Dev.203 advances the commitment contract to v5 and clears every v4
commitment at restart so MEP reconstructs the complete route from current facts.

### Export from protected stored energy

MEP generates `stored_energy_export` candidates for energy already present above
the physical reserve.  These candidates do not invent a preceding charge or
require restoration to the baseline maximum-SoC horizon target.  They remain
admissible only when every scenario is physically complete, preserves the
minimum reserve, and produces positive incremental value after acquisition cost,
wear and the configured margin.

Exportable energy is bounded by current stored energy, the configured minimum
SoC, known inventory and maximum discharge power.  Household demand and reserve
remain part of full physical simulation.

### Peak-anchored export windows

Every non-empty export candidate contains the interval with the highest positive
net marginal export return.  Candidate windows grow contiguously from that peak,
adding the better-priced adjacent interval first until the safe exportable energy
is placed.  The complete-route EUR 0.01 tolerance may decide whether two routes
are materially different, but it cannot move export away from the higher
marginal-return interval.

Where interval-specific costs are equal, net marginal return reduces to the
published export price.  Exact ties use the earlier adjacent interval and then a
stable route identifier.

### Visibility

The dashboard distinguishes reserved, deferred and released explicit charging.
The projected SoC trajectory remains present for native, acquisition-free and
market routes.  A deferred instruction reports its measured-progress reason;
absence of a future projection is explicit and never represented by silently
removing the line.

## Superseded clauses

This ADR preserves V2ADR-056's broad NOM opportunity and V2ADR-057's measured-PV
admission proof.  It supersedes:

- V2ADR-056's use of charge-phase PV timing ahead of export marginal return;
- V2ADR-057's statement that the selected MEP path remains unchanged after a
  measured-progress deferral;
- commitment expiry at the end of only the first action phase;
- the requirement that every optional export restore the baseline maximum-SoC
  horizon end when protected reserve and household obligations remain satisfied.

## Verification

Tests must prove that:

1. measured PV can defer grid charging without invoking the adapter;
2. deferred execution has an explicit normal status and reason;
3. the next MEP revision shifts, shortens or removes only acquisition;
4. a future export survives acquisition target completion;
5. a complete commitment expires only after its final segment;
6. stored/PV energy can produce an export route without `charge_at_power`;
7. every export window contains the absolute marginal-return peak;
8. export duration grows with safely exportable energy;
9. EUR 0.373 cannot beat EUR 0.388 through complete-route cent tolerance;
10. the SoC projection remains visible without a linked charge segment.
11. export-first recovery charging survives pre-export target evaluation;
12. adjacent identical NOM segments are coalesced after every revision.
13. an active v4 commitment is rejected at restart for a corrective replan.

## Core principle

> Execution feedback changes the plan revision, not the economic authority:
> MEP preserves a safe fallback, keeps independent export value, and anchors
> every export at the best available marginal price.
