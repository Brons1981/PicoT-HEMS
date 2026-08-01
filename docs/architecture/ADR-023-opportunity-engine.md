# ADR-023 — Opportunity Engine

## Status
Accepted

## Context
PicoT needs a deterministic stage that turns a validated Planning Input Set into objective, time-bound opportunities and constraints before any device allocation or scenario selection occurs.

## Decision
The Opportunity Engine detects objective planning opportunities and constraints. It does not choose a device, assign power, create Candidates, score outcomes or produce an Execution Plan.

A Planning Opportunity is an objective, evidence-backed statement that something may be relevant or possible within a defined time window, such as:

- cheap import window;
- negative price window;
- high export value window;
- expected PV surplus window;
- flexible load window;
- recovery window;
- expected load window;
- available charge or discharge window.

A Constraint is recorded separately from an Opportunity. Constraints describe technical, temporal, user-defined or capability-based limits.

The Opportunity Engine may combine multiple Planning Inputs into objective derived facts, for example:

- PV forecast + load forecast → expected PV surplus;
- price forecast + time horizon → cheap import window.

It may not interpret such a fact into a device action such as “charge the battery”.

## Planning reduction principle
PicoT reaches an executable decision through four main stages:

1. Opportunity Engine — what is objectively possible or relevant?
2. Candidate Engine — which complete household energy scenarios are feasible?
3. Evaluation Engine — which Candidate best matches the strategy and constraints?
4. Execution Plan — what is actually scheduled for execution?

Each stage deterministically reduces the remaining solution space.

## Records
Opportunities and Constraints are immutable records linked to:

- the Planning Input Set;
- their evidence sources;
- time window;
- confidence;
- lifecycle status.

Suggested Opportunity lifecycle states:

- `DETECTED`
- `ACTIVE`
- `EXPIRED`
- `SUPERSEDED`
- `INVALIDATED`

Historical records remain available for diagnostics, explainability and future replay.

## Boundaries
The Opportunity Engine never:

- selects a device;
- assigns power;
- chooses an Execution Primitive;
- selects a winner;
- creates an Execution Plan;
- applies vendor-specific logic.

## Consequences
The Opportunity Engine remains small and hardware-agnostic. Device competition and resource allocation are deferred to Candidate Generation, while final selection remains the responsibility of Evaluation.
