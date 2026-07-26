# ADR-013 — User Control Layer

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Status | Approved & Frozen |
| Date | 2026-07-26 |
| Project | PicoT HEMS |

## Context

PicoT automates energy operation, but automation must remain subordinate to explicit user intent. The existing User Layer provides interaction and presentation, while the Decision Layer performs automated reasoning. Without a dedicated architectural boundary, temporary overrides, manual commands and automation locks risk becoming ad-hoc exceptions or direct device bypasses.

## Decision

PicoT shall include a dedicated **User Control Layer** between the User Layer and Decision Context.

The layer answers:

> What has the user explicitly requested PicoT to do differently?

Its canonical output is `UserControlSet`.

The User Control Layer supports at least:

- preferences;
- constraints;
- temporary overrides;
- immediate manual commands;
- automation locks;
- explicit release of control back to PicoT.

## Authority

The normative authority order is:

```text
Physical reality
→ Verified device capability and health
→ Safety constraints
→ Explicit User Control
→ Active policy
→ Automated optimization
```

An explicit user control therefore takes precedence over normal policy and optimization, but cannot override physical limitations, verified capability or Safety constraints.

## Rules

- User Control never sends commands directly to devices.
- Manual commands use the same Safety, Execution and Verification path as automated actions.
- Every control has an explicit type, target, scope, source and lifecycle.
- Temporary controls have an expiry or release condition.
- Permanent controls are marked explicitly as permanent.
- A control may never be silently ignored, altered, prolonged or released.
- Rejection, limitation, expiry and verification failure are reported with evidence and reason codes.
- Device-scoped control does not disable unrelated PicoT functions.
- Learning may not infer or create persistent preferences from control history without explicit user consent and a separate approved decision.

## Consequences

Positive consequences:

- the user retains final authority over normal automation;
- manual and automated operation remain auditable and verifiable;
- device-specific bypass logic is avoided;
- overrides become visible inputs to Decision Context;
- safety and capability boundaries remain intact.

Trade-offs:

- the domain model must represent control scope and lifecycle;
- conflict resolution between simultaneous controls must be deterministic;
- reporting and dashboards must expose active controls and their effects;
- expired and failed controls require explicit state handling.

## Related documents

- DOC-000 — Architecture Overview
- DOC-001 — Vision & Principles
- DOC-002 — Design Specification
- ADR-003 — Decision Context
- ADR-005 — Policy Engine
- ADR-007 — Planner
- ADR-009 — Capability & Health Layer
