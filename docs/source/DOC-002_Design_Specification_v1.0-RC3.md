# DOC-002 — Design Specification

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Project | PicoT HEMS |
| Status | Release Candidate |
| Version | 1.0-RC3 |
| Date | 2026-07-26 |
| Source format | Markdown |

## 1. Document information

### 1.1 Purpose

This document defines the functional design and normative software architecture of **PicoT HEMS**.

It describes the architectural building blocks, responsibility boundaries, decision flow, planning behaviour, execution model and implementation constraints that together form the PicoT reference architecture.

This specification is normative unless explicitly stated otherwise. Implementations are expected to conform to the architectural rules defined in this document.

### 1.2 Audience

- Project Owner
- Software Architects
- Developers
- Testers
- Future Contributors

### 1.3 Related documents

- DOC-000 Architecture Overview
- DOC-001 Vision & Principles
- DOC-003 Data Dictionary
- DOC-004 Entity Registry
- DOC-005 Architecture Decision Records
- DOC-006 Design Decisions
- DOC-007 Project Status
- DOC-008 Roadmap
- DOC-009 Test Plan
- DOC-010 Project Rules

## 2. Purpose and vision

### 2.1 Purpose

PicoT HEMS is an intelligent, modular and deterministic Home Energy Management System that continuously plans, coordinates and orchestrates the residential energy ecosystem.

Its purpose is to determine the best achievable energy strategy for every planning interval while respecting physical limitations, verified device capabilities, assessed health, applicable constraints, active user controls and configured energy policies.

PicoT does not optimise individual devices in isolation. It evaluates the complete energy ecosystem, including production, consumption, storage, forecasts, market conditions and user objectives, to produce a coherent and explainable execution plan.

Every significant decision shall be:

- technically feasible;
- explainable and traceable;
- verifiable after execution;
- adaptable to changing operating conditions; and
- consistent with the Authority Hierarchy.

Home Assistant is the primary and only runtime platform during design, implementation and stabilisation. PicoT retains a platform-independent internal architecture based on canonical domain models.

### 2.2 Vision

PicoT HEMS is the intelligent planning and orchestration platform for residential energy management.

Its architecture is built around five defining qualities:

- **Planning** — determine future strategy instead of reacting only to current events.
- **Intelligence** — combine measurements, forecasts, learned behaviour and policy into a consistent operational picture.
- **Coordination** — operate connected devices as one coherent energy system.
- **Orchestration** — translate strategy into controlled and verified execution.
- **Transparency** — make every significant decision understandable, traceable and verifiable.

The ultimate objective is increasingly autonomous operation without sacrificing user authority, predictability, operational stability or explainability.

### 2.3 Scope

PicoT covers the complete decision lifecycle from acquiring measurements to verifying and explaining execution outcomes.

Within this scope, PicoT is responsible for:

- acquiring and normalising data from supported integrations;
- assessing data quality, device health and operational capability;
- maintaining canonical representations of the energy ecosystem;
- generating and consuming forecasts;
- supporting configurable and learned device profiles;
- evaluating user controls and active policies;
- producing deterministic and explainable decisions;
- planning stable and coordinated actions;
- orchestrating supported devices through integration adapters;
- verifying whether requested actions were achieved; and
- recording evidence for transparency and diagnostics.

PicoT is not responsible for:

- acting as a certified safety, security or alarm system;
- replacing electrical protection, fire detection or emergency systems;
- guaranteeing uninterrupted external communication;
- guaranteeing execution by third-party devices;
- replacing Home Assistant's general automation capabilities; or
- delegating energy strategy to vendor cloud platforms.

### 2.4 Design goals

The architecture shall support:

- Safety First
- Planning Before Acting
- Deterministic by Design
- Explain Every Decision
- Verify, Don't Assume
- Graceful Degradation
- Platform Independence
- Modularity
- Transparency
- Evidence over Assumption
- Operational Stability
- Extensibility

