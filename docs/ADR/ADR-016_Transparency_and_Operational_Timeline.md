# ADR-016 — Transparency and Operational Timeline

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Project | PicoT HEMS |
| Status | Approved & Frozen |
| Version | 1.0-RC3 |
| Date | 2026-07-26 |

## Context

PicoT is a planning and orchestration system. Showing only current state or historical measurements is insufficient because the user also needs to understand what PicoT intends to do, why the plan exists and why it changes.

At the same time, transparency must remain usable. Exposing every internal technical detail without structure would reduce clarity rather than improve it.

## Decision

Transparency is a cross-cutting architectural property. It is not confined to the Report Layer.

Every component shall produce sufficient evidence, reasoning and context to make its significant behaviour understandable, verifiable and traceable.

> Transparency is not about exposing everything. Transparency is about exposing the information needed to understand the system's behaviour.

The Reporting Layer shall translate canonical records into understandable information without creating decisions or changing operational state.

## Explanation levels

The user interface may present information at multiple abstraction levels while preserving access to the complete explanation:

1. **Status** — what PicoT is doing.
2. **Reason** — why PicoT is doing it.
3. **Detail** — evidence, confidence, policies, constraints, alternatives and records.

## Operational Timeline

The Reporting Layer shall provide an Operational Timeline covering the current planning horizon.

The timeline shall distinguish between:

- completed and verified actions;
- current operation;
- committed future actions;
- conditional planned actions; and
- cancelled or superseded plans.

Each planned action shall expose, where applicable:

- planned start time;
- expected end time or duration;
- affected devices;
- expected energy flow;
- expected SoC development;
- expected costs or revenue;
- triggering conditions or dependencies;
- confidence; and
- reason for inclusion in the plan.

The timeline shall support generic time intervals and shall not be restricted to hours. Quarter-hour and future interval sizes remain valid.

## Replanning visibility

Whenever replanning changes the timeline, PicoT shall record and expose:

- which action changed;
- what changed;
- why the change occurred;
- which event triggered replanning; and
- the expected operational or economic impact.

## No-surprise principle

> PicoT should never surprise the user. If the system changes its behaviour, it should also explain why.

This principle does not guarantee that external devices behave as planned. It requires PicoT to expose its own intention, detected deviation and resulting plan change.

## Consequences

- The dashboard covers past, present and future.
- Planning intent becomes visible rather than implicit.
- Users can understand why PicoT waits, acts or changes course.
- Technical records remain canonical while presentation can be simplified.
- Transparency requirements influence every component interface.

## Status

Approved and frozen for PicoT HEMS v1.0-RC3.