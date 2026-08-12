# ADR-038 — Current Storage State Contract

**Status:** Proposed  
**Date:** 2026-08-12

## Context

ADR-037 requires PicoT to derive a `StorageEnergyRequirement` from the projected household energy balance. That derivation requires the current usable storage state as planning evidence.

The existing architecture defines storage capabilities and their technical limits through ADR-030 `CapabilitySnapshotSet`, and it allows future battery SoC to appear in an `EnergyPath` as a projected state. It does not yet define the vendor-independent current storage state that enters a Planning Input Snapshot.

Without an explicit current-state contract, implementation would have to invent where current SoC, usable capacity and measurement confidence belong. That would mix measured state with capability limits and would make requirement calculations ambiguous.

## Responsibility

This ADR has one architectural responsibility:

> Define the immutable, vendor-independent current storage state that is available to one Planner Run.

It does not calculate future storage requirements, construct Candidates, evaluate Energy Paths or execute storage commands.

## Decision

PicoT introduces a `CurrentStorageState` planning-domain record for each logical energy-storage execution scope used by the Planner.

A `CurrentStorageState` contains at least:

- storage state identifier;
- logical `execution_scope_id`;
- matching logical storage `capability_id`;
- current SoC;
- usable storage capacity in Wh;
- measurement timestamp;
- confidence;
- evidence/source references.

The state is vendor-independent. It contains no Home Assistant entity IDs, vendor objects, integration mode names or vendor-specific command values.

## Current SoC

Current SoC is represented as a normalized value from `0.0` through `1.0`.

It is measured state, not a configured minimum, maximum or target. Technical/configured SoC limits remain capability/constraint data and must not be confused with the current measured SoC.

## Usable storage capacity

`usable_capacity_wh` represents the storage energy capacity available to the planning model for converting SoC into energy.

It must be positive and must be supported by explicit configuration, capability data or another traceable source. PicoT does not invent a nominal battery capacity when it is unknown.

Current stored energy can therefore be derived deterministically as:

```text
current_stored_energy_wh = current_soc × usable_capacity_wh
```

This derived value does not need to be stored independently unless a later contract requires it.

The derivation of current stored energy is canonical. Downstream planning layers must consume that canonical result or use the same domain-owned derivation; they must not implement independent variants of the SoC-to-energy calculation.

## Atomic Planning Input

Current storage state belongs to the same atomic temporal input envelope as the other state used by one Planner Run.

A `PlanningInputSnapshot` may contain zero or more `CurrentStorageState` records. Every included record must:

- have a measurement timestamp no later than the snapshot capture time;
- reference one logical storage capability/execution scope used by the matching capability snapshot;
- preserve its own confidence and evidence references;
- remain immutable for the duration of the Planner Run.

For one Planner Run, `CurrentStorageState` is assembled and normalized exactly once as part of the atomic Planning Input Snapshot. All downstream planning layers consume that same immutable state. They must not independently re-read the source, reconstruct a second current storage state or recalculate a competing version of the current state.

The same immutable state may be referenced by multiple downstream calculations. Reuse of the snapshot is required; duplicate state acquisition or reconstruction is not.

Zero storage-state records is valid for households without controllable storage. Missing required storage state for a storage-dependent Candidate does not invalidate the complete Planner Run; it prevents that Candidate/requirement calculation from assuming unknown storage energy.

## Freshness and confidence

Current storage state must preserve measurement age and confidence. PicoT does not silently treat stale or low-confidence SoC as exact.

The accepted freshness policy remains owned by the general Planning Input / capability / source-quality contracts. This ADR does not introduce a second freshness engine.

Where current storage state is too stale, invalid or insufficiently supported for a hard storage feasibility decision, the affected storage-dependent calculation must remain unknown or be excluded with an explicit reason rather than using an invented value.

## Relationship to CapabilitySnapshotSet

`CapabilitySnapshotSet` and `CurrentStorageState` have different responsibilities:

- capability snapshot: what the storage device can technically do and its supported limits;
- current storage state: what energy state the storage device is in now.

A current storage state references the corresponding logical storage capability and execution scope. It does not duplicate supported primitives, power limits, SoC limits, availability or health.

## Relationship to HouseholdState

General household electrical measurements remain in the existing household-state contract. `CurrentStorageState` is introduced separately because storage SoC and usable energy capacity are persistent energy-state dimensions required for temporal planning, not merely instantaneous household power measurements.

This ADR does not move or duplicate existing household measurements.

## Relationship to ADR-037

ADR-038 supplies the missing current-storage input required by ADR-037.

The later deterministic calculation may use:

```text
CurrentStorageState
+ HouseholdLoadForecast
+ PV forecast
+ known future demand / commitments
+ losses and applicable reserves
→ Projected Household Energy Balance
→ StorageEnergyRequirement
```

ADR-038 defines only the first input in that chain. ADR-037 remains authoritative for the projected balance, reserve principle, target planning and grid-use contract.

## Multiple storage devices

The contract supports multiple logical storage execution scopes. Each storage state remains separately identifiable and traceable.

This ADR does not define aggregation, allocation or coordination between multiple batteries. Those are later planning responsibilities and must not be inferred from this state contract.

## Explainability and diagnostics

For every storage state used in planning, PicoT can expose at least:

- logical storage/execution scope;
- current SoC;
- usable capacity used by the model;
- measurement timestamp/age;
- confidence;
- evidence/source references.

When a storage-dependent calculation cannot proceed because SoC or usable capacity is unavailable or insufficiently reliable, the diagnostic reason is explicit.

## Non-goals

This ADR does not define:

- `StorageEnergyRequirement` calculation;
- projected household balance calculation;
- battery target SoC selection;
- Candidate Generation;
- Candidate Evaluation;
- grid-charging permission;
- runtime battery control;
- vendor-specific battery modes;
- battery-health policy;
- multi-battery allocation;
- a new freshness or quality engine.

## Relationship to existing ADRs

- ADR-001 remains authoritative for vendor-independent Core contracts.
- ADR-010 remains authoritative for traceable decision evidence and mapping versions.
- ADR-017 remains authoritative for atomic Planning Input and temporal planning.
- ADR-023 remains authoritative for Opportunity Engine boundaries.
- ADR-024 remains authoritative for Candidate Generation.
- ADR-030 remains authoritative for capability snapshots and projected Energy Path state.
- ADR-031 remains authoritative for the current cost-first Candidate exclusion until all required contracts exist.
- ADR-037 remains authoritative for household energy requirement, storage reserve and grid-use planning.

## Consequences

Positive consequences:

- ADR-037 requirement calculations can use explicit current storage energy instead of inferred or vendor-specific values.
- Measured storage state remains separate from technical capability limits.
- One Planner Run has exactly one normalized current storage truth per logical storage state; downstream layers reuse it instead of reconstructing it.
- The SoC-to-current-energy derivation has one canonical domain definition rather than multiple layer-specific calculations.
- Multiple storage devices remain independently traceable.
- Missing storage data causes explicit degradation/exclusion rather than invented defaults.
- The contract remains vendor-independent and testable.

Costs and risks:

- adapters/input assembly must provide current SoC and usable capacity with traceable evidence;
- source freshness and confidence must be preserved;
- later planning code must explicitly handle unavailable storage state.

## Core principle

> Capability data describes what storage can do. Current Storage State describes where storage is now. For one Planner Run that state is normalized once and reused everywhere. PicoT must know both capability and current state before it can calculate how much stored energy is still required.
