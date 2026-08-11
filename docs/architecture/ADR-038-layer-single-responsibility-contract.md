# ADR-038 — Layer Single Responsibility and Immutable Data Contract

**Status:** Accepted  
**Date:** 2026-08-11

## Context

PicoT is deliberately built as a layered deterministic planning architecture. Recent Price Driven work showed that it is easy for one layer to absorb logic that belongs to another layer, for example combining price-window detection with storage charging calculations.

A second boundary is equally important: one layer must never change, enrich, reinterpret or mutate another layer's result. Each layer owns only its own facts and emits immutable data. The Planner works from a coherent combined view of those independent layer outputs.

That prevents hidden coupling, circular behaviour and parallel mini-planners beside the accepted ADR architecture.

The project already relies on separation of concerns throughout ADR-017, ADR-023, ADR-024, ADR-026, ADR-033 and ADR-035. This ADR makes the rule explicit and mandatory for future work.

## Decision

Every PicoT planning/runtime layer has exactly one primary responsibility.

Each layer:

- consumes only the immutable inputs explicitly allowed by its own contract;
- calculates only facts that belong to its own responsibility;
- produces an immutable, versioned output describing those facts;
- exposes diagnostics about its own calculation and data quality;
- never mutates another layer's output.

A layer must not:

- change, overwrite, enrich or reinterpret another layer's data in place;
- absorb decision logic owned by another layer;
- silently perform another layer's calculations as a convenience;
- bypass a later responsibility because the required data is already available;
- create a second parallel implementation of an existing architectural responsibility;
- feed a derived result back into another layer in order to make that layer produce a different answer.

## Independent layer outputs

Layers do not control each other. They publish facts.

Examples include:

- Price Opportunity Detection publishes objective price windows and price metrics;
- PV forecasting publishes expected PV production and confidence;
- household-load forecasting publishes expected load and confidence;
- storage-state acquisition publishes measured SoC/capacity-related facts;
- capability mapping publishes immutable supported-control facts;
- User Rules publish validated rule constraints or overrides;
- commitments publish the immutable currently committed execution state.

None of these producers is allowed to rewrite another producer's result.

## Planner Input View

The Planner does not work from a chain in which one layer keeps modifying the previous layer.

Instead, the outputs of the relevant layers are combined into one atomic, immutable planning view for a Planner Run.

Conceptually:

```text
Price data / opportunities ───────┐
PV forecast ──────────────────────┤
Load forecast ────────────────────┤
Storage state ────────────────────┤
Capabilities ─────────────────────┤
Constraints / User Rules ─────────┤──> Atomic Planning Input View ──> Planner
Commitments ──────────────────────┤
Other accepted layer outputs ─────┘
```

The aggregation step does not alter the meaning of any source record. It only snapshots matching immutable records, versions and timestamps into one coherent planning context.

If two layer outputs disagree or cannot be combined consistently, that conflict remains explicit data for planning/diagnostics; one layer does not "fix" the other.

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

Its price outputs remain valid price facts regardless of what storage, PV, load or execution layers later report.

### Candidate Generation

Responsibility: construct supported scenario paths from the atomic planning view using accepted Opportunities, capabilities, constraints and strategy inputs.

It consumes layer outputs; it does not modify them.

It must not perform the downstream Simulation responsibility itself.

### Simulation / Projection

Responsibility: calculate projected energy consequences of Candidate paths, including where applicable expected storage SoC trajectory, expected NOM energy flow and time-to-target.

Its projection is a new immutable planner artifact. It does not alter the original price Opportunity, PV forecast, load forecast, storage state or Candidate inputs.

### Evaluation

Responsibility: compare already-constructed and simulated Candidates according to the accepted objective/tie-break contract.

It does not create new Candidates and does not mutate their projected outcomes.

### Execution

Responsibility: execute the immutable Winning Energy Path / Execution Plan through validated adapters.

It does not re-plan, modify planning evidence or feed local reinterpretations back into planning layers.

## Price Driven hard boundary

Price Driven is a price-analysis responsibility only.

Its output is price evidence, not battery behaviour.

Battery charging calculations, SoC projection, PV/load interaction and expected NOM behaviour are separate planner/simulation responsibilities that consume the price evidence together with other independent layer outputs.

Price Driven is never changed because battery, PV, load or SoC data changed. It may only produce a new result when its own price input changes or its own accepted price-detection configuration changes.

## Ownership precedence

ADR-038 is authoritative for layer ownership and cross-layer immutability.

Where wording in an earlier ADR can be read as assigning a downstream calculation to the wrong layer, this ADR clarifies the ownership without changing the underlying functional requirement.

In particular:

- ADR-031 still requires complete, technically supported Candidate scenarios, but Candidate Generation does not itself perform storage Simulation;
- ADR-037 still requires PicoT to project expected NOM behaviour, SoC trajectory and time-to-target, but that calculation belongs to Simulation / Projection rather than Price Opportunity Detection or Candidate Generation;
- ADR-017's Planning Input Snapshot is the atomic combined view of independently produced layer data, not a mutable object passed through layers for enrichment.

## Pull-request traceability rule

Every PR that changes planner behaviour must state:

1. which ADR-owned layer or aggregation contract is being changed;
2. that component's single responsibility;
3. which neighbouring responsibilities are explicitly not being implemented in that PR;
4. which immutable inputs are consumed and which immutable outputs are produced.

If a change requires one layer to modify another layer's output, the change is architecturally invalid and must not be implemented.

If a change cannot be assigned to exactly one existing responsibility, the architecture contract must be clarified before implementation proceeds.

## Relationship to existing ADRs

- ADR-017 defines the canonical planning pipeline and atomic Planning Input Snapshot;
- ADR-023 owns Opportunity derivation;
- ADR-024 / ADR-031 own Candidate construction;
- ADR-026 / ADR-032 own Evaluation;
- ADR-033 owns Winning Path to Execution Plan translation;
- ADR-035 owns Home Assistant dispatch translation;
- ADR-036 keeps price detection objective and action-free;
- ADR-037 separates storage intent, projection and explicit trading power ownership.

## Consequences

- every layer is an independent producer of immutable facts;
- no layer may mutate or correct another layer's output;
- the Planner works from one atomic combined view of matching layer outputs;
- Price Driven remains price-only;
- storage projection is implemented once, in the projection/simulation responsibility;
- Candidate Generation does not become a simulator;
- Execution does not become a planner;
- disagreements between layer outputs remain explicit and diagnosable;
- ADR drift becomes easier to detect during review.

## Core principle

> One layer, one responsibility, immutable output. Layers provide facts; they never modify each other. The Planner works from one atomic combined view of those independent facts.
