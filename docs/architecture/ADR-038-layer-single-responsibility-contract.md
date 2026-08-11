# ADR-038 — Layer Single Responsibility Contract

**Status:** Accepted  
**Date:** 2026-08-11

## Context

PicoT is deliberately built as a layered deterministic planning pipeline. Recent Price Driven work showed that it is easy for one layer to absorb logic that belongs to another layer, for example combining price-window detection with storage charging calculations.

That creates hidden coupling, makes behaviour harder to explain, and risks building parallel mini-planners beside the accepted ADR architecture.

The project already relies on separation of concerns throughout ADR-017, ADR-023, ADR-024, ADR-026, ADR-033 and ADR-035. This ADR makes the rule explicit and mandatory for future work.

## Decision

Every PicoT planning/runtime layer has exactly one primary responsibility.

A layer may:

- consume immutable outputs from earlier layers;
- validate inputs required for its own responsibility;
- produce immutable outputs for the next layer;
- expose diagnostics about its own work.

A layer must not:

- absorb decision logic owned by another layer;
- silently perform another layer's calculations as a convenience;
- bypass a later layer because the required data is already available;
- create a second parallel implementation of an existing architectural responsibility.

## Canonical ownership examples

### Price Opportunity Detection

Responsibility: derive objective price Opportunities from price forecasts.

It may determine low-price, negative-price and high-export-value windows and their objective price metrics.

It must not inspect or calculate:

- battery SoC;
- battery charge duration;
- PV/load-based battery charging;
- device modes;
- requested battery power;
- Candidate selection;
- Execution Plans.

### Candidate Generation

Responsibility: construct supported scenario paths from accepted Opportunities, capabilities, constraints and strategy inputs.

It must not perform the downstream Simulation responsibility itself.

### Simulation / Projection

Responsibility: calculate projected energy consequences of Candidate paths, including where applicable expected storage SoC trajectory, expected NOM energy flow and time-to-target.

It does not detect price Opportunities and does not select the Winning Candidate.

### Evaluation

Responsibility: compare already-constructed and simulated Candidates according to the accepted objective/tie-break contract.

It does not create new Candidates or mutate their projected outcomes.

### Execution

Responsibility: execute the immutable Winning Energy Path / Execution Plan through validated adapters.

It does not re-plan or reinterpret planning evidence locally.

## Price Driven hard boundary

Price Driven is a price-analysis responsibility only.

Its output is price evidence, not battery behaviour.

Battery charging calculations, SoC projection, PV/load interaction and expected NOM behaviour are owned by the appropriate planning/simulation responsibilities elsewhere in the pipeline.

## Pull-request traceability rule

Every PR that changes planner behaviour must state:

1. which ADR-owned layer is being changed;
2. that layer's single responsibility;
3. which neighbouring responsibilities are explicitly not being implemented in that PR.

If a change cannot be assigned to exactly one existing responsibility, the architecture contract must be clarified before implementation proceeds.

## Relationship to existing ADRs

- ADR-017 defines the canonical planning pipeline and ordering;
- ADR-023 owns Opportunity derivation;
- ADR-024 / ADR-031 own Candidate construction;
- ADR-026 / ADR-032 own Evaluation;
- ADR-033 owns Winning Path to Execution Plan translation;
- ADR-035 owns Home Assistant dispatch translation;
- ADR-036 keeps price detection objective and action-free;
- ADR-037 separates storage intent, projection and explicit trading power ownership.

## Consequences

- Price Driven remains price-only.
- Storage projection is implemented once, in the projection/simulation responsibility.
- Candidate Generation does not become a simulator.
- Execution does not become a planner.
- ADR drift becomes easier to detect during review.
- Future planner work must preserve layer ownership before convenience.

## Core principle

> One layer, one responsibility. A layer may consume another layer's result, but it may not take ownership of that layer's reasoning.
