# CFD-004 — PEP Lifecycle and Implementation Traceability

## Status

Accepted

## Context

PicoT needs a durable way to record enhancement ideas without allowing them to disappear into chat history or remain disconnected from implementation.

A PEP must describe not only an idea, but also when it becomes relevant and where it must be considered in the codebase.

## Decision

PicoT Enhancement Proposals use a mandatory structure and lifecycle.

## Required PEP fields

Every PEP must include:

- identifier and title;
- status;
- summary;
- motivation;
- scope and non-scope;
- target phase;
- implementation trigger;
- relevant packages;
- relevant components;
- implementation touchpoints;
- dependencies;
- risks of postponement;
- roadmap relationship;
- acceptance criteria;
- open questions.

## Lifecycle

```text
Draft
  ↓
Proposed
  ↓
Accepted
  ↓
Planned
  ↓
In Development
  ↓
Implemented
  ↓
Released
```

A PEP may also become `Rejected` at any stage before implementation when the reason is documented.

## Implementation traceability

An accepted PEP must state:

1. **When** it becomes relevant.
2. **Which package boundaries** it touches.
3. **Which components** must consider it.
4. **What trigger** moves it from accepted idea to planned work.
5. **Which roadmap phase** owns it.

This information prevents future implementation from overlooking accepted ideas.

## Classification

PEPs may be grouped by domain, including:

- 100 — User Experience;
- 200 — Forecast;
- 300 — Diagnostics;
- 400 — Device Ecosystem;
- 500 — Learning;
- 600 — Developer Experience.

## Consequences

- Ideas are preserved in GitHub rather than chat history.
- Roadmap decisions remain linked to implementation touchpoints.
- New work can be checked against accepted PEPs before package changes are made.
- PEPs remain separate from architecture decisions and Core Framework decisions.
