# ADR-017 — Planning Decision Pipeline

**Status:** Accepted  
**Date:** 2026-07-31

## Context

PicoT must not react only to the next action. It must compare complete future energy paths over a planning horizon and select the best path based on the available evidence, user priorities, confidence, recoverability and technical constraints.

## Decision

The Planner is a deterministic decision pipeline:

```text
Planning Input Set
→ Confidence Assessment
→ Opportunity Space
→ Candidate Space Reduction
→ Candidate Generation
→ Simulation
→ Candidate Evaluation
→ Decision Selection
→ Planner Decision Record
→ Execution Plan
```

A Candidate is a complete possible solution for the planning horizon, not a single device action or time segment.

## Planning horizon

PicoT plans over a rolling horizon rather than by calendar day.

- Initial nominal horizon: 36 hours.
- The horizon remains configurable and may evolve later.
- The horizon may include periods for which not all data has the same confidence.

This avoids artificial midnight boundaries and allows PicoT to account for the first hours of the next day.

## Event-driven replanning

PicoT replans when materially relevant knowledge changes, not simply because a fixed timer expired.

Examples:

- next-day prices become available;
- a forecast changes materially;
- an EV is connected or disconnected;
- a device becomes unavailable or available;
- a User Rule or User Objective Profile changes;
- Safety status changes;
- observed SoC or power deviates materially from the plan;
- new capabilities become available.

Each trigger creates a new Planning Input Set and an explicit replan reason.

## Confidence-driven planning

Every planning input carries explicit confidence metadata. Confidence may reflect source reliability, forecast horizon, freshness and historical fit.

Examples:

- current SoC: very high confidence;
- published prices: very high confidence as known source values;
- PV forecast for the next two hours: high confidence;
- PV forecast after 30 hours: lower confidence;
- historical household load: medium to high confidence depending on fit.

Confidence is used both to evaluate Candidates and to reduce the search space before full simulation.

## Projected energy state and recoverability

PicoT evaluates complete time paths across the horizon:

```text
current SoC
+ planned grid charging
+ expected PV charging
- expected household demand
- planned trading
- conversion losses
= projected SoC over time
```

A Candidate may temporarily allow a low SoC when future demand remains reliably recoverable before it is needed.

Recoverability asks:

> Can a future energy requirement still be met reliably before its required time?

It considers available charging windows, time, supported power, expected PV, prices, round-trip losses and uncertainty.

A Candidate is invalid when a future requirement cannot be met and no credible recovery path exists.

## Candidate Space Reduction

PicoT does not generate all theoretical Candidates.

The search space is reduced using:

- hard feasibility constraints;
- User Rules;
- Safety and system boundaries;
- confidence thresholds;
- recoverability;
- technical capability support;
- economic relevance;
- dominated-candidate removal.

Only plausible and sufficiently supported scenarios are fully generated, simulated and scored.

Excluded scenarios remain explainable, including the rule, confidence threshold, technical reason or dominating Candidate that caused exclusion.

## Pipeline responsibilities

### Planning Input Engine

Collects, validates and versions facts. It does not plan.

### Opportunity Engine

Detects relevant opportunities and constraints, such as cheap charging windows, expensive discharge windows, PV surplus, negative prices, expected demand or device availability. It does not select a plan.

### Candidate Engine

Builds complete energy paths from the opportunity space and available degrees of freedom.

### Evaluation Engine

Simulates Candidates, evaluates cost, self-consumption, losses, wear, confidence, risk and recoverability, and selects the best valid path according to the active user objectives.

## Explainability

The Decision Record must show:

- which inputs and confidence values were used;
- which opportunities were detected;
- which scenarios were excluded before generation and why;
- which Candidates were simulated;
- each Candidate's evaluation;
- why the selected Candidate won;
- why the closest alternatives were not selected.

## Core principle

> PicoT plans on changes in knowledge, looks beyond the current day, and chooses the best complete energy path within the reliability of the available evidence.
