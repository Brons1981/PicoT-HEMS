# ADR-043 — Storage Requirement Temporal Semantics

**Status:** Proposed  
**Date:** 2026-08-12

## Context

ADR-037 introduced `StorageEnergyRequirement` as the stored energy that must be available by a future time to support the projected household path and reserve policy.

Live validation exposed an ambiguity in the first implementation. `StorageRequirementDeriver` currently sets `required_by` to the start of the largest projected storage drawdown. When a new live snapshot is captured after that drawdown has already started, the derived `required_by` becomes equal to `captured_at`.

The implementation is internally consistent with its own tests, but the field then mixes three different temporal meanings:

1. when the protected storage drawdown starts;
2. how long the stored energy must protect household demand;
3. when additional energy, if any, must be acquired.

Those are not the same concept.

A scalar `required_by` therefore becomes misleading in live planning. In particular, a requirement may already be fully satisfied by current stored energy while `required_by == now`, even though no charging action is required. Treating that timestamp as a charging deadline would produce incorrect urgency and could distort price-window selection.

PicoT must correct the domain contract rather than compensate in runtime, dashboards, Candidate Generation or Execution.

## Decision

PicoT separates **storage protection semantics** from **energy acquisition semantics**.

### StorageEnergyRequirement describes the protected energy interval

The canonical requirement must explicitly represent:

- `required_energy_wh` — stored energy required to support the projected household path;
- `required_soc_percent` where applicable;
- `protection_starts_at` — first instant from which that stored energy is needed for the identified projected drawdown;
- `protected_through` — instant through which that energy protects the projected household path;
- reason/category;
- confidence;
- evidence references;
- reserve contribution where applicable.

`protection_starts_at` may legitimately equal the current snapshot time when the relevant drawdown is already active.

That does **not** imply that additional charging is required now.

### Acquisition urgency is derived separately

Whether additional energy must be acquired is determined only after comparing the requirement with the canonical current storage state and effective storage limit.

The recoverability/acquisition result must expose at least:

- `additional_energy_required_wh`;
- whether additional acquisition is required at all;
- maximum technically acquirable energy before the protection boundary;
- latest technically feasible acquisition/charge start when additional energy is required;
- technical recoverability;
- evidence and confidence.

When `additional_energy_required_wh == 0`, there is no charging/acquisition deadline. The latest charge start is therefore semantically **not applicable** and must not be represented as `protection_starts_at` or `captured_at` merely to fill a timestamp field.

### `required_by` is retired from the canonical requirement

The ambiguous `StorageEnergyRequirement.required_by` field is retired by this ADR.

During implementation migration, code must move directly to `protection_starts_at` and `protected_through`. PicoT must not maintain two independent temporal interpretations in parallel.

Any temporary compatibility needed to keep tests/builds atomic must be confined to a single migration commit/PR and must not be exposed as a second planner path or runtime decision source.

## Derivation semantics

For a projected household energy balance, PicoT identifies the relevant future drawdown as already defined by the accepted ADR-037 reserve logic:

- `protection_starts_at` is the position from which the selected projected drawdown begins;
- `protected_through` is the future minimum point that completes that drawdown;
- `required_energy_wh` is the selected drawdown requirement after effective storage and confidence/reserve policy are applied.

Each new live snapshot recomputes the remaining projected requirement from that snapshot forward.

Therefore, when part of a previously projected drawdown has already occurred:

- the remaining `required_energy_wh` may decrease;
- `protection_starts_at` may equal the new snapshot time because protection is already active;
- `protected_through` remains a future point when the projected protected period is still ongoing;
- acquisition urgency depends on whether current stored energy is below the recomputed requirement.

This prevents `requirement_energy_wh` from becoming a historical total and prevents `protection_starts_at` from being misused as an action deadline.

## Planner use

Candidate Generation must not interpret `protection_starts_at` alone as a command to charge.

The planner sequence remains canonical:

```text
Planning Input Snapshot
→ projected household energy balance
→ StorageEnergyRequirement
   - required energy
   - protection starts
   - protected through
→ compare with CurrentStorageState
→ PV-only feasibility / technical recoverability
→ additional energy acquisition need
→ Candidate Generation
→ Simulation / Outcomes
→ Evaluation
→ Execution
```

A price Opportunity remains evidence only. A storage requirement remains a requirement only. Additional acquisition need and recoverability determine whether charging candidates are necessary and how much temporal freedom remains.

## Price-window consequence

The broad `LOWEST_PRICE_WINDOW` from ADR-036 is not an execution window.

When additional storage energy is required, a future timed Candidate may select economically preferable quarter-hour intervals inside or around relevant Opportunities, constrained by:

- `additional_energy_required_wh`;
- `protection_starts_at`;
- `protected_through`;
- maximum charge power and other capabilities;
- expected PV/Solcast energy;
- household load forecast;
- source policy;
- conversion losses;
- price intervals;
- technical recoverability.

This ADR does not itself define the ranking algorithm for those timed Candidates.

## Observability

Diagnostics and the Planner Inspector must distinguish the concepts explicitly.

At minimum they should expose:

- required storage energy;
- protection starts at;
- protected through;
- current stored energy;
- additional energy required;
- additional acquisition required yes/no;
- latest feasible charge/acquisition start when applicable;
- technical recoverability.

A timestamp that is not applicable must be shown as unavailable/not applicable rather than substituted with the current time.

## Fail-closed behaviour

If PicoT cannot derive a valid protected interval, it must not invent a deadline.

If current storage state is unavailable, additional acquisition need is unavailable rather than assumed.

If additional energy is required but technical recoverability cannot be established, Candidate Generation must fail closed for dependent charging paths.

## Relationship to ADR-037

ADR-043 clarifies and supersedes only the temporal field semantics of `StorageEnergyRequirement` introduced by ADR-037.

All other ADR-037 responsibilities remain unchanged, including:

- complete household energy planning;
- conservative reserve policy;
- PV-first feasibility;
- explicit grid-supported charging permission;
- Opportunity-as-evidence semantics;
- Candidate/Evaluation/Execution boundaries.

## Consequences

Positive consequences:

- `captured_at` can no longer masquerade as a charging deadline merely because a drawdown is already active;
- current storage sufficiency and future acquisition urgency are separated cleanly;
- live requirements continue to represent only the remaining future need;
- timed price/PV candidates get the correct temporal constraints;
- dashboard semantics become explainable without presentation-layer fixes;
- no parallel planner or runtime workaround is required.

Costs:

- `StorageEnergyRequirement` and dependent tests/contracts require a coordinated migration;
- technical recoverability must represent “no additional acquisition required” without a fake latest-start timestamp;
- diagnostics and live observer attributes must migrate to the new names.

## Non-goals

This ADR does not define:

- the timed Candidate ranking algorithm;
- the economic value function;
- vendor-specific Zendure modes;
- a new Opportunity detector;
- a runtime workaround for legacy `required_by` behaviour.
