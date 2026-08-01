# ADR-024 — Candidate Engine

## Status
Accepted

## Context
After the Opportunity Engine has reduced the Planning Input Set to objective Opportunities and Constraints, PicoT must create a limited set of complete household energy scenarios without exploding into millions of combinations.

## Decision
The Candidate Engine builds a small, diverse and meaningful Candidate Set. A Candidate is a complete possible household energy path over the planning horizon, not a single device action.

The Candidate Engine answers:

> Which complete energy scenarios are technically and logically feasible?

It does not choose the winner. Winner selection belongs to the Evaluation Engine.

## Reduction strategy
PicoT uses a narrow strategy where safe, but preserves meaningful alternatives.

### Hard reduction
A scenario is discarded immediately when it is objectively impossible or violates a hard boundary, for example:

- PV charging without available PV;
- EV charging while the EV is unavailable;
- insufficient time to meet a required energy target;
- violation of a hard system constraint;
- violation of an active User Rule;
- unsupported control capability.

### Controlled branching
When several valid energy paths exist, PicoT keeps a limited representative set rather than every possible micro-variation.

Candidate Families may include:

- sequential execution;
- parallel execution;
- priority-first execution;
- PV-first execution;
- cost-first execution;
- reserve-first execution;
- limited-power parallel execution.

Time variants are built from meaningful Opportunity Windows, not arbitrary minute-by-minute start times.

## Strategic guidance
The Planner Strategy Model influences Candidate Generation.

User Objectives determine which scenario families are strategically relevant. The optimisation profile determines how broadly PicoT searches:

- Conservative;
- Balanced;
- Active;
- Maximum.

User Objectives may reduce the Candidate Space, but may never override Safety, hard constraints or User Rules.

## Dominance
A Candidate may be removed early only when it is demonstrably dominated: it is no better on any relevant objective and worse on at least one relevant objective.

If a Candidate is cheaper but causes more battery wear, both may remain because each can be preferable under a different User Objective profile.

## Output
The Candidate Engine produces a finite immutable Candidate Set linked to:

- Planning Input Set;
- Opportunity and Constraint records;
- Strategy version;
- Device capabilities;
- assumptions and confidence;
- exclusion reasons for rejected scenario families.

## Core principle
> PicoT uses hard reduction for impossible scenarios, controlled branching for valid alternatives, User Objectives for strategic direction and the optimisation profile for search breadth. Only a small, diverse and meaningful Candidate Set proceeds to Evaluation.
