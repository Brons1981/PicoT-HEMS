# ADR-041 — Storage Energy Temporal Value and Replacement Cost Contract

**Status:** Accepted  
**Date:** 2026-08-12

## Context

The accepted PicoT architecture already defines the required foundations for predictive household planning:

- ADR-015 defines vendor-independent execution primitives including standby, balancing, fixed-power charging and fixed-power discharging;
- ADR-017 requires complete Energy Paths over a rolling horizon and defines projected energy state and recoverability;
- ADR-024 / ADR-031 define controlled Candidate construction, including cost-first charging and high-value storage discharge once sufficient projected-state and allocation evidence exists;
- ADR-025 defines Financial Result, Reserve Availability, Battery Longevity and other User Objectives;
- ADR-026 defines deterministic comparison of complete Candidate outcomes;
- ADR-036 preserves meaningful low-price and high-price Opportunities without turning them into commands;
- ADR-037 defines HouseholdLoadForecast, projected household energy balance, StorageEnergyRequirement with a `required_by` time, conservative reserve, PV-first feasibility and explicit grid-supported charging;
- ADR-039 defines the canonical PV Energy Timeline using actual PV for known elapsed time and forecast PV for the unknown future.

These contracts deliberately do not yet define how PicoT compares the economic value of one unit of stored battery energy at different future times.

A locally sensible action can be globally inferior. For example, using stored energy during a moderately priced period may avoid grid import now but consume energy that could avoid much more expensive import later. Conversely, preserving battery energy throughout the night can be inferior when that energy could avoid an expensive evening interval and be replaced later from a substantially cheaper grid-charging opportunity or expected PV.

This missing contract must be explicit before high-value discharge, strategic standby and economically timed replacement charging can be evaluated consistently.

## Responsibility

This ADR has one architectural responsibility:

> Define how PicoT represents and compares the time-dependent economic value and replacement cost of stored energy inside complete Candidate Energy Paths.

It does not create a new Planner stage, strategy, execution mode or vendor-specific control path.

## Decision

PicoT evaluates stored energy as a time-dependent planning resource.

The economic value of stored energy is not determined only by the current market price. It depends on the complete remaining Energy Path, including future household demand, StorageEnergyRequirements and deadlines, expected PV, future import/export prices, conversion losses, storage limits, supported charge/discharge power, confidence and recoverability.

Candidate Outcome Production derives the economic consequences of using, preserving or replacing stored energy over the complete planning horizon. Evaluation compares those already-derived outcomes under ADR-025 / ADR-026.

No Opportunity, current price or battery SoC may independently command charge, discharge or standby behaviour.

## Temporal storage value

For a Candidate Energy Path, stored energy at time `t` has future value when retaining that energy can avoid a more costly or otherwise strategically inferior energy source later in the horizon.

Examples include:

- preserving battery energy during a cheap midday import period so it remains available during an expensive evening period;
- deliberately discharging during an expensive evening period when the consumed energy can be replaced later at materially lower expected cost;
- charging only enough during a cheap night period to cover expensive morning demand until expected PV becomes reliably available;
- preserving free storage capacity when expected PV would otherwise be curtailed or exported at a less favourable value.

Temporal value is derived from the complete Candidate path. PicoT does not assign one permanent monetary value to a battery kWh.

## Replacement cost

When a Candidate consumes stored energy before a later StorageEnergyRequirement, PicoT determines whether the consumed energy remains recoverable and, where replacement is required, derives the expected cost of the feasible replacement path.

Replacement may originate from:

- expected usable PV;
- explicitly permitted grid-supported charging;
- another accepted household energy flow represented in the Candidate.

Replacement cost includes, where applicable:

- imported energy cost in the selected future price interval;
- charging and discharging conversion losses;
- round-trip efficiency effects where the complete cycle is relevant;
- additional grid import caused by the replacement action;
- lost PV self-consumption or increased export consequences;
- applicable storage wear/cycling outcome information where available;
- switching/execution consequences already represented by the Candidate outcome.

