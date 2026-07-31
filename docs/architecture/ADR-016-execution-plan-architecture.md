# ADR-016 — Execution Plan Architecture

**Status:** Accepted  
**Date:** 2026-07-31

## Context

The Planner must not emit isolated commands. It must produce a complete, time-bound and explainable plan that can be validated, stored, superseded, replayed and translated into device actions.

## Decision

The Planner produces an immutable `ExecutionPlan` for a planning horizon. The Execution layer does not make energy decisions; it schedules, validates and dispatches the plan's segments.

```text
PlanningInputSet
→ PlannerDecisionRecord
→ ExecutionPlan
→ Execution Plan Store
→ Execution Scheduler
→ Execution Queue
→ Command Validator
→ Execution Primitive
→ Device Adapter
→ Vendor Command
```

## Plan structure

An Execution Plan contains at least:

- plan ID, schema version and revision;
- creation time and explicit timezone;
- `valid_from` and `valid_until`;
- Planner Decision and Planning Input references;
- target logical device or execution scope;
- lifecycle status;
- ordered time segments;
- fallback policy reference.

Each segment contains:

- segment ID and order;
- explicit start and end time;
- one primary Execution Primitive;
- any requested power and generic SoC constraints;
- purpose and evidence references;
- rule or planner origin where applicable.

For one target, segments may not overlap. Adjacent identical segments should be merged.

## Lifecycle

Supported plan states include:

- `PROPOSED`
- `VALIDATED`
- `SCHEDULED`
- `ACTIVE`
- `SUPERSEDED`
- `COMPLETED`
- `CANCELLED`
- `EXPIRED`
- `FAILED`

Only one plan may be active per execution scope. A newer plan supersedes an older plan explicitly and preserves the history.

## Validation and execution

A deterministic validator checks schema, chronology, overlap, target support, required primitive parameters, power and SoC bounds, fallback availability and unresolved conflicts.

Before each segment is executed, a Command Validator checks the current reality again, including:

- active plan and segment validity;
- no newer plan exists;
- Safety does not block further PicoT commands;
- adapter and mapping availability;
- current SoC and device limits;
- capability health;
- request freshness;
- whether material circumstances require replanning.

Possible command-validation outcomes:

- `APPROVED`
- `REJECTED`
- `CANCELLED`
- `REPLAN_REQUIRED`

Execution must be confirmed through acknowledgement and, where possible, observed telemetry. Execution records distinguish confirmed, acknowledged-but-not-observed, rejected, timed out, failed and cancelled outcomes.

## Replanning

The Execution layer never edits a plan to make a new energy decision. Material changes produce:

```text
REPLAN_REQUIRED
→ new PlanningInputSet
→ new PlannerDecisionRecord
→ new ExecutionPlan
```

## User Rule conflict handling

If active User Rules conflict, PicoT does not select a winner and does not modify rule contents.

The deterministic flow is:

```text
USER_RULE_CONFLICT_DETECTED
→ USER_RULE_CONFLICT_AUTO_DISABLED
→ disable all conflicting rules
→ log rule status changes and conflict evidence
→ send push notification and show dashboard warning
→ run the normal PicoT Planner again with remaining active rules
→ create a replacement Execution Plan
```

The standard Planner fallback prevents the battery remaining in standby while waiting for a user to notice the conflict.

The content of the conflicting rules remains unchanged. Only their enabled state changes. Each change records the affected rule, prior and new state, timestamp, `AUTO_DISABLED`, reason `USER_RULE_CONFLICT`, and actor `PICOT_RULE_ENGINE`.

The final plan records the conflict record, disabled rule IDs, effective active rules and that standard-planner replanning was used.

## User override

A confirmed manual user action must not be silently overwritten by the active plan. Until a dedicated override contract is accepted, PicoT does not automatically reassert a planned state after a detected manual override.

## Explainability

Every execution request remains traceable through:

```text
ExecutionRequest
→ ExecutionPlan segment
→ ExecutionPlan
→ PlannerDecisionRecord
→ CandidateEvaluation
→ PlanningInputSet
→ CapabilitySnapshotSet
```

Vendor translation is logged separately from the generic planner intent.

## Core principle

> The Planner produces no direct commands. It produces a time-bound, validated and fully explainable Execution Plan. Each segment is translated into a vendor-specific command only after current-state validation.
