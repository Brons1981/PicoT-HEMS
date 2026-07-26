# ADR-014 — Canonical Operational Lifecycle

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Project | PicoT HEMS |
| Status | Approved & Frozen |
| Version | 1.0-RC3 |
| Date | 2026-07-26 |

## Context

PicoT requires strict responsibility boundaries so that observation, decision making, planning, execution, verification and explanation do not become mixed inside implementation components.

Without a canonical lifecycle, components can silently acquire multiple responsibilities, making behaviour less deterministic, less testable and harder to explain.

## Decision

PicoT shall use the following canonical operational lifecycle:

```text
Observe
  ↓
Decide
  ↓
Plan
  ↓
Execute
  ↓
Verify
  ↓
Explain
```

The stages have the following responsibilities:

- **Observe** builds an accurate and qualified representation of current and expected reality.
- **Decide** selects the best achievable strategy within applicable boundaries.
- **Plan** converts the strategy into a stable and executable plan.
- **Execute** implements only the approved plan.
- **Verify** establishes what actually happened.
- **Explain** exposes evidence, reasons, confidence and outcome.

Every architectural component shall contribute to exactly one lifecycle stage unless another approved ADR explicitly defines an exception.

A component shall not combine lifecycle stages merely for implementation convenience.

## Consequences

- Observation cannot silently become decision logic.
- Planning remains separate from execution.
- Execution cannot optimise, reinterpret or improve an approved plan.
- Verification cannot determine the next action or silently repair a failed plan.
- Reporting cannot alter operational state.
- Component interfaces become easier to test and audit.
- All implementation work can be mapped to one lifecycle responsibility.

## Verification principle

> Execution performs actions. Verification determines facts. Planning decides what happens next.

## Status

Approved and frozen for PicoT HEMS v1.0-RC3.