PicoT must not treat one discharged kWh as replaceable by exactly one imported kWh when accepted efficiency evidence shows otherwise.

## Economic discharge comparison

A high-price Opportunity is evidence only, as required by ADR-036.

A discharge Candidate may be economically preferable when the expected avoided cost/value obtained by using stored energy during that interval exceeds the expected consequences of preserving or later replacing that energy, while all future StorageEnergyRequirements remain feasible and recoverable.

Conceptually:

```text
value of using stored energy now
versus
value of preserving it for later
and/or
expected cost of replacing it before a future requirement
```

The implementation must use complete Candidate outcomes rather than a hidden single-threshold rule such as `current_price > replacement_price`.

## Strategic standby

`STANDBY` already exists as an ADR-015 Execution Primitive.

This ADR establishes that a Candidate may deliberately preserve storage through a period in which the battery could technically discharge when the complete projected path shows that stored energy has greater expected future value or is required for a future reserve/deadline.

Standby is therefore a valid strategic energy-path choice, not merely an error or inactive fallback state.

Candidate Generation remains responsible for constructing such an Energy Path only under an accepted scenario template. This ADR does not directly create the template.

## Partial future charging

Grid-supported charging does not imply charging to the effective maximum SoC.

ADR-037 remains authoritative for the conservative default target and for evidence allowing a lower target. Temporal-value analysis may support a Candidate that purchases only the amount of energy required to reach one or more future StorageEnergyRequirements before expected PV or another recovery source becomes available.

For example, a night charging Candidate may target only the energy needed to cover expected expensive morning demand until a sufficiently reliable PV recovery interval.

This is not a new `target_soc_at_time` architecture. It uses the existing ADR-037 `StorageEnergyRequirement(required energy/SoC, required_by)` contract, potentially with multiple time-bound requirements over the planning horizon.

## Multiple time-bound requirements

PicoT may have multiple StorageEnergyRequirements within one rolling horizon.

A Candidate must preserve feasibility across all applicable requirements. Satisfying a later high target does not excuse violating an earlier requirement, and preserving an early reserve does not automatically require retaining that energy after its purpose has passed.

This allows storage reserve to change over time without converting a strategic reserve into a fake hardware minimum SoC.

Hardware/configured minimum and maximum SoC limits remain hard capability/system boundaries. Planner-derived reserve requirements remain time-bound planning requirements.

## Recoverability and latest feasible recovery

ADR-017 and ADR-037 remain authoritative for recoverability.

For temporal-value calculations PicoT may derive the latest feasible start of a recovery action from explicit requirements, available opportunity windows, expected PV, supported charging power, storage limits, losses and confidence.

This derived `latest feasible recovery start` is not a new Planner stage and is not an execution command. It is evidence used to reject paths that postpone recovery beyond a credible deadline and to compare paths that recover at different feasible opportunities.

No hidden fixed latest-start margin may be invented. Any safety/confidence margin used in the derivation must be explicit, versioned and explainable.

## Relationship to delegated realtime balancing

PicoT Core remains vendor-independent.

A selected Energy Path may use balancing primitives whose realtime power regulation is delegated by a Device Adapter to an integration or device controller. For example, an adapter may translate a generic balancing primitive into a vendor mode that reacts to live P1 measurements.

Such delegated realtime control does not receive or inherit PicoT forecast intelligence unless its capability contract explicitly provides that behaviour.

PicoT therefore remains responsible for the strategic Energy Path: when balancing is appropriate, when storage should be preserved, when fixed-power charging/discharging is justified, and when changed reality requires replanning.

The current Zendure/@gielz implementation is not part of this Core contract. A future PicoT-specific Zendure execution engine may replace that adapter/runtime implementation without changing this ADR.

## Replanning from reality

Temporal-value decisions are valid only for the immutable evidence of their Planner Run.

