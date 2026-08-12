# ADR-039 — PV Energy Timeline Contract

**Status:** Proposed  
**Date:** 2026-08-12

## Context

ADR-037 requires PicoT to project the complete household energy balance using expected usable PV together with current storage state and household demand. The existing generic forecast model contains `PV_POWER` points, but the Planner does not yet have one canonical interpretation that converts PV power forecasts and actual PV production into energy per planning interval.

A household energy balance must operate on energy over time, not compare an instantaneous PV power value directly with energy demand. In addition, once actual PV production for elapsed time is known, PicoT must not continue treating the old forecast for that elapsed period as reality.

Without one domain-owned PV energy timeline, multiple planning layers could independently convert power to energy, mix forecast and actual data differently, or continue using stale forecast values for periods whose production is already measured.

## Responsibility

This ADR has one architectural responsibility:

> Define one canonical, immutable PV energy timeline for a Planner Run, combining measured PV energy for known elapsed time with forecast PV energy for the still-unknown future.

It does not calculate household energy requirements, select charging actions, generate Candidates, evaluate Candidates or execute device commands.

## Decision

PicoT introduces a canonical `PVEnergyTimeline` as planning-domain data.

The timeline consists of ordered, non-overlapping intervals covering the relevant planning period. Each interval contains at least:

- interval start and end;
- PV energy in Wh;
- evidence type: `ACTUAL`, `FORECAST`, or where required `MIXED`;
- confidence;
- source/evidence references;
- conversion/method version where a power forecast was converted to energy.

The timeline is assembled once for one Planner Run and is immutable for that run. Downstream planning layers consume this same timeline and must not independently reinterpret raw PV power forecasts or reconstruct competing actual/forecast combinations.

## Energy is the planning quantity

The household balance consumes PV energy in Wh over a defined interval.

A raw instantaneous or interval power value is not itself PV energy. Where the source forecast provides power, PicoT converts it to interval energy through one canonical, versioned domain transformation whose semantics match the source contract.

For a power value that explicitly represents average power over a complete interval, the basic deterministic conversion is:

```text
pv_energy_wh = average_power_w × interval_duration_hours
```

PicoT must not assume that an arbitrary source value is interval-average power. Source/adaptor validation must establish the source semantics before that transformation is used.

## Actual replaces forecast for known elapsed time

Actual measured PV production is authoritative for elapsed time where sufficiently valid measured energy is available.

Once actual production is known for an elapsed interval, the old forecast contribution for that same elapsed interval is not retained in the household energy balance and is not merely represented by lowering forecast confidence.

```text
known elapsed period  → actual PV energy
unknown future period → forecast PV energy + forecast confidence
```

Forecast-versus-actual deviation remains valuable evidence for diagnostics, confidence handling and material-change replanning, but the old forecast is not used as the realised energy value after reality is known.

## Current partially elapsed interval

A planning interval may be partly elapsed at snapshot capture time.

Where sufficiently valid actual PV energy is available for the elapsed portion, PicoT uses that measured energy for the elapsed portion and forecast energy only for the remaining unknown portion. The resulting interval may therefore be marked `MIXED` while preserving separate evidence references for the measured and forecast contributions.

PicoT must not double-count the forecast portion that overlaps already measured production.

If source granularity does not permit a reliable split, the timeline must preserve that uncertainty explicitly rather than inventing precision.

## Actual PV energy source

This ADR defines the canonical planning meaning of actual PV energy; it does not mandate one vendor or Home Assistant entity.

Actual PV energy must originate from a validated, traceable capability/source whose semantics represent produced PV energy over time, or from one accepted canonical integration of validated PV power measurements over time.

The adapter/input assembly layer is responsible for normalising source-specific data. Core planning layers do not query vendor entities directly.

## Forecast PV energy source

Forecast PV energy originates from a validated forecast source and preserves forecast identity, creation time, source, interval coverage and confidence.

If a forecast source exposes power rather than energy, the adapter/domain conversion must preserve the interpretation used, including a conversion/method version. Unsupported or ambiguous source semantics must not be silently treated as average interval power.

## Confidence