### 2.5 Architectural principles

#### Single Source of Truth

Every information element shall have one authoritative representation. Derived values shall not become independent sources of truth.

#### Separation of Responsibilities

Observation, decision, planning, execution, verification and explanation are distinct architectural responsibilities.

#### Capability-aware Planning

Planning shall use currently available capability rather than nominal specifications alone.

#### Health-aware Operation

Data, forecast, device and integration health shall influence confidence and available optimisation behaviour.

#### User Authority

Explicit User Control influences planning but never bypasses physical reality, available capability, assessed health or applicable constraints.

#### Stable Control Behaviour

PicoT shall avoid unnecessary mode changes, oscillation, switching wear and plan churn.

#### Learning Improves, Never Governs

Learning may improve models and confidence but never replaces verified measurements, explicit configuration, available capability or active policy.

## 3. Canonical operational lifecycle

PicoT is designed around one deterministic operational lifecycle:

```text
Observe
  ↓
Decide
  ↓
Plan
  ↓
Execute
  ↓
Verify
  ↓
Explain
```

The lifecycle defines the responsibility of every component:

- **Observe** builds the best available representation of current and expected reality.
- **Decide** selects the best achievable strategy.
- **Plan** converts the strategy into a stable and executable plan.
- **Execute** implements only the approved plan.
- **Verify** establishes what actually happened.
- **Explain** exposes evidence, reasons, confidence and outcome.

Every architectural component shall contribute to exactly one lifecycle stage unless an explicit architecture decision defines otherwise.

No component may silently combine lifecycle responsibilities for implementation convenience.

## 4. Processing model

Every optimisation cycle is exactly one HEMS Transaction.

Measured state and `ActiveUserControls` converge in the Decision Context:

```text
Measure ───────────────┐
                       ↓
ActiveUserControls → Decision Context
                       ↓
                     Policy
                       ↓
                    Decision
                       ↓
                    Planning
                       ↓
        Safety Layer evaluation
                       ↓
                   Execution
                       ↓
                  Verification
                       ↓
                    Reporting
```

Each transaction contains:

- `transaction_id`;
- immutable artefacts;
- timestamps;
- source and configuration versions;
- active user controls;
- reason codes;
- confidence and evidence;
- requested actions; and
- verification results.

Manual commands and overrides do not bypass this transaction model.

## 5. Architecture overview

### 5.1 Canonical layer order

1. User Layer
2. User Control Layer
3. Integration Layer
4. Learning Layer
5. Capability & Health Layer
6. Decision Layer
7. Execution Layer
8. Control & Verification Layer
9. Report Layer

Cross-cutting:

- Safety Layer

Only the Safety Layer is cross-cutting.

### 5.2 Architectural characteristics

PicoT intentionally separates:

- presentation from user control;
- integration from business logic;
- learning from decision making;
- capability assessment from optimisation;
- planning from execution;
- execution from verification; and
- reporting from operational logic.

## 6. Component architecture

### 6.1 User Layer

#### Responsibility

The User Layer is responsible exclusively for presenting information to the user.

It provides visibility into the current, historical and planned state of PicoT without influencing behaviour, planning or decision making.

The User Layer is strictly read-only.

#### Responsibilities

- display current system status;
- display planning results;
- display energy flows and forecasts;
- display device status and system health;
- display decision explanations;
- display execution and verification results;
- display historical information and diagnostics;
- display notifications;
- display active user controls; and
- display system confidence.

#### Prohibited responsibilities

The User Layer shall never:

- create or modify configuration;
- create or modify user controls;
- initiate planning;
- execute commands;
- communicate directly with integrations; or
- influence optimisation.

### 6.2 User Control Layer — ADR-013

#### Responsibility

The User Control Layer is responsible for all user interactions that intentionally influence PicoT behaviour.

Every user action is validated and translated into an internal representation. The currently active and applicable controls are exposed through the canonical `ActiveUserControls` interface object.

