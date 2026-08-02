# ADR-034 — Runtime Monitor, Material Change and Replanning Contract

**Status:** Proposed  
**Date:** 2026-08-02

## Context

ADR-028 defines runtime resource governance, the five-second stabilisation interval, fresh atomic Planning Input Snapshots and the rule that full Planner Runs may not overlap. ADR-016 and ADR-027 define active Execution Plans, commitments and the boundary between planning and execution.

The Core pipeline is now complete through `ExecutionPrimitiveRequest`, but a contract gap remains before live Home Assistant integration:

- runtime observations are not represented by a fixed immutable record;
- material change categories and severity are not defined;
- it is not specified which changes request replanning and which may act immediately;
- planner-run state, stabilisation and pending replan intent are not represented by one deterministic state model;
- a fresh Planning Input Snapshot must be requested without buffering mutable runtime state;
- execution-related changes must remain traceable to plans, capabilities and observations.

Implementing these choices directly in runtime code would hide architecture in the implementation.

## Decision

PicoT introduces a deterministic Runtime Monitor contract inside the existing runtime responsibility. No additional orchestration layer is created.

The Runtime Monitor receives immutable runtime observations and the current immutable runtime coordination state. It returns one immutable `RuntimeMonitorResult` containing:

- all evaluated material-change records;
- the next runtime coordination state;
- whether immediate protective handling is required;
- whether `REPLAN_REQUIRED` is set;
- accumulated deterministic replan reasons;
- no Planning Input Snapshot and no Planner decision.

The Runtime Monitor observes and classifies. It does not plan, modify an Execution Plan or create vendor commands.

## Runtime observation

A `RuntimeObservation` contains at least:

- observation identifier;
- observation kind;
- observed timestamp;
- source reference;
- execution scope identifier where applicable;
- capability identifier where applicable;
- old and new normalized values where applicable;
- unit where applicable;
- source version or mapping version where applicable;
- evidence references.

Initial observation kinds are:

- `CAPABILITY_AVAILABILITY_CHANGED`;
- `CAPABILITY_HEALTH_CHANGED`;
- `CAPABILITY_MAPPING_CHANGED`;
- `HOUSEHOLD_STATE_CHANGED`;
- `FORECAST_CHANGED`;
- `PRICE_CHANGED`;
- `USER_RULES_CHANGED`;
- `STRATEGY_CHANGED`;
- `COMMITMENT_CHANGED`;
- `EXECUTION_OUTCOME_CHANGED`;
- `SAFETY_STATE_CHANGED`;
- `HARD_LIMIT_STATE_CHANGED`;
- `RUNTIME_PRESSURE_CHANGED`.

Observations are immutable, timezone-aware and uniquely identified.

## Material-change classification

Every observation is classified as exactly one of:

- `NON_MATERIAL` — recorded but does not request replanning;
- `MATERIAL_REPLAN` — sets `REPLAN_REQUIRED`;
- `IMMEDIATE_PROTECTIVE_ACTION` — requires immediate Safety or hard-limit handling and also sets `REPLAN_REQUIRED` for the next full Planner Run.

Initial deterministic material rules:

- Safety activation or a hard-limit violation is `IMMEDIATE_PROTECTIVE_ACTION`;
- loss of an actively required capability, unhealthy active capability, mapping change, commitment change, strategy change or User Rule version change is `MATERIAL_REPLAN`;
- execution rejection, failure, timeout or `REPLAN_REQUIRED` outcome is `MATERIAL_REPLAN`;
- forecast, price or household-state changes are material only when the observation producer explicitly marks an accepted threshold or version transition as crossed;
- runtime pressure changes are material only when the effective Planner limits or pressure class change;
- duplicate observations with the same identifier are rejected;
- an observation may not silently downgrade an already pending replan request.

Threshold calculation remains owned by the relevant observation producer or a future accepted domain contract. The Runtime Monitor does not invent numeric tolerances.

## Runtime coordination state

`RuntimeCoordinationState` is immutable and contains at least:

- planner-run state;
- active Planner Run identifier where applicable;
- last Planner Run start and end timestamps;
- stabilisation deadline where applicable;
- `replan_required` flag;
- ordered unique replan reasons;
- last processed observation timestamp;
- runtime pressure state;
- state version.