Actual and forecast evidence have different uncertainty characteristics.

Measured actual PV energy carries the confidence/source quality of the measurement or accepted integration. Forecast PV energy carries forecast confidence. A `MIXED` interval preserves the confidence/evidence of both contributions; one opaque confidence number must not erase which part was measured and which part remains forecast.

The exact confidence-combination method for later aggregate projections is outside this ADR unless already owned by an accepted confidence contract.

## Relationship to PV deviation monitoring

ADR-039 does not introduce a second PV deviation monitor or a second replanning mechanism.

Existing Runtime Monitor/material-change logic remains responsible for detecting sufficiently material new information and requesting a fresh Planner Run. A fresh Planner Run then assembles a fresh `PVEnergyTimeline` from the newest actual and forecast evidence.

The timeline may expose forecast-versus-actual evidence for diagnostics, but it does not independently trigger replanning.

## Atomic Planning Input boundary

The raw validated inputs required to assemble the timeline belong to the fresh atomic Planning Input process. The canonical timeline is derived once from that immutable input for the Planner Run.

All downstream calculations — projected household balance, storage requirement derivation and Candidate construction where relevant — reuse the same timeline.

No downstream layer may:

- re-read live PV entities;
- independently integrate PV power;
- independently decide whether actual or forecast wins for an elapsed period;
- silently substitute another forecast series.

## Missing or incomplete data

Missing actual PV data does not permit PicoT to claim measured production that it does not know. Where appropriate and still valid, forecast evidence may remain the best available estimate with explicit uncertainty.

Missing or ambiguous forecast semantics prevent unsupported power-to-energy conversion. PicoT degrades explicitly rather than inventing a unit interpretation.

A data gap must remain visible in diagnostics and confidence/evidence. This ADR does not authorize silent interpolation unless a separate accepted contract explicitly defines it.

## Explainability and diagnostics

For every PV timeline interval PicoT can expose at least:

- interval boundaries;
- PV energy used in Wh;
- whether it is actual, forecast or mixed;
- source/evidence references;
- confidence/evidence quality;
- forecast conversion/method version where applicable;
- whether any data gap or ambiguity was present.

For an elapsed interval where actual replaced forecast, diagnostics may retain both values for comparison, while the household balance uses only the actual realised contribution.

## Non-goals

This ADR does not define:

- a new Solcast integration;
- a new PV deviation monitor;
- material-change thresholds;
- household load forecasting;
- projected household balance calculation;
- `StorageEnergyRequirement` calculation;
- battery target SoC;
- grid-charging permission;
- Candidate Generation;
- Candidate Evaluation;
- execution behaviour;
- arbitrary interpolation of missing PV data.

## Relationship to existing ADRs

- ADR-001 remains authoritative for vendor-independent Core contracts.
- ADR-010 remains authoritative for traceable evidence and mapping versions.
- ADR-017 remains authoritative for temporal planning, confidence and recoverability.
- ADR-023 remains authoritative for Opportunity Engine boundaries.
- ADR-028 remains authoritative for fresh atomic Planning Input Snapshots.
- ADR-034 remains authoritative for material-change monitoring and replanning.
- ADR-037 remains authoritative for projected household/storage energy requirements and grid-use planning.
- ADR-038 remains authoritative for immutable Current Storage State.

## Consequences

Positive consequences:

- the Planner reasons about PV in energy over time rather than comparing incompatible power and energy quantities;
- actual production replaces forecast for known elapsed time;
- current partially elapsed intervals can combine measured and still-forecast contributions without double counting;
- all planning layers use one canonical PV interpretation;
- source-specific forecast semantics are validated rather than guessed;
- existing PV deviation monitoring remains the single replan route.

Costs and risks:

- actual PV energy capability/source semantics must be validated;
- forecast power semantics must be known before conversion;
- partial intervals require careful evidence accounting;
- missing source data must be represented explicitly.

## Core principles

> PicoT plans PV as energy over time, not as an isolated instantaneous power value.

> Reality replaces forecast where reality is known; forecast remains only for what is still unknown.

> For one Planner Run, PV energy is assembled once into one immutable canonical timeline and reused everywhere.