The User Control Layer is the only architectural path through which user intent may influence operational behaviour.

#### Supported control categories

- `PREFERENCE`
- `CONSTRAINT`
- `TEMPORARY_OVERRIDE`
- `MANUAL_COMMAND`
- `AUTOMATION_LOCK`
- `OVERRIDE_RELEASE`

#### ActiveUserControl attributes

Each control contains, where applicable:

- unique `control_id`;
- source and initiating user;
- creation and activation timestamps;
- optional expiration timestamp or release condition;
- scope and affected entities;
- requested behaviour;
- priority within User Control;
- acceptance state;
- reason and evidence; and
- affected transactions and actions.

#### Rules

- Explicit User Control takes precedence over active policy and automated optimisation.
- User Control cannot override physical reality, available capability, assessed health or applicable constraints.
- User Control never sends device commands directly.
- Manual commands use the normal planning, execution and verification path.
- An active control may never be silently ignored, altered, prolonged or released.
- Rejection, limitation, expiry, execution failure and verification failure shall be reported.
- Controls should be narrowly scoped and have an explicit end condition unless permanence is intentional.

### 6.3 Integration Layer

#### Responsibility

The Integration Layer manages all communication between PicoT and external systems.

It translates external data into canonical models and approved execution requests into platform- or vendor-specific commands.

#### Responsibilities

- data acquisition;
- protocol translation;
- canonical mapping;
- unit and timestamp normalisation;
- communication management;
- retries and timeout handling;
- authentication; and
- transparent failure reporting.

Business, planning and optimisation logic are prohibited inside integration adapters.

All higher layers operate exclusively on canonical models.

### 6.4 Learning Layer — ADR-010

#### Responsibility

The Learning Layer improves PicoT's understanding of the residential energy ecosystem by analysing historical observations, execution results and recurring behaviour.

It never decides, plans or executes.

#### Responsibilities

- learn consumption and production patterns;
- refine configurable device profiles;
- estimate expected runtime, energy use, power curves and completion times;
- compare forecasts with observed reality;
- improve prediction confidence; and
- expose learned values together with model version, evidence and confidence.

Configured device profiles remain available from the first usable version. Learning may refine them later through the same canonical profile structure.

#### Failure behaviour

When learning is unavailable, disabled or insufficiently reliable, the original configured or source model passes through unchanged.

Minimum states:

- `UNAVAILABLE`
- `DISABLED`
- `INITIALIZING`
- `LEARNING`
- `AVAILABLE`
- `DEGRADED`
- `UNRELIABLE`

### 6.5 Capability & Health Layer — ADR-009

#### Responsibility

The Capability & Health Layer determines what PicoT can responsibly achieve in the current operational context and how reliable that conclusion is.

Capability and Health are evaluated independently.

- Capability answers: **What is currently possible?**
- Health answers: **How reliable is the operational picture?**

#### Health domains

- Data Health
- Forecast Health
- Device Health
- Integration Health
- Learning Health
- Overall System Confidence

#### Capability resolution

Nominal specifications are never treated as guaranteed real-time availability.

```text
requested capability ≤ available capability ≤ nominal capability
```

Available capability may depend on:

- measured state;
- temperature;
- SoC;
- firmware limits;
- device self-protection;
- grid conditions;
- active mode;
- communication availability; and
- verified behaviour.

Thermal derating is represented as degraded but potentially available capability, not automatically as device failure.

#### Forecast reliability

The original forecast is immutable. PicoT derives a separate operational interpretation:

```text
Original Forecast
+ Observed Reality
→ Reliability Assessment
→ Operational Forecast Confidence
→ Conservative Operational Estimate
```

Confidence may decay faster than it recovers.

Uniform health states:

- `UNKNOWN`
- `INITIALIZING`
- `HEALTHY`
- `DEGRADED`
- `UNRELIABLE`
- `STALE`
- `UNAVAILABLE`

Every classification shall expose evidence and reasons. No opaque health score is permitted.