Material changes in actual household flow, storage SoC/power, PV production/forecast, prices, capability state or execution outcome follow ADR-034 and request a fresh Planning Input Snapshot and Planner Run where applicable.

PicoT does not continuously mutate the old plan from live values. Reality changes the evidence; new evidence produces a new plan.

## Explainability

Where temporal storage value materially affects the selected Candidate, PicoT must be able to expose at least:

- stored energy available at the relevant decision time;
- applicable future StorageEnergyRequirements and deadlines;
- current and relevant future price Opportunities;
- expected PV/recovery contribution;
- whether replacement energy is required;
- feasible replacement source and interval where applicable;
- expected replacement energy including accepted loss assumptions;
- expected replacement cost where grid energy is used;
- whether preserving storage was evaluated;
- whether standby, charging or discharging alternatives were excluded and why;
- the decisive financial and non-financial outcome differences used by Evaluation.

A user-facing explanation may state, for example, that stored energy is used during an expensive evening period because the expected avoided import cost exceeds the expected cost of replacing the required energy during a later cheaper interval, while the next reserve requirement remains recoverable.

## Non-goals

This ADR does not define:

- a new Opportunity Engine;
- a new Candidate Engine;
- a hidden battery-arbitrage score;
- fixed universal price-difference thresholds;
- fixed universal SoC targets;
- direct price-to-action mapping;
- vendor-specific NOM, smart-charge or smart-discharge modes;
- realtime P1 power-control algorithms;
- battery degradation pricing where no accepted degradation model exists;
- dynamic trading as a separate strategy;
- a PicoT Zendure execution engine.

## Relationship to existing ADRs

- ADR-015 remains authoritative for generic Execution Primitives.
- ADR-017 remains authoritative for rolling-horizon Energy Paths, projected state and recoverability.
- ADR-024 remains authoritative for controlled Candidate branching.
- ADR-025 remains authoritative for User Objectives and strategy priority.
- ADR-026 / ADR-032 remain authoritative for deterministic winner selection from derived Candidate Outcomes.
- ADR-031 remains authoritative for Candidate Scenario Construction and its current exclusions until required contracts are implemented.
- ADR-034 remains authoritative for material-change replanning.
- ADR-036 remains authoritative for price Opportunity Detection; price Opportunities remain evidence, not commands.
- ADR-037 remains authoritative for household demand, StorageEnergyRequirement, reserve, PV-first feasibility and explicit grid-supported charging.
- ADR-038 remains authoritative for Current Storage State.
- ADR-039 remains authoritative for the PV Energy Timeline.
- ADR-040 remains authoritative for ingestion from real source entities into canonical planning evidence.

## Consequences

Positive consequences:

- PicoT can compare using battery energy now with preserving it for a more valuable future period;
- expensive-period discharge can be compared against later cheap replacement rather than being triggered by price alone;
- cheap grid charging can be partial and requirement-driven rather than automatically filling the battery;
- strategic standby becomes economically meaningful without inventing a fake minimum SoC;
- winter planning can make greater use of price shifting when PV recovery is limited;
- the design remains deterministic, explainable and vendor-independent;
- a future Zendure execution engine can be introduced without changing Planner economics.

Costs and risks:

- Candidate Outcome Production must model losses and replacement energy consistently;
- multiple time-bound requirements increase simulation complexity;
- uncertain PV/load forecasts can materially affect estimated replacement value and must preserve confidence;
- battery wear cannot be monetised until an accepted wear/degradation model exists;
- insufficient Candidate diversity can hide a better temporal path even when the evaluation model is correct.

## Core principles

> A stored kWh does not have one fixed value; its value depends on when it can avoid a less favourable future energy flow.

> PicoT compares complete Energy Paths: using energy now is attractive only when the resulting future path remains feasible, recoverable and preferable under the active Planner Strategy.

> Price is evidence, not a command. Storage reserve is time-bound planning state, not a fabricated hardware limit.
