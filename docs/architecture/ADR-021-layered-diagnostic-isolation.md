# ADR-021 — Layered Diagnostic Isolation

## Status

Accepted

## Context

PicoT contains multiple configurable layers, including User Rules, Expert configuration, Planning Hints, Managed Energy Profiles, external actions and Planner optimisation.

When behaviour is unexpected, users must be able to isolate the responsible layer without deleting or rewriting configuration and without disabling essential baseline functionality.

## Decision

PicoT provides a Layered Diagnostic Isolation Mode.

Diagnosis is performed by temporarily bypassing one layer at a time and applying a known fallback for that layer.

The original configuration remains unchanged throughout the diagnostic session.

## Non-destructive diagnosis

Diagnosis must never:

- delete configuration;
- overwrite Expert values;
- rewrite User Rules;
- discard learned data;
- modify Planning Hints;
- permanently disable integrations.

After diagnosis ends, the original configuration becomes active again.

## Diagnostic layers

Initial diagnostic isolation targets include:

1. all User Rules;
2. Expert User Rules;
3. Expert configuration;
4. Planning Hints;
5. Managed or learned Energy Profiles;
6. external Home Assistant and Homey actions;
7. advanced Planner optimisation.

Additional layers may be added only when they have a defined temporary fallback.

## Temporary fallbacks

Examples:

```text
User Rules bypassed
→ normal PicoT Planner remains active
```

```text
Expert configuration bypassed
→ standard configuration is used as a temporary fallback
```

```text
Planning Hints bypassed
→ energy impact is treated as UNKNOWN unless another accepted profile exists
```

```text
Learned Energy Profile bypassed
→ USER_DECLARED profile is used when available, otherwise UNKNOWN
```

```text
External actions blocked
→ HA/Homey triggers are not sent; the remaining plan continues within validated constraints
```

```text
Advanced Planner optimisation bypassed
→ documented basic Planner fallback is used
```

No diagnostic step may remove essential source data required for baseline PicoT operation.

## Guided isolation flow

PicoT guides the user step by step:

```text
Temporarily bypass layer A
→ does the problem persist?
→ yes: restore A and test B, or continue according to the selected isolation workflow
→ no: identify A as the likely problem layer
```

The exact workflow must be visible and reproducible.

## Records

Each step produces an immutable diagnostic isolation record containing:

- diagnostic session ID;
- layer;
- temporary action;
- fallback used;
- start and end time;
- user response or observed outcome;
- affected Planner decisions and Execution Plans.

## Explainability

Every PlannerDecisionRecord produced during diagnosis must state:

- that Diagnostic Mode was active;
- which layers were bypassed;
- which temporary fallbacks were used;
- whether the behaviour changed.

## Core principles

> Diagnostic Mode isolates layers through temporary fallbacks. It never replaces or destroys the user’s original configuration.

> PicoT must remain as operational as possible during diagnosis. Essential baseline inputs and functions are not removed merely because an Expert layer is being isolated.