### 6.6 Decision Layer

The Decision Layer determines what should happen, when it should happen and why it should happen.

It consists of four components.

#### 6.6.1 Decision Context — ADR-003

Question: **What do we know?**

Output: `DecisionContext`

The Decision Context is immutable for the duration of one planning cycle and includes:

- canonical measurements;
- original and operational forecasts;
- learned models and device profiles;
- capability and health assessments;
- `ActiveUserControls`;
- configuration;
- tariffs; and
- external constraints.

#### 6.6.2 Policy Engine — ADR-005

Question: **What is allowed?**

Output: `DecisionSpace`

The Policy Engine resolves applicable objectives and constraints. It does not choose a strategy.

#### 6.6.3 Decision Engine — ADR-006

Question: **What is the best achievable strategy?**

Output: `DecisionProposal`

The Decision Engine:

- generates candidate strategies;
- rejects infeasible candidates;
- ranks valid alternatives;
- exposes score breakdown, confidence and reasons; and
- selects a strategy within the resolved Decision Space.

It does not plan or execute.

#### 6.6.4 Planner — ADR-007

Question: **How and when should the selected strategy be executed?**

Output: `RequestedAction` or a coordinated set of requested actions.

The Planner determines:

- timing;
- sequencing;
- coordination;
- planning horizon;
- expected outcome;
- expected completion state; and
- plan confidence.

The Planner never communicates directly with devices.

### 6.7 Planning Strategy

#### Planning Horizon

The Planning Horizon defines how far into the future PicoT creates an execution plan. It may vary according to forecast availability, forecast reliability and the devices involved.

#### Replanning Triggers

A new planning cycle may be triggered by material changes in:

- measurements;
- energy prices;
- forecasts;
- device availability;
- capability or health;
- user controls;
- policy; or
- other operational context.

Minor fluctuations should not automatically replace the current plan.

#### Plan Stability

Where multiple plans produce comparable outcomes, the Planner shall prefer the plan requiring the fewest changes to the current execution strategy.

#### Hysteresis

Thresholds may be used to prevent oscillation caused by small forecast changes, measurement noise or marginal economic differences.

#### Minimum Benefit Threshold

A new plan should replace the current plan only when the expected improvement exceeds a configurable minimum benefit.

#### Switching Penalty

The Planner shall account for the operational cost of changing device state.

Switching penalties may represent:

- relay or contactor wear;
- compressor wear;
- communication overhead;
- reduced predictability;
- user disruption; or
- other device-specific operational costs.

Every state transition therefore has an explicit or implicit planning cost.

#### Planning Commitment

Once an execution plan has been committed, PicoT should preserve it whenever reasonably possible.

Committed actions should not be revoked unless a significant event or a change in the operational context justifies replanning.

The Planner shall balance the expected benefit of replanning against the impact of changing an already committed execution plan.

#### Predictability

Stable and predictable execution is preferred over marginal optimisation gains when alternatives are otherwise comparable.

### 6.8 Safety Layer — cross-cutting

The Safety Layer is optional and cross-cutting.

It is not a safety, security or alarm system. Its purpose is to stop PicoT from issuing further control commands when configured conditions occur.

On activation, PicoT may make a best-effort attempt to place supported devices in a configured less-active state. Such attempts depend entirely on integrations, communication and hardware availability and are not guaranteed.

The Safety Layer must never be represented as a replacement for certified protection, fire detection, electrical protection, external safety automation or human intervention.

No User Control can disable or bypass an active Safety Layer restriction.

### 6.9 Execution Layer

#### Responsibility

The Execution Layer translates an approved `RequestedAction` into concrete device commands through the Integration Layer.

Sending a command does not imply success.

#### Execution philosophy

Execution is the controlled implementation of an approved plan.

The Execution Layer shall never optimise, reinterpret or improve a planning decision.

Execution shall be:

- deterministic;
- observable;
- repeatable;
- transparent; and
- verifiable where the integration provides suitable evidence.

