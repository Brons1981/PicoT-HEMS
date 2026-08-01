# ADR-026 — Evaluation Engine

## Status
Accepted

## Context
The Candidate Engine produces a limited set of feasible complete household energy paths. PicoT must deterministically select exactly one winner according to the active Planner Strategy Model without using an opaque score that cannot be explained.

## Decision
The Evaluation Engine compares Candidates per strategic objective and selects exactly one Winning Candidate.

It does not create new Opportunities or Candidates, modify User Rules or User Objectives, or choose vendor commands.

## Comparison model
PicoT does not rely on one hidden aggregate score.

For each relevant User Objective, the Evaluation Engine records how each Candidate performs relative to the other Candidates. Examples include:

- financial result;
- self-consumption;
- battery longevity;
- reserve availability;
- sustainability;
- net balance;
- future objectives.

The final selection follows the active Planner Strategy Model and remains fully reproducible.

## Tie-break order
When multiple Candidates remain equivalent after the normal comparison, PicoT applies this deterministic order:

1. objective with the highest user-assigned priority;
2. objective with the second-highest priority;
3. remaining objectives in descending priority order;
4. highest confidence;
5. highest recoverability;
6. lowest execution complexity and fewest unnecessary switches;
7. stable deterministic Candidate identifier order.

Equal User Objective percentages therefore never cause randomness.

## Explainability
The Evaluation Record must show:

- which Candidate won per objective;
- which objectives were equal;
- which objective or tie-break step decided the winner;
- confidence and recoverability used;
- rejected alternatives and the decisive differences.

Example user explanation:

> Candidate A was selected because Financial Result is your highest priority and it provided a better expected financial result. The lower self-consumption of Candidate A had less influence under your current strategy.

## Output
The Evaluation Engine outputs exactly one Winning Candidate together with an immutable Evaluation Record.

## Core principle
> PicoT selects a winner through an explainable deterministic comparison per strategic objective, not through an opaque total score. Every tie-break follows a fixed and reproducible decision order.