Initial planner-run states are:

- `IDLE`;
- `RUNNING`;
- `STABILISING`.

Only one full Planner Run may be `RUNNING`.

## Five-second stabilisation

When a Planner Run ends, the state becomes `STABILISING` and the deadline is exactly five seconds after the supplied run-end timestamp.

Observations received while `RUNNING` or `STABILISING` may set `REPLAN_REQUIRED`, but never start another Planner Run.

When the state is `IDLE`, or when stabilisation has expired, a pending replan may produce `FRESH_SNAPSHOT_REQUIRED`.

The Runtime Monitor never builds that snapshot. A snapshot provider must capture all current inputs atomically after the monitor signals that a fresh snapshot is required.

No buffered observation values are copied into a new Planning Input Snapshot merely because they triggered replanning.

## Replanning signal

A `ReplanningSignal` contains:

- signal status;
- requested timestamp;
- ordered unique reasons;
- source observation identifiers;
- required fresh-snapshot flag.

Initial statuses are:

- `NONE`;
- `PENDING`;
- `FRESH_SNAPSHOT_REQUIRED`;
- `BLOCKED_BY_RUNNING_PLANNER`;
- `BLOCKED_BY_STABILISATION`.

Safety and hard-limit handling may execute immediately outside the full Planner Run, but the subsequent Planner Run still requires a fresh atomic snapshot.

## Atomic validation

The Runtime Monitor rejects input when:

- timestamps are not timezone-aware;
- observations are not time ordered;
- duplicate observation identifiers are present;
- observation timestamps precede the state's last processed observation timestamp;
- a `RUNNING` state has no active Planner Run identifier;
- an `IDLE` or `STABILISING` state incorrectly contains an active Planner Run identifier;
- a stabilisation deadline is missing or inconsistent;
- a state transition would create overlapping Planner Runs.

No partial monitor result is returned for invalid atomic input.

## Determinism

For identical immutable inputs and the same implementation version, the Runtime Monitor produces identical:

- classifications;
- replan reasons;
- source observation ordering;
- next coordination state;
- replanning signal;
- identifiers.

Randomness and wall-clock reads inside the monitor are not used. Current time is supplied explicitly.

## Initial implementation boundary

The first implementation includes:

1. immutable runtime observation, material-change, coordination-state and replanning-signal records;
2. deterministic classification of the initial observation kinds;
3. replan reason accumulation without duplicates;
4. one-active-Planner-Run enforcement;
5. the fixed five-second stabilisation interval;
6. `FRESH_SNAPSHOT_REQUIRED` signalling;
7. unit tests and CI coverage.

The first implementation does not include:

- Home Assistant entity subscriptions;
- numeric threshold derivation;
- Planning Input Snapshot construction;
- Planner execution;
- Device Adapter calls;
- Safety action implementation;
- persistence or event-bus infrastructure.

Those connect through later implementation slices without changing this contract.

## Relationship to existing ADRs

- ADR-012: missing required runtime information remains diagnosable and exportable;
- ADR-013: runtime classification is deterministic and contains no AI or LLM;
- ADR-016: Runtime Monitor does not edit Execution Plans;
- ADR-017: material changes lead to a fresh Planning Input Snapshot;
- ADR-027: active commitments remain authoritative runtime context;
- ADR-028: one Planner Run, five-second stabilisation and fresh snapshots are enforced;
- ADR-029: Safety and hard limits may require immediate protective handling;
- ADR-033: plan construction remains separate from runtime monitoring.

## Consequences

- Runtime changes become explicit, immutable and explainable.
- Replanning cannot overlap or use stale buffered state.
- Safety and hard-limit events remain immediate without bypassing fresh-snapshot replanning.
- Home Assistant can later act as an observation source without becoming part of Core planning logic.
- No extra orchestration layer is introduced.

## Core principle

> PicoT observes runtime changes deterministically, classifies only accepted material events, preserves active commitments, never overlaps Planner Runs and requests every replan from a fresh atomic snapshot after the fixed stabilisation interval.
