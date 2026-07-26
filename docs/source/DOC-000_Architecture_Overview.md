# DOC-000 — Architecture Overview

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Project | PicoT HEMS |
| Status | Release Candidate |
| Version | 1.0-RC3 |
| Date | 2026-07-26 |
| Source format | Markdown |

## 1. Purpose

This document provides the high-level architecture of PicoT HEMS.

PicoT stands for **Planning, Intelligence, Coordination, Orchestration & Transparency**. Transparency is the unifying principle across the complete architecture.

## 2. Runtime position

Home Assistant is the primary and only target platform during design, implementation and stabilisation. PicoT remains architecturally separate from Home Assistant integrations and vendor-specific data models.

## 3. Processing pipeline

Measured state and active user controls are both explicit inputs to the Decision Context.

```text
Measure ───────────────┐
                       ↓
Active User Controls → Decision Context
                       ↓
                     Policy
                       ↓
                    Decision
                       ↓
                    Planning
                       ↓
                     Safety
                       ↓
                   Execution
                       ↓
                  Verification
                       ↓
                    Reporting
```

Each optimization cycle is one HEMS Transaction with a unique `transaction_id`, immutable artifacts and end-to-end traceability.

User Control does not bypass the transaction model. Manual commands and overrides remain subject to capability assessment, safety validation, execution and verification.

## 4. Architectural layers

1. User Layer
2. User Control Layer
3. Report Layer
4. Decision Layer
5. Capability & Health Layer
6. Learning Layer
7. Integration Layer
8. Execution Layer
9. Control & Verification Layer

Cross-cutting:

- Safety Layer

Only the Safety Layer is cross-cutting.

## 5. Core interfaces

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
Decision Context ← Active User Controls
  ↓
DecisionSpace
  ↓
DecisionProposal
  ↓
RequestedAction
  ↓
Safety validation
  ↓
Execution and verification
```

## 6. Authority model

PicoT automates within established boundaries until the user consciously and explicitly chooses otherwise.

The authority order is:

```text
Physical reality
→ Verified device capability and health
→ Safety constraints
→ Explicit User Control
→ Active policy
→ Automated optimization
```

User Control therefore takes precedence over normal policy and optimization, but never over physical limitations, verified capability or safety constraints.

## 7. Architectural rules

- No module may assume success.
- Every important action must be verified before it is considered complete.
- Stable operational components are extended through stable interfaces rather than modified for each new capability.
- Optional components must support transparent pass-through behavior.
- Vendor, provider and market changes are absorbed outside the Decision Core.
- Every significant result must expose its evidence, confidence and reason codes.
- An active user override may never be silently ignored.
- User controls must have an explicit scope and, where applicable, an end condition.
- Manual commands must use the same execution and verification path as automated actions.

## 8. Safety Layer boundary

The Safety Layer is optional and is not a safety, security or alarm system. Its purpose is to stop PicoT from issuing further control commands when configured conditions occur.

On activation, PicoT may make a best-effort attempt to place supported devices in a less active state, but only when integrations, communication and hardware remain available. PicoT does not guarantee that such commands will be delivered or executed.

User Control cannot disable or bypass the Safety Layer.

## 9. Dashboard transparency

Every architectural layer shall expose at least:

- online state;
- health state;
- reliability or confidence;
- operating mode;
- evidence and reasons.

The User Control Layer additionally exposes active overrides, scope, source, start time, expiry or release condition, affected decisions and verification state.

The dashboard shall show the complete architecture at a glance, with the capital **T** as the visual backbone representing Transparency.
