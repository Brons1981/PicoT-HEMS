# ADR-036 — Price Opportunity Detection Contract

**Status:** Accepted  
**Date:** 2026-08-11

## Context

ADR-017 defines a rolling planning horizon and requires PicoT to replan when materially relevant knowledge changes, including publication of next-day energy prices. ADR-023 defines the Opportunity Engine as the stage that turns validated planning inputs into objective, evidence-backed and time-bound opportunities without selecting devices, assigning power, choosing Execution Primitives or producing plans.

The current Price Driven v2 path partly duplicates that responsibility through a separate `PriceOpportunityAnalyzer` and uses price opportunities to derive runtime primitives directly. This has created two architectural problems:

- price-window detection exists outside the canonical `OpportunityEngine` / `OpportunitySet` contract;
- price opportunities can influence execution before Candidate Generation, Evaluation and Execution Plan creation.

The current price-window implementation also restricts analysis to the current calendar date, while ADR-017 requires planning across a rolling horizon that may include the next market day.

A precise contract is therefore required for detecting low-price and high-price opportunities inside the existing Opportunity Engine before Price Driven is moved back into the canonical planning pipeline.

## Decision

PicoT extends the Opportunity Engine with one deterministic Price Opportunity Detection contract.

Price Opportunity Detection consumes validated energy-price forecast points from one immutable `PlanningInputSnapshot` and emits zero or more immutable price-related `Opportunity` records inside the matching `OpportunitySet`.

The detector describes price conditions only. A price opportunity is evidence, not an instruction.

## Supported price opportunity kinds

The detector supports these existing opportunity kinds:

- `NEGATIVE_PRICE_WINDOW` — an objective interval in which the published import price is below zero;
- `LOWEST_PRICE_WINDOW` — a relatively low-price import opportunity;
- `HIGH_EXPORT_VALUE_WINDOW` — a relatively high-price export-value opportunity.

`NEGATIVE_PRICE_WINDOW` remains an absolute-price fact. Relative low-price and high-price windows are detected using explicit, versioned price-reference rules.

## Rolling horizon

Price Opportunity Detection operates on the price points that overlap the complete Planning Input Snapshot horizon:

```text
snapshot.captured_at → snapshot.horizon_end
```

It does not truncate the Opportunity Set at midnight and it does not create a separate planning pipeline for each calendar day.

When next-day prices become available, the new price data enters a fresh Planning Input Snapshot through the normal ADR-017 / ADR-034 replanning flow. The Opportunity Engine then detects all supported price opportunities that fall inside the new rolling horizon.

## Market-day reference scopes

Relative price classification is calculated per local market date represented inside the rolling horizon.

This is a price-reference rule only; it is not a planning boundary.

The purpose is to prevent a newly published, unusually cheap or expensive next market day from suppressing otherwise meaningful price opportunities that still exist in the remaining part of the current market day.

For each represented market date:

- the local daily minimum is the reference for `LOWEST_PRICE_WINDOW` detection;
- the local daily maximum is the reference for `HIGH_EXPORT_VALUE_WINDOW` detection;
- only price points that overlap the snapshot horizon are emitted as Opportunities;
- all emitted Opportunities remain members of one horizon-wide `OpportunitySet`.

No global rank is assigned across market dates.

## Low-price boundary

A price point qualifies for a `LOWEST_PRICE_WINDOW` when its price is less than or equal to an explicit low-price boundary derived from the local daily minimum.

The initial boundary contract is:

```text
low_price_boundary = daily_minimum + low_price_margin_eur_per_kwh
```

`low_price_margin_eur_per_kwh` must be explicit, finite, non-negative and versioned with the planner configuration that produced the Opportunity Set.

The detector must not invent a hidden margin.

## High-price boundary

A price point qualifies for a `HIGH_EXPORT_VALUE_WINDOW` when its price is greater than or equal to an explicit high-price boundary derived from the local daily maximum.

The initial boundary contract is:

```text
high_price_boundary = daily_maximum - high_price_margin_eur_per_kwh
```

`high_price_margin_eur_per_kwh` must be explicit, finite, non-negative and versioned with the planner configuration that produced the Opportunity Set.

The detector must not invent a hidden margin.

## Window construction

Qualifying adjacent price points are grouped into one contiguous Opportunity Window when the end timestamp of one point equals the start timestamp of the next point.

A short internal excursion outside the qualifying boundary may be bridged only under the following deterministic initial rule:

1. the excursion consists of exactly one market-price interval;
2. the qualifying points immediately before and after the excursion are contiguous with it;
3. the excursion does not cross a local market-date boundary;
4. the complete merged window still satisfies the relevant aggregate boundary:
   - low-price window: merged average price is less than or equal to the low-price boundary;
   - high-price window: merged average price is greater than or equal to the high-price boundary.

If any condition fails, the excursion splits the window.

The bridged interval remains part of the Opportunity evidence. It is never hidden from diagnostics or explainability.

A future change to bridge width or bridge qualification requires an accepted ADR update or extension; it must not be introduced as an undocumented implementation heuristic.

