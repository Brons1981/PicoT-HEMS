# PicoT HEMS Architecture Decisions

This index contains accepted architectural decisions. Detailed ADR files may be added when a decision requires more context.

## Accepted decisions

### ADR-001 — Planner uses capabilities only
The planner consumes logical capabilities and never vendor-specific entities or integration details directly.

### ADR-002 — Discovery is not a runtime fallback mechanism
Discovery is used to identify candidate sources during setup or targeted rediscovery. It is not continuously rerun because a source is temporarily unavailable.

### ADR-003 — Semantic validation precedes selection
A source may only be selected after it has passed deterministic semantic validation.

### ADR-004 — Capability mappings are persistent
A validated mapping remains selected until objective evidence proves it permanently invalid.

### ADR-005 — Temporary unavailability is not invalidity
`TEMPORARILY_UNAVAILABLE` must not trigger automatic replacement or rediscovery.

### ADR-006 — Rediscovery is capability-scoped
Rediscovery affects only the invalid capability. Unrelated domains and capabilities remain untouched.

### ADR-007 — Source replacement is never silent
PicoT may propose an alternative source and explain its advantages and disadvantages, but user confirmation is required when a change can affect behaviour.

### ADR-008 — Primary meter and realtime power source are distinct roles
A primary P1 meter may remain authoritative while a separate CT meter is deliberately selected for faster realtime power measurements.

### ADR-009 — Mapping history is retained
Selection reasons, rejected candidates, timestamps, lifecycle changes, and historical mapping versions must remain traceable.

### ADR-010 — Planner decisions reference mapping versions
Every stored decision must identify the capability mapping version and source data used.

### ADR-011 — Configuration ownership is explicit
Externally managed configuration is read-only for PicoT unless ownership is explicitly assigned to PicoT.

### ADR-012 — Missing expected information triggers diagnosis
PicoT must not merely state that information was not recorded when required layers should have recorded it. The surrounding available data and layer statuses must be exportable for diagnosis.

### ADR-013 — Runtime contains no AI or LLM
The future PicoT bot and runtime interfaces are deterministic and may only retrieve and present stored historical data, decision records, and available forecasts.

### ADR-014 — Architecture is future-proof; v0.1 implementation remains minimal
Necessary structural contracts are designed now, while non-essential functionality is deferred to the roadmap.

### ADR-015 — Execution Primitive Architecture
The Core expresses desired energy behaviour through generic Execution Primitives. Device Adapters translate those primitives into vendor-specific modes and commands.

Detailed record: [`ADR-015-execution-primitives.md`](ADR-015-execution-primitives.md)

### ADR-016 — Execution Plan Architecture
The Planner produces a complete, immutable and time-bound Execution Plan. Execution validates each due segment before translating it into a vendor-specific command. Conflicting User Rules are automatically disabled, logged and followed by standard-planner replanning.

Detailed record: [`ADR-016-execution-plan-architecture.md`](ADR-016-execution-plan-architecture.md)

### ADR-017 — Planning Decision Pipeline
PicoT evaluates complete energy paths over a rolling planning horizon, replans on material knowledge changes, and uses confidence, recoverability and Candidate Space Reduction before final evaluation.

Detailed record: [`ADR-017-planning-decision-pipeline.md`](ADR-017-planning-decision-pipeline.md)

### ADR-018 — User Objective Model
Users configure transparent personal objectives rather than technical battery modes. An Objective Mapping Layer translates understandable UI input into internal Planner weights with noticeable influence.

Detailed record: [`ADR-018-user-objective-model.md`](ADR-018-user-objective-model.md)

### ADR-019 — Energy Profile Model
User Rules and Energy Profiles remain separate Core concepts. Expert-mode Planning Hints may describe user-declared expected energy impact and can later evolve into Managed Energy Profiles without modifying rule logic.

Detailed record: [`ADR-019-energy-profile-model.md`](ADR-019-energy-profile-model.md)

### ADR-020 — Dual User Input Model
PicoT supports Simple and Expert input where useful. Both compile to the same validated internal model; Expert mode provides more expressiveness but never more authority.

Detailed record: [`ADR-020-dual-user-input-model.md`](ADR-020-dual-user-input-model.md)

### ADR-021 — Layered Diagnostic Isolation
PicoT diagnostics isolate configurable layers through temporary fallbacks while preserving original configuration and essential baseline operation.

Detailed record: [`ADR-021-layered-diagnostic-isolation.md`](ADR-021-layered-diagnostic-isolation.md)

### ADR-022 — Progressive Complexity Principle
PicoT keeps the default experience simple and exposes additional complexity only by explicit opt-in. New features should extend existing Core models instead of introducing parallel systems.

Detailed record: [`ADR-022-progressive-complexity-principle.md`](ADR-022-progressive-complexity-principle.md)