Execution failures shall never silently modify the plan.

When execution deviates from the requested action, the deviation shall be recorded and propagated to Control & Verification. Any changed strategy is determined by a later planning cycle, not by hidden execution logic.

### 6.10 Control & Verification Layer

#### Responsibility

The Control & Verification Layer observes the actual result and compares requested state with achieved state.

It records:

- success;
- partial success;
- failure;
- timeout;
- contradiction; or
- other deviation.

Verification closes the operational loop and provides evidence to subsequent transactions.

For explicit User Control, verification also records whether the requested user outcome was achieved, limited or contradicted by later device behaviour.

Verification does not silently correct a failed plan.

### 6.11 Report Layer

#### Responsibility

The Report Layer provides complete transparency and explainability.

It presents:

- current and historical state;
- Decision Records;
- active user controls;
- evidence and confidence;
- applied policies;
- rejected alternatives;
- requested actions;
- execution results;
- verification outcomes; and
- diagnostics.

The Report Layer observes and explains completed and active transactions. It never changes operational state or influences planning directly.

## 7. Authority model

The normative order of authority is:

```text
Physical reality
→ Available device capability and assessed health
→ Safety constraints
→ Explicit User Control
→ Active policy
→ Automated optimisation
```

This order means that the user controls normal automation while PicoT remains honest about what is physically, technically and operationally possible.

## 8. Canonical Domain Models — ADR-008

The Decision Core never consumes vendor models directly.

```text
External systems
↓
Integration adapters
↓
Canonical Domain Models
↓
Learning
↓
Capability & Health
↓
Decision Context
```

Canonical model families include:

- Energy
- Market
- Grid Tariff
- Effective Cost
- Time Interval
- Battery
- Grid
- Forecast
- Device Profile
- Policy
- User Control
- Capability & Health
- Decision Record
- Execution Result
- Verification Result

Market Price and Grid Tariff remain separate. Effective Cost preserves all components. Time intervals are generic and are not restricted to hours.

## 9. Decision Record

Every completed planning cycle shall produce a Decision Record containing sufficient evidence to reconstruct:

- the Decision Context;
- active `ActiveUserControls`;
- applicable policy;
- evaluated alternatives;
- rejected strategies;
- selected strategy;
- planning confidence;
- committed execution plan;
- requested actions;
- execution results; and
- verification outcomes.

## 10. Extensibility — ADR-012

New capabilities shall extend the architecture rather than modify stable operational components.

Optional components shall expose transparent pass-through behaviour when unavailable, disabled or insufficiently reliable.

New User Control types shall extend the canonical control interface rather than introduce direct device-specific bypasses.

## 11. Dashboard and transparency

Every architectural layer shall expose, where applicable:

- online state;
- health state;
- reliability or confidence;
- operating mode;
- last update;
- reasons and evidence.

The User Control Layer additionally exposes:

- active controls and source;
- scope and affected device or function;
- activation and expiry or release condition;
- effect on automated decisions;
- acceptance or limitation state; and
- latest execution and verification outcome.

The User Layer presents this information but never modifies it.

The user should be able to identify where a problem exists before having to inspect why it exists.

The capital **T** is the central visual concept: Transparency forms the backbone of the architecture and dashboard.

## 12. Retention and future learning

PicoT retains operational evidence where it provides value for:

- verification;
- explainability;
- trend assessment;
- reliability assessment;
- device profile refinement; and
- future self-learning.

Historical observations shall not directly influence optimisation unless processed through an approved Capability & Health or Learning component.

User Control history may be retained for traceability and explanation but shall not become learned preference without explicit user consent and an approved design decision.

## 13. Non-goals

PicoT is not:

- a replacement for Home Assistant;
- a collection of unrelated automations;
- a vendor-specific controller;
- a mandatory cloud platform;
- a certified safety or alarm system;
- an opaque autonomous decision-maker; or
- a system that removes final control from the user.
