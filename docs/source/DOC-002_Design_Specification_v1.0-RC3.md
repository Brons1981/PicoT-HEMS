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
- User Authority.
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

Measured state and active user controls converge in Decision Context:

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

Each transaction contains:

- `transaction_id`;
- immutable artifacts;
- timestamps;
- source and configuration versions;
- active user controls;
- reason codes;
- confidence and evidence;
- verification result.

Manual commands and overrides do not bypass this transaction model.

## 4. Architecture layers

### 4.1 User Layer

Provides the human-facing interaction surface. It captures user intent and configuration and presents information, but does not itself decide, plan or execute energy actions.

### 4.2 User Control Layer — ADR-013

Question: **What has the user explicitly requested PicoT to do differently?**

Output: `UserControlSet`

The User Control Layer translates explicit user intent into validated, traceable controls for the Decision Context and, for immediate commands, the normal execution path.

Supported control categories:

- `PREFERENCE`: influences future decisions without requiring a specific result;
- `CONSTRAINT`: limits allowed behavior, such as do not discharge;
- `TEMPORARY_OVERRIDE`: temporarily replaces normal automated behavior;
- `MANUAL_COMMAND`: requests an immediate concrete action;
- `AUTOMATION_LOCK`: excludes a device or function from automatic control;
- `OVERRIDE_RELEASE`: returns control to normal PicoT automation.

Every control contains, where applicable:

- unique `control_id`;
- control type;
- target and scope;
- requested value or mode;
- source and creation time;
- activation time;
- expiry, release condition or permanence;
- priority within User Control;
- acceptance state;
- reason and evidence;
- affected transactions and actions.

Rules:

- Explicit User Control takes precedence over active policy and automated optimization.
- User Control cannot override physical limitations, verified capability or Safety constraints.
- User Control never sends device commands directly.
- Manual commands use Safety, Execution and Verification.
- An active control may never be silently ignored, altered, prolonged or released.
- Rejection, limitation, expiry, execution failure and verification failure must be reported.
- A control should be narrowly scoped and have an explicit end condition unless permanence is intentional.
- Device-scoped control does not automatically disable PicoT for unrelated devices or functions.

### 4.3 Report Layer

Presents current state, decisions, user controls, evidence, confidence, execution and verification results. Reporting observes completed transactions and active control state and does not alter them.

### 4.4 Decision Layer

The Decision Layer is Approved & Frozen and consists of four components.

#### Decision Context — ADR-003

Question: **What do we know?**

Output: `DecisionContext`

Decision Context includes the current `UserControlSet` as an explicit input alongside measured state, forecasts, capability, health and configuration.

#### Policy Engine — ADR-005

Question: **What is allowed?**

Output: `DecisionSpace`

Policy priority:

1. Safety and physical constraints
2. Verified device capability and health
3. Explicit User Control
4. Operational policy
5. Contract policy
6. System policy
7. User preferences that are not explicit overrides

The Policy Engine never chooses a strategy. It resolves active user constraints and overrides into the permitted Decision Space and records any rejected or limited control with reasons.

#### Decision Engine — ADR-006

Question: **What is the best strategy?**

Output: `DecisionProposal`

Responsibilities include candidate generation, ranking, score breakdown, confidence, alternatives and reason codes. It never plans or executes. It optimizes only within the Decision Space already constrained by User Control.

#### Planner — ADR-007

Question: **Is this the right moment to execute the strategy?**

Output: `RequestedAction`

Responsibilities include hysteresis, minimum runtime, oscillation prevention, relay protection, switching budgets and operational stability. The Planner does not optimize.

A User Control can prevent, replace or defer a planned action, but cannot bypass Planner protections where these are required for safe and stable operation. Any such limitation is reported transparently.

The interfaces are immutable:

```text
DecisionContext
→ DecisionSpace
→ DecisionProposal
→ RequestedAction
```

### 4.5 Capability & Health Layer — ADR-009

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

A user request outside available capability is limited or rejected; it is never presented as successfully accepted without evidence.

#### Trends and history

Capability & Health may use short-term trends to anticipate degradation. Relevant operational history is retained for reliability assessment, explainability and future learning.

### 4.6 Learning Layer — ADR-010

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
- never changes explicit User Control;
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

### 4.7 Integration Layer

Adapters translate external vendor, provider and Home Assistant models into canonical domain models. Integrations contain no energy strategy and cannot reinterpret explicit user intent.

### 4.8 Execution Layer

Translates an approved `RequestedAction`, including an approved manual command, into concrete commands. Sending a command does not imply success.

### 4.9 Control & Verification Layer

Observes the actual result, compares requested and achieved state and records success, partial success, failure or deviation. Verification closes the control loop and provides evidence to later transactions.

For User Control, verification also records whether the requested user outcome was achieved, limited or contradicted by subsequent device behavior.

### 4.10 Safety Layer

The Safety Layer is optional and cross-cutting.

It is not a safety, security or alarm system. Its sole purpose is to stop PicoT from issuing further control commands when configured conditions occur.

On activation, PicoT may make a best-effort attempt to place supported devices, such as an inverter or battery, in a less active state. Such attempts depend entirely on integrations, communication and hardware availability and are not guaranteed.

The Safety Layer must never be documented as a replacement for certified protection, fire detection, electrical protection or external safety automation.

No User Control can disable, bypass or downgrade an active Safety constraint.

## 5. Authority model

The normative order of authority is:

```text
Physical reality
→ Verified device capability and health
→ Safety constraints
→ Explicit User Control
→ Active policy
→ Automated optimization
```

This order means that the user controls normal automation, while PicoT remains honest about what is physically, technically and operationally possible.

## 6. Canonical Domain Models — ADR-008

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
- User Control
- Capability & Health

Market Price and Grid Tariff remain separate. Effective Cost preserves all components. Time intervals are generic and are not restricted to hours.

## 7. Extensibility — ADR-012

New capabilities shall extend the architecture rather than modify stable operational components. Optional components must expose transparent pass-through behavior when unavailable, disabled or insufficiently reliable.

New User Control types must extend the canonical control interface rather than introduce direct device-specific bypasses.

## 8. Dashboard and transparency

Every architectural layer shall expose:

- online state;
- health state;
- reliability/confidence;
- operating mode;
- last update;
- reasons and evidence.

The User Control Layer additionally exposes:

- active controls and their source;
- scope and affected device or function;
- activation and expiry or release condition;
- effect on automated decisions;
- acceptance or limitation state;
- latest execution and verification outcome.

The user must be able to identify where a problem exists before having to inspect why it exists.

The capital **T** is the central visual concept: Transparency forms the backbone of the architecture and dashboard.

## 9. Retention and future learning

PicoT retains operational evidence wherever it provides value for:

- verification;
- explainability;
- trend assessment;
- reliability assessment;
- future self-learning.

Historical observations must not directly influence optimization unless processed through an approved Capability & Health or Learning component.

User Control history may be retained for traceability and explanation, but must not be converted into learned preferences without explicit user consent and an approved design decision.

## 10. Non-goals

PicoT is not:

- a replacement for Home Assistant;
- a collection of unrelated automations;
- a vendor-specific controller;
- a mandatory cloud platform;
- a certified safety or alarm system;
- an opaque autonomous decision-maker;
- a system that removes final control from the user.
