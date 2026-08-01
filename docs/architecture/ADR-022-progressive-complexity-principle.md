# ADR-022 — Progressive Complexity Principle

## Status

Accepted

## Context

PicoT must remain understandable for ordinary users while still allowing advanced users to express precise intent.

Uncontrolled feature growth risks creating duplicate subsystems, inconsistent behaviour and an unmanageable Core.

## Decision

PicoT adopts a Progressive Complexity Model.

The default user experience is simple. Additional complexity becomes visible only when the user explicitly opts in.

Complexity is optional for the user, never for the architecture.

## Design rules

New functionality should, where possible:

- extend existing Core models;
- use the same Planner;
- use the same Explainability and Diagnostics;
- use the same Execution Pipeline;
- avoid parallel engines or duplicated state;
- add a new fundamental concept only when it has its own responsibility, data and lifecycle.

## User progression

```text
Basis
→ Simple
→ Expert
→ optional Learning
→ optional automatic optimisation
```

Each layer builds on the same internal architecture.

## Expert configuration

Expert configuration must always be explicit and visibly enabled by the user.

Disabling or bypassing Expert configuration for diagnosis must not disable required baseline functionality. The applicable standard configuration is used as a temporary fallback.

## Diagnostic isolation

Every optional complexity layer must define how it can be temporarily isolated without destroying or rewriting user configuration.

## Architecture review rule

Before accepting a new ADR or feature, PicoT asks:

1. Is this a new fundamental concept or an extension of an existing one?
2. Does it have a distinct responsibility, data model and lifecycle?
3. Can it use existing validation, records, Explainability, Diagnostics and Execution paths?
4. Is the implementation value worth the added complexity?

## Core principles

> New functionality should preferably extend existing building blocks instead of introducing a parallel subsystem.

> Expert users may express more precise intent, but all users remain within the same validated PicoT architecture.
