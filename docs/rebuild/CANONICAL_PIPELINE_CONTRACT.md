# PicoT HEMS Canonical Pipeline Contract

Status: **FROZEN REBUILD CONTRACT — Phase A**

## Historical architecture baseline

The architectural baseline for this rebuild is explicitly pinned to:

- `docs/architecture/ARCHITECTURE_MAP.md`
- commit `8197abbefd969f10da5a8f27244862be07998299`
- created `2026-08-01T21:12:40Z`
- commit message: `docs(architecture): add PicoT Core v0 architecture map`

This is the original Architecture Map revision, before the 2026-08-12 closed-loop readiness update and ADR-040 work. Later implementation-status text, later integration conclusions and ADR-040+ are not architectural input to Phase A.

Detailed rules remain authoritative in the Accepted ADRs represented by that architecture baseline. This document does not redesign PicoT; it turns that already accepted architecture into a strict rebuild and live-validation contract.

## Verified original pipeline

The 2026-08-01 Architecture Map defines this pipeline:

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

The original map states that the pipeline is architecturally closed through `ExecutionPrimitiveRequest`; Device Adapters and vendor integrations remain separate from PicoT Core.

## Original stage responsibilities — preserved

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

## Original cross-cutting architecture — preserved

- Planner Strategy guides the full Planner pipeline without becoming a separate layer.
- Every request remains traceable through `ExecutionPrimitiveRequest → ExecutionRecord → ExecutionPlanSegment → ExecutionPlan → EvaluationRecord → Winning Candidate → EnergyPath → OpportunitySet → PlanningInputSnapshot → CapabilitySnapshotSet`.
- Only one full Planner Run may be active.
- A fixed five-second stabilisation interval applies between runs.
- Material changes request replanning from a fresh atomic snapshot.
- Safety, phase-current limits, voltage limits, fuse limits, capability health and hardware limits always override optimisation preferences.

## Rebuild invariants

These invariants are implementation guards for preserving the accepted architecture; they do not add planner stages or new optimisation behaviour.

1. **One canonical fact → one owner.**
2. **One canonical derivation → one owner.**
3. Downstream components consume/reference canonical records; they do not silently reinterpret, replace or mutate them.
4. A derived value remains traceable to its canonical source record(s) and designated derivation.
5. **No parallel path to the same result.** The rebuild uses the accepted pipeline rather than an observer-planner, ADR-specific planner, battery planner, price planner or alternative orchestration route.
6. `PlanningInputSnapshot` is immutable for the Planner Run.
7. A component creates only records belonging to its accepted responsibility.
8. No component may suppress another component's canonical input merely because it considers that information unnecessary downstream.
9. Live validation must prove that the same immutable records/references survive the intended chain without hidden replacement.
10. Green CI alone is not proof of architectural integration; the canonical live path must also be traceable.

## Nine fixed live validation cards

The nine cards are a **dashboard projection of the original pipeline and its external command boundary**, not nine newly invented Core layers:

```text
1  Planning Input
2  Opportunity Engine
3  Candidate Engine
4  Evaluation Engine
5  Execution Plan Builder
6  Execution Engine
7  Execution Primitive
8  Device Adapter
9  Vendor Command / Observed Result
```

Cards 1–7 expose the accepted planning/execution chain. Cards 8–9 expose the external adapter/vendor boundary needed to verify the physical closed loop. Their presence on the dashboard does not move Device Adapter or Vendor Command into PicoT Core.

Each card must show, where applicable:

- current run/snapshot reference;
- canonical input reference(s);
- canonical output reference(s);
- creation/capture timestamp;
- stage status;
- explicit blocker/error;
- provenance/lineage to the preceding accepted record;
- stage-specific values already defined by the accepted architecture/ADR contracts.

The card body may grow only with functionality that belongs to that accepted responsibility. Testing a new feature does not create an extra orchestration layer or parallel dashboard pipeline.

## Lineage validation

The live validation path must be able to prove the original traceability chain:

```text
PlanningInputSnapshot
→ OpportunitySet
→ Candidate / EnergyPath
→ EvaluationRecord / Winning Candidate
→ ExecutionPlan / ExecutionPlanSegment
→ ExecutionRecord / ExecutionPrimitiveRequest
→ Device Adapter translation
→ Vendor Command / observed behaviour
```

For validation purposes, a record/reference can be classified as:

- **UNCHANGED** — canonical record/reference consumed without reinterpretation;
- **DERIVED** — a new record was created by the component contractually responsible for that derivation and retains provenance;
- **NOT_CONSUMED** — the component did not require the fact; the source record itself remains unchanged;
- **LINEAGE_BREAK** — a required reference/provenance link disappeared;
- **ILLEGAL_MUTATION** — an immutable canonical record was changed/replaced outside its accepted ownership contract.

`LINEAGE_BREAK` and `ILLEGAL_MUTATION` fail the rebuild validation gate.

## Phase A exclusion boundary

Phase A deliberately does **not** use:

- the 2026-08-12 `ARCHITECTURE_MAP.md` implementation-status update as architectural authority;
- the 2026-08-12 closed-loop readiness conclusion as proof that the implementation is architecturally correct;
- ADR-040 or later ADRs as justification for changing the 2026-08-01 pipeline;
- current code structure as evidence that a component belongs in the architecture.

Later ADRs and implementation work may be reviewed separately after the original accepted pipeline is reconstructed and proven. They are not allowed to retroactively redefine this Phase A baseline.

## Phase A completion gate

Phase A is complete when:

1. the historical baseline is pinned to commit `8197abbefd969f10da5a8f27244862be07998299`;
2. the original pipeline and responsibilities above are treated as immutable rebuild boundaries;
3. the rebuild invariants protect ownership, immutability and traceability without adding a new planner layer;
4. the nine-card dashboard is understood only as a live validation projection of that architecture;
5. Phase B starts with the smallest possible end-to-end path through these existing boundaries before planner intelligence is filled in stage by stage.