## Objective metrics

Every relative price Opportunity records objective metrics sufficient for later Candidate construction, evaluation, diagnostics and replay.

The price opportunity contract requires at least:

- start timestamp;
- end timestamp;
- duration;
- average price;
- minimum price;
- maximum price;
- applicable low-price or high-price boundary;
- number of source price intervals;
- number of bridged non-qualifying intervals;
- confidence;
- complete evidence references to the source forecast points.

Metrics describe the window. They do not rank or score it.

## Multiple opportunities remain available

The Opportunity Engine preserves all qualifying price windows inside the planning horizon.

It does not reduce them to one `best window`, one `best start`, one cheapest quarter-hour or one highest quarter-hour.

The Opportunity Engine does not assign:

- a global opportunity rank;
- a weighted total score;
- a preferred start time;
- a selected device;
- requested power;
- an Execution Primitive;
- a winner.

Meaningful alternatives remain available for Candidate Generation as required by ADR-024.

## Current-day and next-day behavior

Publication of next-day prices adds new evidence and therefore may add, remove, split or reshape future Opportunities in the fresh snapshot.

The existence of a better-priced Opportunity tomorrow does not by itself mean PicoT should stop acting today.

Price Opportunity Detection only states which price windows exist. Whether a current-day, overnight or next-day window participates in a valid household Energy Path is decided later by Candidate Generation and Evaluation using the complete planning context.

## High-price opportunities are not export commands

A `HIGH_EXPORT_VALUE_WINDOW` means only that the market price is objectively high relative to its explicit reference rule.

It does not mean:

- discharge the battery;
- export energy;
- reserve battery SoC for export;
- change household consumption;
- override another plan.

Those decisions require later Candidate, projected-state, capability, strategy and Evaluation contracts.

## Determinism and traceability

For identical immutable Planning Input Snapshots, explicit price-detection configuration and implementation version, Price Opportunity Detection must produce identical:

- opportunity boundaries;
- source point membership;
- bridge decisions;
- metrics;
- ordering;
- identifiers.

Every emitted price Opportunity remains linked to the source forecast and Planning Input Snapshot through immutable evidence references.

## Pipeline boundary

The intended pipeline is:

```text
Planning Input Snapshot
→ Opportunity Engine
→ OpportunitySet
   ├─ NEGATIVE_PRICE_WINDOW
   ├─ LOWEST_PRICE_WINDOW
   └─ HIGH_EXPORT_VALUE_WINDOW
→ Candidate Engine
→ Candidate Set / complete Energy Paths
→ Evaluation Engine
→ Winning Energy Path
→ Execution Plan
→ Runtime / Adapter
```

Price Opportunity Detection never bypasses these stages.

## Migration of Price Driven v2

Implementation of this ADR requires the current Price Driven v2 path to move back toward the canonical planner pipeline.

The migration direction is:

1. make the existing `OpportunityEngine` the authoritative producer of price opportunities;
2. extend the canonical `Opportunity` metrics required by this ADR;
3. stop treating the separate `PriceOpportunityAnalyzer` / `PriceOpportunity` model as an architectural source of truth;
4. remove direct price-opportunity-to-Execution-Primitive selection from Price Driven;
5. feed price Opportunities into the existing Candidate Engine;
6. preserve ADR-031 exclusions for cost-first charging until the required energy-target / projected-state / power-allocation contract is accepted and implemented;
7. only allow physical dispatch after the normal Evaluation and Execution Plan stages.

Temporary diagnostic entities may remain during migration when they are explicitly observation-only and do not become planner inputs.

## Relationship to existing ADRs

- **ADR-017** — uses the rolling planning horizon and next-day-price replan trigger;
- **ADR-023** — Price Opportunity Detection is part of the Opportunity Engine and produces objective evidence only;
- **ADR-024** — multiple meaningful price opportunities remain available for controlled Candidate branching;
- **ADR-026 / ADR-032** — winner selection and objective weighting belong to Evaluation; no opaque opportunity score is introduced here;
- **ADR-031** — an Opportunity is evidence, not an instruction; cost-first charging remains excluded until its missing allocation contracts exist;
- **ADR-034** — publication or material change of price data causes replanning from a fresh atomic snapshot.

## Consequences

- Price Driven no longer needs a parallel opportunity architecture.
- Both low-price and high-price blocks are detected through one symmetric, explicit contract.
- Next-day prices can be incorporated immediately without turning midnight into a planning boundary.
- A very cheap next day cannot silently erase all meaningful current-day price opportunities because relative classification is scoped per market date.
- One slightly adverse interval can remain inside a useful price block only under an explicit and replayable bridge rule.
- Multiple price blocks survive until the Candidate and Evaluation stages where the full household context is available.
- The Opportunity Engine remains hardware-agnostic and cannot directly cause charge, discharge or export behavior.

## Core principle

> Price Opportunity Detection describes all meaningful low-price and high-price windows inside the rolling planning horizon, with explicit evidence and no hidden ranking, while all decisions about what PicoT should actually do remain in the later ADR-defined planning stages.
