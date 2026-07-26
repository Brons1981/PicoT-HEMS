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

```text
Measure
  ↓
Decision Context
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

## 4. Architectural layers

1. User Layer
2. Report Layer
3. Decision Layer
4. Capability & Health Layer
5. Learning Layer
6. Integration Layer
7. Execution Layer
8. Control & Verification Layer

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
Decision Context
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

## 6. Architectural rules

- No module may assume success.
- Every important action must be verified before it is considered complete.
- Stable operational components are extended through stable interfaces rather than modified for each new capability.
- Optional components must support transparent pass-through behavior.
- Vendor, provider and market changes are absorbed outside the Decision Core.
- Every significant result must expose its evidence, confidence and reason codes.

## 7. Safety Layer boundary

The Safety Layer is optional and is not a safety, security or alarm system. Its purpose is to stop PicoT from issuing further control commands when configured conditions occur.

On activation, PicoT may make a best-effort attempt to place supported devices in a less active state, but only when integrations, communication and hardware remain available. PicoT does not guarantee that such commands will be delivered or executed.

## 8. Dashboard transparency

Every architectural layer shall expose at least:

- online state;
- health state;
- reliability or confidence;
- operating mode;
- evidence and reasons.

The dashboard shall show the complete architecture at a glance, with the capital **T** as the visual backbone representing Transparency.
