# ADR-033 — Winning Energy Path to Execution Plans

**Status:** Accepted  
**Date:** 2026-08-01

## Context

ADR-016 defines the immutable, time-bound `ExecutionPlan` and states that only one plan may be active per execution scope. ADR-026 and ADR-032 define the immutable Evaluation Result containing one Winning Candidate and its matching Winning Energy Path. ADR-030 defines that one Energy Path may contain Path Segments for several execution scopes.

A remaining contract gap prevents a correct implementation of plan construction:

- one Winning Energy Path may contain several execution scopes;
- ADR-016 describes an Execution Plan for one target logical device or execution scope;
- the architecture does not yet state whether one Winning Energy Path produces one multi-scope plan or several scope-specific plans;
- the exact relationship between Path Segments and Execution Plan Segments is not fixed;
- baseline paths may contain no controllable segments;
- plan revision, lifecycle, fallback and traceability values must be assigned without hidden implementation policy.

Implementing this conversion directly in code would place architectural policy inside the Plan Builder.

## Decision

PicoT converts one successful `EvaluationResult` into an immutable `ExecutionPlanSet` containing zero or more scope-specific `ExecutionPlan` records.

This does not introduce a new runtime layer. Plan construction remains the final responsibility of the existing Planner pipeline before the existing Execution Engine.

The pipeline remains:

```text
EvaluationResult
→ ExecutionPlanSet construction
→ Execution Plan Store
→ Execution Engine
→ Execution Primitive
→ Device Adapter
→ Vendor Command
```

## Execution Plan Set

An `ExecutionPlanSet` belongs to exactly one successful Evaluation Result and contains:

- plan-set identifier;
- schema version;
- snapshot identifier;
- strategy version;
- Evaluation Record identifier;
- Winning Candidate identifier;
- Winning Energy Path identifier;
- creation timestamp;
- ordered scope-specific Execution Plans;
- implementation version.

The set is immutable and atomic. No partial set is returned when input validation fails.

A valid baseline Winning Energy Path with no controllable Path Segments produces a valid empty `ExecutionPlanSet`. PicoT does not invent standby commands merely to make the set non-empty.

## Scope-specific plans

One `ExecutionPlan` is produced for each distinct `execution_scope_id` present in the Winning Energy Path's Path Segments.

Each plan:

- targets exactly one execution scope;
- contains only segments for that scope;
- uses the lifecycle state `PROPOSED` when first constructed;
- starts at revision `1`;
- preserves the full plan validity interval from the Winning Energy Path horizon;
- references the Planning Input Snapshot, Evaluation Record, Winning Candidate and Winning Energy Path;
- references the capability mapping version used by the Winning Energy Path;
- contains an explicit fallback policy reference;
- remains vendor-independent.

Plans are ordered lexicographically by stable execution-scope identifier. Plan identifiers are derived deterministically from the snapshot, Evaluation Record, Winning Candidate, Winning Energy Path and execution scope.

## Segment conversion

Every Path Segment in the Winning Energy Path converts to exactly one Execution Plan Segment in the plan for the same execution scope.

The conversion preserves without reinterpretation:

- chronological interval;
- Execution Primitive;
- requested power;
- generic SoC constraints;
- purpose;
- evidence references;
- capability reference;
- optional Energy Profile reference.

Execution Plan Segment order is recalculated per execution scope as a contiguous sequence starting at `1`, using chronological order followed by stable Path Segment identifier order.

The Plan Builder does not:

- change a primitive;
- change requested power;
- add or remove a controllable action;
- merge segments;
- split segments;
- create vendor commands;
- make a new energy decision.

Adjacent-segment merging, when desired, belongs to Candidate Energy Path construction before Evaluation. The committed Winning Energy Path is not rewritten during plan construction.

## Plan validity

For the first implementation:

- `valid_from` equals the Winning Energy Path horizon start;
- `valid_until` equals the Winning Energy Path horizon end;
- `created_at` is supplied explicitly and must be timezone-aware;
- `created_at` may not be later than `valid_until`;
- every converted segment must remain within the validity interval.

No implicit local timezone conversion is performed.

## Fallback policy

Plan construction requires one explicit, non-empty fallback policy reference supplied as atomic input.

The Plan Builder does not select or invent a fallback policy. The referenced policy is interpreted later by validation and execution according to accepted Execution contracts.

## Atomic validation

Before construction, PicoT rejects input when:

- Evaluation Result status is not `WINNER_SELECTED`;
- Winning Candidate or Winning Energy Path is absent;
- Evaluation Record, Candidate and Energy Path references do not match;
- snapshot or strategy versions differ;
- any Path Segment references a capability not present in the Energy Path;
- any segment lies outside the Energy Path horizon;
- creation time is not timezone-aware;
- fallback policy reference is empty.

No plans are produced from `NO_VALID_CANDIDATE`.

## Traceability

Every Execution Plan and Plan Segment remains traceable to:

- Planning Input Snapshot;
- Evaluation Record;
- Winning Candidate;
- Winning Energy Path;
- original Path Segment;
- logical capability;
- capability mapping version;
- evidence and purpose.

Vendor translation and execution acknowledgements remain separate records owned by the Execution Engine and Device Adapters.

## Determinism

For identical immutable inputs and the same implementation version, plan construction produces identical:

- plan-set identifier;
- plan identifiers;
- plan ordering;
- segment identifiers and ordering;
- lifecycle, revision and references.

Random identifiers are not used.

## Initial implementation boundary

The first implementation includes:

1. immutable `ExecutionPlanSet`, `ExecutionPlan` and `ExecutionPlanSegment` records;
2. lifecycle state `PROPOSED` for newly constructed plans;
3. atomic Evaluation Result validation;
4. deterministic grouping by execution scope;
5. exact Path Segment conversion;
6. explicit empty plan set for a baseline path without controllable segments;
7. unit tests and CI coverage.

It does not include:

- plan validation against live device state;
- scheduling;
- queueing;
- commitment lifecycle transitions;
- dynamic power allocation;
- retries, timeouts or acknowledgements;
- vendor translation.

Those remain responsibilities of ADR-016 and ADR-027 within the existing Execution Engine.

## Relationship to existing ADRs

- ADR-015: Execution Plan Segments retain generic Execution Primitives;
- ADR-016: defines Execution Plan structure, lifecycle and execution boundary;
- ADR-017: the committed plan derives from one complete Winning Energy Path;
- ADR-026 and ADR-032: only the selected Winning Candidate and Energy Path enter plan construction;
- ADR-027: commitments and dynamic allocation begin after plan construction;
- ADR-030: Path Segments and Energy Paths remain immutable and traceable;
- ADR-031: scenario construction remains separate from plan commitment.

## Consequences

- Multi-scope Winning Energy Paths become an atomic set of scope-specific plans.
- The one-active-plan-per-scope rule from ADR-016 remains enforceable.
- Baseline selection does not create fictional commands.
- Plan construction remains a deterministic conversion rather than another optimisation step.
- No additional orchestration layer is introduced.

## Core principle

> The Winning Energy Path is not re-planned during commitment. PicoT deterministically groups its existing Path Segments by execution scope and converts them into an atomic set of immutable, scope-specific Execution Plans for the existing Execution Engine.
