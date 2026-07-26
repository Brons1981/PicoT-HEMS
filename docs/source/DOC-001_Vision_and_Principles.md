# DOC-001 — Vision & Principles

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Project | PicoT HEMS |
| Status | Release Candidate |
| Version | 1.0-RC3 |
| Date | 2026-07-26 |

## 1. Identity

PicoT means:

- **P**lanning
- **I**ntelligence
- **C**oordination
- **O**rchestration
- **T**ransparency

The capital **T** is intentional. Transparency is not an isolated feature; it is the principle connecting every other part of PicoT.

## 2. Mission

PicoT continuously determines and coordinates the best responsible operating strategy for a residential energy ecosystem, using measurable evidence, explicit policy, verified execution and transparent reporting.

PicoT automates within established boundaries until the user consciously and explicitly chooses otherwise.

## 3. Principle Zero

> No module may assume success. Every important action must be verified before it is considered complete.

## 4. Core principles

### Safety First
Safety-related policy takes precedence over optimization. The PicoT Safety Layer itself is not a safety, security or alarm system and cannot replace certified hardware or external safety integrations.

### User Authority
The user retains ultimate authority over normal automated operation. An explicit user control takes precedence over active policy and automated optimization, but cannot override physical reality, verified device capability or safety constraints.

PicoT must never silently ignore, alter or prolong a user control. A rejected, limited, failed or expired control must be reported with evidence and reasons.

### Verify, Don't Assume
Commands are requests until execution is verified through observable state or other approved evidence.

### Evidence over Assumption
PicoT bases every significant decision on measured, verified or explicitly qualified information. When certainty is unavailable, PicoT exposes confidence rather than presenting assumptions as facts.

Information priority:

1. Measured
2. Verified
3. Calculated
4. Estimated with confidence
5. Unknown

### Explain Every Decision
A user should never have to infer the reason behind a significant decision. PicoT proactively exposes the active strategy, decisive evidence, constraints, rejected alternatives and expected result.

### Deterministic by Design
Equivalent inputs, policy and state should produce the same result.

### Modularity over Complexity
Each module answers one architectural question and produces one explicit output.

### Graceful Degradation
Missing or unreliable inputs reduce capability, not predictability. PicoT falls back deliberately and visibly.

### Platform Independence
The core uses canonical models rather than Home Assistant or vendor-specific models.

### Closed-loop Control
Planning, execution, observation and verification form a continuous control loop. Manual commands use the same closed-loop path as automated actions.

### Clarity Above Cleverness
Understandable and testable behavior is preferred over opaque sophistication.

### Operational Stability outweighs Marginal Economic Gain
The Planner shall avoid unnecessary switching, oscillation and relay wear even when a small additional economic benefit might be available.

### Design for Evolution
Future capabilities are enabled through stable interfaces and retained evidence, without unnecessarily increasing the complexity of the first usable version.

## 5. User Control obligations

Every user control must be explicit about:

- intent and control type;
- scope, such as device, function, operating mode or time period;
- source and creation time;
- expiry, release condition or permanence;
- decisions and actions affected;
- acceptance, limitation or rejection reason;
- execution and verification result where applicable.

Supported control categories may include preferences, constraints, temporary overrides, immediate manual commands, automation locks and explicit release of control back to PicoT.

## 6. Transparency obligations

For every significant decision, health classification or user control, PicoT must be able to answer:

- What do we know?
- What is measured, calculated or estimated?
- How reliable is it?
- What is allowed?
- Is an explicit user control active?
- What strategy was selected?
- Why was it selected?
- Why were alternatives rejected?
- Why is the action executed now?
- Was execution successful?
- What changed after verification?

No opaque scores, unexplained classifications or hidden overrides are permitted.

## 7. Evolution rule

New capabilities shall be introduced by extending the architecture rather than modifying stable operational components. Optional components expose the same interface as their pass-through implementation.
