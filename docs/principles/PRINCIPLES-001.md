# PRINCIPLES-001 — PicoT HEMS Design Principles

## Status

Accepted

## Foundational model

PicoT follows this chain:

```text
Transparency
        ↓
Explainability
        ↓
Evidence
        ↓
Deterministic Behaviour
        ↓
Diagnostics
        ↓
Trust
```

Trust is not assumed or claimed. It is earned through transparent, explainable and verifiable behaviour.

## Principles

### 1. Transparency

The system must expose what it knows, what it decided, what it attempted and what happened.

### 2. Explainability

Every meaningful decision must be explainable from stored facts, rules, constraints and decision records.

### 3. Evidence based

PicoT must not invent reasons or infer unsupported facts. Explanations must be traceable to available evidence.

### 4. Deterministic behaviour

Given the same validated inputs, rules and configuration, PicoT must produce the same result.

### 5. Capability driven

Planner behaviour depends on capabilities, not on brands or product-specific implementations.

### 6. Vendor independence

Vendor details remain in Device Packs and adapters. The Core must not become vendor-specific.

### 7. Core first

Contracts, records, boundaries, diagnostics and tests are established before optimization features are added.

### 8. Diagnostics first

Diagnostics are part of the Core, not an afterthought. Failures must produce exportable evidence around the affected layers and records.

### 9. Single responsibility

Each component has one clear responsibility. Business logic does not leak into adapters or infrastructure components such as the Event Bus.

### 10. Stable contracts

Interfaces and records are explicit and stable. Changes to the Shared Kernel require a formal Core Framework Decision.

### 11. Testability

Every component and contract must be independently testable. A change is not complete without appropriate tests.

### 12. Safety before optimization

The system must preserve configured operational constraints before pursuing financial or efficiency optimization.

### 13. Human control

Users retain control over preferences, limits, optional layers and supported operating modes.

### 14. Evolution without disruption

New Device Packs, capabilities and features must be added without destabilizing the Core or requiring vendor-specific planner changes.

### 15. Long-term maintainability

Design choices are evaluated for clarity, ownership, dependency direction and sustainability over multiple years.

## Design test

Every ADR, CFD and PEP must be checked against this question:

> Does this increase or preserve the transparency of PicoT?

A decision that reduces transparency requires explicit justification and reconsideration.
