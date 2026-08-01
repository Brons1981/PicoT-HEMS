# ADR-025 — Planner Strategy Model

## Status
Accepted

## Context
PicoT does not search for one universal optimum. It must search for the best plan for the current user, based on explicit objectives and an explicit optimisation intensity, while preserving all hard technical and user-defined boundaries.

## Decision
PicoT uses a Planner Strategy Model as a cross-cutting model beside the Planning Decision Pipeline.

It is not a separate pipeline stage. It influences every planner stage in which multiple valid choices remain.

The Planner Strategy Model contains at least:

- User Objectives;
- Optimisation Profile;
- strategy version and mapping version.

User Objectives may include:

- Financial Result;
- Self-consumption;
- Battery Longevity;
- Reserve Availability;
- Sustainability;
- Net Balance;
- future objectives.

The Optimisation Profile determines how intensively PicoT searches and reacts:

- Conservative;
- Balanced;
- Active;
- Maximum.

The profile changes search breadth, confidence thresholds, replanning sensitivity and resource budgets, but never changes Safety or hard system limits.

## Objectives versus Rules
User Objectives describe what the user wants to achieve.

User Rules describe explicit constraints or required behaviour.

Priority order remains:

1. Safety Layer;
2. hard system and hardware constraints;
3. User Rules;
4. Planner Strategy Model;
5. optimisation within the remaining solution space.

Core principle:

> User Rules limit the Planner’s playing field. User Objectives determine how PicoT uses the remaining playing field.

## Cross-cutting influence
The Planner Strategy Model may influence:

- which Opportunities are strategically relevant;
- which Candidate Families are generated;
- how Candidates are evaluated;
- how broadly PicoT optimises;
- how Planning Preview comparisons are presented.

It may never invent new capabilities or override hard constraints.

## Strategy immutability
The strategy is immutable during a Planner Run.

Only an explicit user action may change User Objectives or the Optimisation Profile.

A changed situation starts a new Planner Run with the same strategy.

A changed strategy starts a new Planner Run with a new strategy version.

Core rule:

> New circumstances lead to a new plan. New objectives lead to a new strategy. PicoT never changes the user’s strategy autonomously.

## Planning Preview
Changes to objectives or important settings may be evaluated through a Planning Preview before activation.

The Preview:

- performs a full Planner Run without execution;
- shows a planning timeline;
- compares the current and proposed plan;
- shows expected changes in cost, self-consumption, cycling, import/export and relevant goals;
- requires explicit user confirmation before activation.

A Planning Preview is a momentary forecast based on currently available information, not a guarantee. New prices, forecasts, states or rules may later change the real plan.

## Design philosophy
> The Planner is generic. The Planner Strategy Model makes the Planner personal.

> The user does not configure the energy plan. The user configures objectives. PicoT deterministically derives the best possible plan within all boundaries.
