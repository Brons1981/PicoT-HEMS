# DOC-000 — Architecture Overview

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Project | PicoT HEMS |
| Status | Consistency Review |
| Version | 1.0-RC3 |
| Date | 2026-07-27 |
| Source format | Markdown |

## 1. Purpose

This document provides the high-level architecture of PicoT HEMS.

PicoT stands for **Planning, Intelligence, Coordination, Orchestration & Transparency**. Transparency is an architectural property, not a feature. It spans the complete operational lifecycle and connects every architectural responsibility.

## 2. Runtime position

Home Assistant is the primary and only target platform during design, implementation and stabilisation. PicoT remains architecturally separate from Home Assistant integrations and vendor-specific data models.

## 3. Processing pipeline

Measured state and `ActiveUserControls` are both explicit inputs to the Decision Context.

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

Each optimization cycle is one HEMS Transaction with a unique `transaction_id`, immutable artifacts and end-to-end traceability.

User Control does not bypass the transaction model. Manual commands and overrides remain subject to capability assessment, applicable Safety Layer restrictions, execution and verification.

## 4. Canonical operational lifecycle

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

The lifecycle provides the architectural meaning behind the processing pipeline:

- **Observe** builds the best available representation of current and expected reality.
- **Decide** determines the best achievable strategy within the resolved Decision Space.
- **Plan** converts the selected strategy into a stable, timed and coordinated execution plan.
- **Execute** implements only the approved plan and does not reinterpret it.
- **Verify** determines what actually happened and records deviations.
- **Explain** exposes the evidence, confidence, reasons and outcome.

Every architectural component shall contribute to exactly one lifecycle stage unless an explicit architectural decision defines otherwise. Components shall not silently combine observation, decision, planning, execution, verification or explanation responsibilities.

## 5. Architectural layers

The following order is the canonical architecture order and shall be used consistently in all PicoT documentation, diagrams and implementation descriptions:

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

The User Layer is strictly read-only. All user actions that influence PicoT enter through the User Control Layer.

## 6. Core interfaces

```text
External data
  ↓
Adapters
  ↓
Canonical Domain Models
  ↓
Learning Layer
  ↓
Capability & Health
  ↓
Decision Context ← ActiveUserControls
  ↓
DecisionSpace
  ↓
DecisionProposal
  ↓
Planner
  ↓
RequestedAction
  ↓
Safety Layer evaluation, where configured and applicable
  ↓
Execution
  ↓
Verification
  ↓
Reporting
```

`ActiveUserControls` is the canonical interface object representing the currently active user directives, including overrides, manual commands and temporary constraints. `DecisionContext` consumes `ActiveUserControls` as an explicit input.

The Report Layer implements the **Explain** lifecycle responsibility by exposing the evidence, reasons, confidence and verified outcome produced by the preceding lifecycle stages.

## 7. Authority model

PicoT automates within established boundaries until the user consciously and explicitly chooses otherwise.

The authority order is:

```text
Physical reality
→ Available device capability and assessed health
→ Safety constraints
→ Explicit User Control
→ Active policy
→ Automated optimization
```

User Control therefore takes precedence over normal policy and optimization, but never over physical limitations, available device capability, assessed health or applicable safety constraints.

## 8. Architectural rules

- No module may assume success.
- Every important action must be verified before it is considered complete.
- Stable operational components are extended through stable interfaces rather than modified for each new capability.
- Optional components must support transparent pass-through behavior.
- Vendor, provider and market changes are absorbed outside the Decision Core.
- Every significant result must expose its evidence, confidence and reason codes.
- An active user override may never be silently ignored.
- User controls must have an explicit scope and, where applicable, an end condition.
- Manual commands must use the same execution and verification path as automated actions.
- The Planner shall prefer stable committed plans over marginal improvements.
- The Execution Layer shall never optimize, reinterpret or silently replace an approved plan.
- Execution deviations become evidence for verification and a subsequent planning cycle.

## 9. Safety Layer boundary

The Safety Layer is optional and is not a safety, security or alarm system. Its purpose is to stop PicoT from issuing further control commands when configured conditions occur.

On activation, PicoT may make a best-effort attempt to place supported devices in a configured less-active state, but only when integrations, communication and hardware remain available. PicoT does not guarantee that such commands will be delivered or executed.

User Control cannot disable or bypass an active Safety Layer restriction.

## 10. Dashboard transparency

Every architectural layer shall expose at least:

- online state;
- health state;
- reliability or confidence;
- operating mode;
- evidence and reasons.

The User Control Layer additionally exposes active overrides, scope, source, start time, expiry or release condition, affected decisions and verification state.

The dashboard shall show the complete architecture at a glance, with the capital **T** as the visual backbone representing Transparency.