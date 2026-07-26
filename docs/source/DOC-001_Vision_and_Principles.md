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

## 3. Principle Zero

> No module may assume success. Every important action must be verified before it is considered complete.

## 4. Core principles

### Safety First
Safety-related policy takes precedence over optimization. The PicoT Safety Layer itself is not a safety, security or alarm system and cannot replace certified hardware or external safety integrations.

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
Planning, execution, observation and verification form a continuous control loop.

### Clarity Above Cleverness
Understandable and testable behavior is preferred over opaque sophistication.

### Operational Stability outweighs Marginal Economic Gain
The Planner shall avoid unnecessary switching, oscillation and relay wear even when a small additional economic benefit might be available.

### Design for Evolution
Future capabilities are enabled through stable interfaces and retained evidence, without unnecessarily increasing the complexity of the first usable version.

## 5. Transparency obligations

For every significant decision or health classification, PicoT must be able to answer:

- What do we know?
- What is measured, calculated or estimated?
- How reliable is it?
- What is allowed?
- What strategy was selected?
- Why was it selected?
- Why were alternatives rejected?
- Why is the action executed now?
- Was execution successful?
- What changed after verification?

No opaque scores or unexplained classifications are permitted.

## 6. Evolution rule

New capabilities shall be introduced by extending the architecture rather than modifying stable operational components. Optional components expose the same interface as their pass-through implementation.
