# ADR-018 — User Objective Model

**Status:** Accepted  
**Date:** 2026-07-31

## Context

Users usually do not think in technical battery modes or planner parameters. They think in desired outcomes such as lower cost, more self-consumption, less battery wear or more reserve.

A direct one-to-one mapping from a UI slider to an internal planner weight can also make user changes feel ineffective when small visible movements barely affect the resulting plan.

## Decision

PicoT asks users which outcomes matter, not how the battery should technically be controlled.

A `UserObjectiveProfile` contains independent objective weights, for example:

- `FINANCIAL_RESULT`
- `BATTERY_LONGEVITY`
- `SELF_CONSUMPTION`
- `DYNAMIC_TRADING`
- `RESERVE_AVAILABILITY`
- `SUSTAINABILITY`

Weights are independent and do not need to sum to 100.

## Priority order

```text
Safety and hard system boundaries
→ active User Rules
→ User Objective Profile
→ Planner optimisation
```

User Rules are explicit instructions. Objectives are soft preferences and may never override hard limits or Safety.

## Objective Mapping Layer

The user interface is explicitly separated from the internal planner model:

```text
User Interface
→ Objective Mapping Layer
→ Internal Objective Vector
→ Planning Decision Pipeline
```

The mapping layer may:

- translate sliders non-linearly;
- use larger internal steps than the visible UI step;
- apply presets;
- translate Preferences Wizard answers;
- expose the mapping transparently.

The mapping layer does not make planner decisions.

Example:

```text
UI slider 0..10
→ internal weight 0, 10, 20, 30, 45, 60, 72, 83, 91, 97, 100
```

The exact mapping will be defined and validated separately.

## Perceived Influence Principle

> Every deliberate user change must have a noticeable influence on PicoT behaviour.

The principle does not mean every slider movement must force a different plan. It means the mapping must be designed so that meaningful user changes are not lost in an overly insensitive internal scale.

## Candidate evaluation

Each Candidate receives normalised scores per objective. The active User Objective Profile determines the transparent weighting.

The Scoring Engine may not add hidden objective weights that are absent from the profile or accepted fixed system rules.

## Profiles and wizard

PicoT may offer presets such as:

- `BALANCED`
- `LOWEST_COST`
- `MAXIMUM_SELF_CONSUMPTION`
- `BATTERY_FRIENDLY`
- `TRADING_FOCUSED`
- `HIGH_RESERVE`

A preset is only a prefilled Objective Vector. The user may inspect and adjust it.

The future Preferences Wizard may translate understandable answers into the same Objective Vector.

## Replanning and history

Changing the active User Objective Profile is a material planning trigger.

Each revision is immutable and versioned. Every Planner Decision references the exact active profile revision.

## Explainability

PicoT must be able to show:

- the visible user setting;
- the internal objective weight;
- how that weight affected Candidate evaluation;
- why a cheaper or more self-consuming alternative was not selected.

## Design philosophy

> A user never configures the PicoT planning algorithm. A user configures only personal objectives and priorities. PicoT deterministically derives the optimal strategy from those objectives within all applicable constraints, User Rules, capabilities and available evidence.

## Consequences

- The Planner remains universal across users.
- Only the Objective Profile changes.
- New strategies can be added without exposing technical modes.
- The user interface is optimised for people; the Planner is optimised for deterministic reasoning.
- The translation between both remains transparent, reproducible and explainable.