### ADR-023 — Opportunity Engine
The Opportunity Engine derives objective, evidence-backed opportunities and constraints from the Planning Input Set without selecting devices, assigning power or creating plans.

Detailed record: [`ADR-023-opportunity-engine.md`](ADR-023-opportunity-engine.md)

### ADR-024 — Candidate Engine
The Candidate Engine produces a small, diverse and meaningful set of complete household energy scenarios using hard reduction, controlled branching, strategic guidance and safe dominance removal.

Detailed record: [`ADR-024-candidate-engine.md`](ADR-024-candidate-engine.md)

### ADR-025 — Planner Strategy Model
User Objectives and the Optimisation Profile form a cross-cutting immutable strategy that guides the entire Planning Decision Pipeline without becoming a separate pipeline layer.

Detailed record: [`ADR-025-planner-strategy-model.md`](ADR-025-planner-strategy-model.md)

### ADR-026 — Evaluation Engine
The Evaluation Engine selects one Winning Candidate through deterministic comparison per strategic objective and a fixed, explainable tie-break order instead of an opaque total score.

Detailed record: [`ADR-026-evaluation-engine.md`](ADR-026-evaluation-engine.md)

### ADR-027 — Execution Plan Commitment and Dynamic Power Allocation
Execution Plans become stable commitments. PicoT optimises around running tasks and only changes technically and explicitly flexible parts while respecting anti-flipper limits.

Detailed record: [`ADR-027-execution-plan-commitment.md`](ADR-027-execution-plan-commitment.md)

### ADR-028 — Runtime Resource Governance
PicoT governs CPU, memory, storage and Planner runtime through resource budgets, pressure states, graceful degradation, a fixed five-second stabilisation interval and fresh atomic Planning Input Snapshots.

Detailed record: [`ADR-028-runtime-resource-governance.md`](ADR-028-runtime-resource-governance.md)

### ADR-029 — Household Power Capacity Management
PicoT manages energy flows within the physical phase distribution, always enforces hard per-phase limits, exposes Net Balance as an optimisation objective and provides evidence-based installation advice.

Detailed record: [`ADR-029-household-power-capacity-management.md`](ADR-029-household-power-capacity-management.md)

### ADR-030 — Energy Path and Capability Snapshot Contract
The Candidate Engine builds complete, vendor-independent Energy Paths from atomic logical Capability Snapshot Sets while preserving limits, health, freshness, mapping versions and traceability.

Detailed record: [`ADR-030-energy-path-capability-snapshot-contract.md`](ADR-030-energy-path-capability-snapshot-contract.md)

### ADR-031 — Candidate Scenario Construction Contract
The Candidate Engine applies accepted scenario templates to explicit logical capability roles and constructs only complete, technically supported and explainable Energy Paths.

Detailed record: [`ADR-031-candidate-scenario-construction-contract.md`](ADR-031-candidate-scenario-construction-contract.md)

### ADR-032 — Candidate Evaluation Contract
The Evaluation Engine compares immutable Candidate outcomes in strategy order, records every objective and tie-break, and selects one existing Candidate without hidden scoring.

Detailed record: [`ADR-032-candidate-evaluation-contract.md`](ADR-032-candidate-evaluation-contract.md)

### ADR-033 — Winning Energy Path to Execution Plans
A successful Evaluation Result is converted deterministically into an atomic set of immutable, scope-specific Execution Plans without changing the Winning Energy Path.

Detailed record: [`ADR-033-winning-energy-path-to-execution-plans.md`](ADR-033-winning-energy-path-to-execution-plans.md)

### ADR-034 — Runtime Monitor, Material Change and Replanning Contract
The Runtime Monitor classifies immutable observations, preserves one-active-Planner-Run discipline, enforces the five-second stabilisation interval and requests every replan from a fresh atomic snapshot.

Detailed record: [`ADR-034-runtime-monitor-material-change-replanning-contract.md`](ADR-034-runtime-monitor-material-change-replanning-contract.md)

### ADR-035 — Home Assistant Adapter and Controlled Dispatch Contract
One validated Execution Primitive Request is translated through one explicit, versioned Home Assistant mapping. Dry-run and live use the same immutable service call.

Detailed record: [`ADR-035-home-assistant-adapter-contract.md`](ADR-035-home-assistant-adapter-contract.md)

### ADR-036 — Price Opportunity Detection Contract
Price Opportunity Detection is part of the canonical Opportunity Engine and deterministically describes low-price, negative-price and high-export-value windows across the rolling planning horizon without ranking, selecting devices or bypassing Candidate Generation and Evaluation.

Detailed record: [`ADR-036-price-opportunity-detection-contract.md`](ADR-036-price-opportunity-detection-contract.md)
