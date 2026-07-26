# DOC-002 — Design Specification

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Project | PicoT HEMS |
| Status | Release Candidate |
| Version | 1.0-RC3 |
| Date | 2026-07-26 |
| Source format | Markdown |

## 1. Purpose

This document defines the functional and architectural design of PicoT HEMS.

PicoT is a modular, explainable and verification-driven Home Energy Management System. Home Assistant is the runtime and user-interface platform, while PicoT contains the energy policy, planning, orchestration and verification logic.

## 2. Architecture principles

PicoT follows DOC-001. The normative principles include:

- Principle Zero: no module may assume success.
- Safety First.
- Verify, Don't Assume.
- Evidence over Assumption.
- Explain Every Decision.
- Deterministic by Design.
- Modularity over Complexity.
- Graceful Degradation.
- Platform Independence.
- Closed-loop Control.
- Clarity Above Cleverness.
- Operational Stability outweighs Marginal Economic Gain.
- Design for Evolution.

## 3. Processing model

Every optimization cycle is exactly one HEMS Transaction.

```text
Measure
→ Decision Context
→ Policy
→ Decision
→ Planning
→ Safety
→ Execution
→ Verification
→ Reporting
```

Each transaction contains:

- `transaction_id`;
- immutable artifacts;
- timestamps;
- source and configuration versions;
- reason codes;
- confidence and evidence;
- verification result.

## 4. Architecture layers

### 4.1 User Layer

Captures user intent and configuration. It never makes energy decisions.

### 4.2 Report Layer

Presents current state, decisions, evidence, confidence, execution and verification results. Reporting observes completed transactions and does not alter them.

### 4.3 Decision Layer

The Decision Layer is Approved & Frozen and consists of four components.

#### Decision Context — ADR-003

Question: **What do we know?**

Output: `DecisionContext`

#### Policy Engine — ADR-005

Question: **What is allowed?**

Output: `DecisionSpace`

Policy priority:

1. Safety
2. Device
3. Operational
4. Contract
5. System
6. User

The Policy Engine never chooses a strategy.

#### Decision Engine — ADR-006

Question: **What is the best strategy?**

Output: `DecisionProposal`

Responsibilities include candidate generation, ranking, score breakdown, confidence, alternatives and reason codes. It never plans or executes.

#### Planner — ADR-007

Question: **Is this the right moment to execute the strategy?**

Output: `RequestedAction`

Responsibilities include hysteresis, minimum runtime, oscillation prevention, relay protection, switching budgets and operational stability. The Planner does not optimize.

The interfaces are immutable:

```text
DecisionContext
→ DecisionSpace
→ DecisionProposal
→ RequestedAction
```

### 4.4 Capability & Health Layer — ADR-009

Question: **Can PicoT responsibly optimize in the current situation?**

Output: `CapabilityReport`

Responsibilities:

- Data Health;
- Forecast Health;
- Device Health;
- Integration Health;
- Capability Resolution;
- Overall System Confidence.

A common assessment framework evaluates, where applicable:

```text
Freshness
→ Completeness
→ Consistency
→ Plausibility
→ Source Reliability
→ Observed Performance
→ Health
→ Capability
```

Health describes trustworthiness or technical condition. Capability describes what can still be used responsibly.

Uniform health states:

- `UNKNOWN`
- `INITIALIZING`
- `HEALTHY`
- `DEGRADED`
- `UNRELIABLE`
- `STALE`
- `UNAVAILABLE`

All classifications expose evidence and reasons. No health score may be a black box.

#### Forecast reliability

The original forecast is immutable. PicoT derives a separate reliability assessment and operational estimate.

```text
Original Forecast
+ Observed Reality
→ Reliability Assessment
→ Operational Forecast Confidence
→ Conservative Operational Estimate
```

Loss of confidence may occur faster than recovery. Degraded confidence can lead to more conservative planning, such as retaining additional battery reserve.

#### Dynamic device capability

Nominal specifications are never treated as guaranteed real-time availability. Available capability depends on observed state and conditions, including temperature, SoC, firmware limits, device self-protection, grid conditions, mode, communication and verified behavior.

```text
requested capability ≤ available capability ≤ nominal capability
```

Thermal derating is represented as degraded but potentially still available capability, not automatically as device failure.

Capability limitation evidence may be:

- confirmed by the device or integration;
- inferred from temperature and observed behavior;
- unknown in magnitude, requiring conservative planning.

#### Trends and history

Capability & Health may use short-term trends to anticipate degradation. Relevant operational history is retained for reliability assessment, explainability and future learning.

### 4.5 Learning Layer — ADR-010

The Learning Layer is an optional, non-authoritative model-enhancement layer.

```text
Learning available and sufficiently reliable?

YES → Produce enhanced model
NO  → Pass original model through unchanged
```

The rest of PicoT always consumes the same interface. The Learning Layer:

- never makes decisions;
- never controls devices;
- never overwrites original source data;
- exposes correction, model version, confidence and evidence;
- is subject to Capability & Health assessment.

Minimum states:

- `UNAVAILABLE`
- `DISABLED`
- `INITIALIZING`
- `LEARNING`
- `AVAILABLE`
- `DEGRADED`
- `UNRELIABLE`

V1 may implement the layer as a transparent no-op/pass-through component.

### 4.6 Integration Layer

Adapters translate external vendor, provider and Home Assistant models into canonical domain models. Integrations contain no energy strategy.

### 4.7 Execution Layer

Translates an approved `RequestedAction` into concrete commands. Sending a command does not imply success.

### 4.8 Control & Verification Layer

Observes the actual result, compares requested and achieved state and records success, partial success, failure or deviation. Verification closes the control loop and provides evidence to later transactions.

### 4.9 Safety Layer

The Safety Layer is optional and cross-cutting.

It is not a safety, security or alarm system. Its sole purpose is to stop PicoT from issuing further control commands when configured conditions occur.

On activation, PicoT may make a best-effort attempt to place supported devices, such as an inverter or battery, in a less active state. Such attempts depend entirely on integrations, communication and hardware availability and are not guaranteed.

The Safety Layer must never be documented as a replacement for certified protection, fire detection, electrical protection or external safety automation.

## 5. Canonical Domain Models — ADR-008

The Decision Core never consumes vendor models directly.

```text
External
↓
Adapters
↓
Canonical Domain Models
↓
Decision Context
```

Canonical model families:

- Energy
- Market
- Grid Tariff
- Effective Cost
- Time Interval
- Battery
- Grid
- Forecast
- Policy
- Capability & Health

Market Price and Grid Tariff remain separate. Effective Cost preserves all components. Time intervals are generic and are not restricted to hours.

## 6. Extensibility — ADR-012

New capabilities shall extend the architecture rather than modify stable operational components. Optional components must expose transparent pass-through behavior when unavailable, disabled or insufficiently reliable.

## 7. Dashboard and transparency

Every architectural layer shall expose:

- online state;
- health state;
- reliability/confidence;
- operating mode;
- last update;
- reasons and evidence.

The user must be able to identify where a problem exists before having to inspect why it exists.

The capital **T** is the central visual concept: Transparency forms the backbone of the architecture and dashboard.

## 8. Retention and future learning

PicoT retains operational evidence wherever it provides value for:

- verification;
- explainability;
- trend assessment;
- reliability assessment;
- future self-learning.

Historical observations must not directly influence optimization unless processed through an approved Capability & Health or Learning component.

## 9. Non-goals

PicoT is not:

- a replacement for Home Assistant;
- a collection of unrelated automations;
- a vendor-specific controller;
- a mandatory cloud platform;
- a certified safety or alarm system;
- an opaque autonomous decision-maker.
