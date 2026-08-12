# PicoT HEMS Architecture Map

## Purpose

This map provides a concise overview of the accepted PicoT HEMS Core architecture. Detailed rules remain authoritative in the linked ADRs.

## Core principles

- PicoT Core is deterministic and contains no AI or LLM at runtime.
- The Planner consumes logical capabilities, never vendor-specific entities.
- Planning is based on immutable, atomic input snapshots.
- Every decision remains traceable and explainable.
- User Rules may constrain behaviour but may not bypass hard limits or Safety.
- Vendor translation happens only after a generic Execution Primitive has been validated.
- No additional orchestration layer is introduced between the accepted pipeline stages.

## Closed PicoT Core v0 pipeline

```text
PlanningInputSnapshot
        │
        ▼
Opportunity Engine
        │
        ▼
OpportunitySet
        │
        ▼
Candidate Engine
        │
        ├── CapabilitySnapshotSet
        ├── EnergyPath
        └── CandidateSet
        │
        ▼
Evaluation Engine
        │
        ├── CandidateOutcomeSet
        ├── EvaluationRecord
        └── Winning Candidate + Winning Energy Path
        │
        ▼
Execution Plan Builder
        │
        ├── ExecutionPlanSet
        ├── scope-specific ExecutionPlan
        └── ExecutionPlanSegment
        │
        ▼
Execution Engine
        │
        ├── due-segment selection
        ├── current capability validation
        ├── CommandValidationOutcome
        ├── ExecutionPrimitiveRequest
        └── ExecutionRecord / ExecutionResult
        │
        ▼
Execution Primitive
        │
        ▼
Device Adapter
        │
        ▼
Vendor Command
```

The pipeline is architecturally closed through `ExecutionPrimitiveRequest`. Device Adapters and vendor integrations remain separate from PicoT Core.

## Stage responsibilities

### Planning Input

Produces one immutable `PlanningInputSnapshot` with the active Planner Strategy, Household State, forecasts, runtime pressure and relevant version references.

### Opportunity Engine

Detects objective, evidence-backed Opportunities. It does not select devices, assign power or create plans.

### Candidate Engine

Constructs a small, diverse and meaningful `CandidateSet` from accepted scenario templates, Opportunities and logical capabilities. Each Candidate references exactly one immutable Energy Path.

### Evaluation Engine

Compares supplied Candidate outcomes in Planner Strategy order and applies deterministic tie-breaks. It selects one existing Candidate without hidden aggregate scoring.

### Execution Plan Builder

Converts the Winning Energy Path without reinterpretation into an atomic `ExecutionPlanSet`, with one immutable plan per execution scope.

### Execution Engine

Selects due plan segments, validates current logical capability conditions and emits vendor-independent `ExecutionPrimitiveRequest` records. It does not create vendor commands or make new energy decisions.

### Device Adapter

Translates validated Execution Primitives into vendor-specific commands and records acknowledgement and observed behaviour separately.

## Cross-cutting models

### Planner Strategy

User Objectives and the Optimisation Profile guide the full Planner pipeline without becoming a separate layer.

### Explainability and traceability

Every request remains traceable through:

```text
ExecutionPrimitiveRequest
→ ExecutionRecord
→ ExecutionPlanSegment
→ ExecutionPlan
→ EvaluationRecord
→ Winning Candidate
→ EnergyPath
→ OpportunitySet
→ PlanningInputSnapshot
→ CapabilitySnapshotSet
```

### Runtime governance

Only one full Planner Run may be active. A fixed five-second stabilisation interval applies between runs. Material changes request replanning from a fresh atomic snapshot.

### Safety and hard constraints

Safety, phase-current limits, voltage limits, fuse limits, capability health and hardware limits always override optimisation preferences.

## Primary ADR map

- ADR-015 — Execution Primitive Architecture
- ADR-016 — Execution Plan Architecture
- ADR-017 — Planning Decision Pipeline
- ADR-023 — Opportunity Engine
- ADR-024 — Candidate Engine
- ADR-025 — Planner Strategy Model
- ADR-026 — Evaluation Engine
- ADR-027 — Execution Plan Commitment and Dynamic Power Allocation
- ADR-028 — Runtime Resource Governance
- ADR-029 — Household Power Capacity Management
- ADR-030 — Energy Path and Capability Snapshot Contract
- ADR-031 — Candidate Scenario Construction Contract
- ADR-032 — Candidate Evaluation Contract
- ADR-033 — Winning Energy Path to Execution Plans
- ADR-034 — Runtime Monitor, Material Change and Replanning Contract
- ADR-035 — Home Assistant Adapter and Controlled Dispatch Contract
- ADR-036 — Price Opportunity Detection Contract
- ADR-037 — Household Energy Requirement, Storage Reserve and Grid Use Contract
- ADR-038 — Current Storage State Contract
- ADR-039 — PV Energy Timeline Contract

ADR-040 — Authoritative Observation Source Ingestion Contract is currently **Proposed** and is therefore not yet part of the accepted architecture.

See [`ARCHITECTURE_DECISIONS.md`](ARCHITECTURE_DECISIONS.md) for the complete accepted ADR index.

## Current implementation status

Implemented and covered by CI include:

- Planning Input Snapshot contracts;
- Forecast and Household State contracts;
- Planner Strategy Model;
- Opportunity Engine;
- Capability Snapshot and Energy Path contracts;
- Candidate Engine and Evaluation Engine;
- Execution Plan Builder and Execution Engine;
- Runtime Monitor and replanning-state contracts;
- Home Assistant adapter/dispatcher with explicit dry-run/live gating;
- ADR-037/038/039 storage, household-balance and PV-energy planning chain;
- direct Home Assistant adapters/observers for selected physical sources;
- Ruff, Mypy and Pytest quality checks.

## Current integration boundary

The main remaining distance to a real closed loop is integration wiring rather than another planner redesign:

```text
Authoritative physical HA sources
        │
        ▼
validated input adapters / mappings
        │
        ▼
Fresh atomic PlanningInputSnapshot
        │
        ▼
existing Planner pipeline
        │
        ▼
Winning Energy Path
        │
        ▼
ExecutionPlanSet
        │
        ▼
Execution Engine
        │
        ▼
Home Assistant adapter / dispatcher
        │
        ▼
observed execution result
        │
        ▼
Runtime Monitor
        │
        ▼
REPLAN_REQUIRED → fresh snapshot
```

The Runtime Monitor is no longer the next missing component; it exists. The next implementation focus is authoritative observation ingestion, atomic live snapshot construction and complete Home Assistant closed-loop wiring/validation.

See [`CLOSED_LOOP_READINESS_AUDIT_2026-08-12.md`](CLOSED_LOOP_READINESS_AUDIT_2026-08-12.md).
