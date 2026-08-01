# ADR-032 — Candidate Evaluation Contract

**Status:** Proposed  
**Date:** 2026-08-01

## Context

ADR-026 defines the Evaluation Engine as the deterministic stage that selects exactly one Winning Candidate through transparent comparison per strategic objective. ADR-024, ADR-030 and ADR-031 define the immutable Candidate Set, Energy Paths and the first scenario-construction rules.

A remaining contract gap prevents a correct Evaluation Engine implementation:

- Candidate records currently contain traceability and confidence, but no comparable objective outcomes;
- recoverability, execution complexity and switching impact are referenced by ADR-026 but not represented by a fixed domain contract;
- the immutable Evaluation Record and Winning Candidate result are not yet defined;
- the exact meaning of "winner per objective" and the deterministic tie-break procedure must be made explicit before code is written.

Implementing these choices directly in the Evaluation Engine would hide architecture inside code.

## Decision

PicoT introduces an immutable Candidate Evaluation contract inside the existing Evaluation Engine layer.

The Evaluation Engine receives:

- one immutable `CandidateSet`;
- the matching immutable `PlannerStrategy`;
- one immutable `CandidateOutcomeSet` containing comparable, already-derived outcomes for every Candidate.

It returns one immutable `EvaluationResult` containing:

- exactly one Winning Candidate reference;
- one complete `EvaluationRecord`;
- no modified Candidate, Energy Path, User Objective or Planner Strategy.

The Evaluation Engine compares; it does not simulate, generate or execute.

## Candidate outcomes

A `CandidateOutcomeSet` belongs to one Candidate Set and contains exactly one `CandidateOutcome` per Candidate.

Each `CandidateOutcome` contains at least:

- Candidate identifier;
- objective outcomes;
- confidence;
- recoverability;
- execution complexity;
- expected switching count;
- validity status;
- invalidity reasons where applicable;
- evidence references.

All values are immutable and traceable to the same Planning Input Snapshot and Candidate Set.

A missing outcome for a Candidate is an atomic-input error. An outcome for an unknown Candidate is also an atomic-input error.

## Objective outcome model

Each objective outcome is represented by an immutable `ObjectiveOutcome` containing:

- `ObjectiveKind`;
- comparable numeric value;
- comparison direction;
- unit;
- confidence;
- evidence references.

Initial comparison directions:

- `HIGHER_IS_BETTER`
- `LOWER_IS_BETTER`

The unit is explicit and objective-specific. Examples include:

- expected financial result in `EUR`;
- self-consumption in `WH` or a documented ratio;
- battery wear in an accepted wear unit;
- reserve availability in `WH` or ratio;
- sustainability in an accepted emissions or renewable-energy unit;
- net balance deviation in `W` or `WH`.

The Evaluation Engine never compares values with different units for the same objective. A unit mismatch is an input error.

No default outcome value is invented. If an objective cannot be evaluated for all valid Candidates with comparable values, that objective is recorded as unavailable for this Evaluation Run and cannot decide the winner.

## Validity boundary

Only valid Candidates participate in winner selection.

Initial validity states:

- `VALID`
- `INVALID`

An invalid Candidate remains present in the Evaluation Record with its reasons but cannot win.

If no valid Candidate exists, the Evaluation Engine returns no winner and a deterministic `NO_VALID_CANDIDATE` result. It does not silently choose an invalid path.

Because Candidate Generation preserves a baseline where the contracts support it, a no-winner result indicates an explicit planning failure that must remain diagnosable.

## Strategic objective order

The Planner Strategy determines the objective comparison order.

Objectives are ordered by:

1. descending internal `ObjectiveWeight`;
2. stable `ObjectiveKind` value order when weights are equal.

Objectives with weight zero do not decide the winner, but may still be recorded for explainability.

No hidden objective or implicit fallback weight enters Evaluation.

## Objective comparison

For each deciding objective in strategic order:

1. compare all remaining valid Candidates using that objective's declared comparison direction;
2. retain the best Candidate or tied group;
3. record each Candidate's value, direction, unit and relative result;
4. stop when exactly one Candidate remains;
5. otherwise continue to the next objective.

A comparison may produce:

- `BETTER`
- `EQUAL`
- `WORSE`
- `UNAVAILABLE`

The first objective or tie-break step that leaves exactly one Candidate is the decisive step.

## Numeric equality

Evaluation uses exact immutable domain values unless a future accepted ADR defines an objective-specific tolerance.

The first implementation does not introduce hidden floating-point tolerances. Outcome producers are responsible for deterministic normalization before values enter the Evaluation Engine.

## Tie-break sequence

When strategic objectives do not produce one winner, the Evaluation Engine applies ADR-026 in this exact order:

1. highest confidence;
2. highest recoverability;
3. lowest execution complexity;
4. lowest expected switching count;
5. lexicographically smallest stable Candidate identifier.

Each tie-break step is recorded, including the compared values and whether the group remained tied.

### Confidence

Candidate evaluation confidence is a normalized value from `0.0` to `1.0` supplied by the Candidate Outcome.

It does not replace the Candidate's construction confidence. The outcome record references the source of the final evaluation confidence.

### Recoverability

Recoverability is a normalized value from `0.0` to `1.0` expressing how reliably the Candidate can still meet future required energy states before their deadlines.

A value may only be supplied when recoverability has been deterministically derived from accepted projected-state and requirement contracts. Unknown recoverability remains `None` and cannot be treated as zero.

When recoverability is unavailable for any remaining Candidate, this tie-break step is recorded as unavailable and skipped for the entire tied group.

### Execution complexity

Execution complexity is a non-negative integer derived from explicit path characteristics, initially:

- number of controllable Path Segments;
- number of execution scopes used;
- number of primitive transitions.

The exact derivation version is stored in the Candidate Outcome. The Evaluation Engine consumes the result and does not recalculate it.

### Expected switching count

Expected switching count is a non-negative integer representing expected device switching events under the Candidate path.

Unknown switching count remains `None`. When unavailable for any remaining Candidate, this tie-break step is recorded as unavailable and skipped for the entire tied group.

## Evaluation record

The immutable `EvaluationRecord` contains at least:

- evaluation identifier;
- schema version;
- snapshot identifier;
- strategy version;
- Candidate Set reference;
- evaluated Candidate identifiers;
- invalid Candidate records and reasons;
- strategic objective order;
- per-objective comparison records;
- tie-break records;
- decisive step;
- Winning Candidate identifier, or explicit no-winner outcome;
- creation timestamp;
- implementation version.

Every per-objective comparison record contains:

- objective;
- configured weight;
- comparison direction;
- unit;
- Candidate values;
- relative results;
- Candidates retained after that step;
- whether the step was decisive.

Every tie-break record contains:

- tie-break kind;
- Candidate values;
- Candidates retained;
- whether the step was available;
- whether the step was decisive.

## Evaluation result

`EvaluationResult` contains:

- the immutable `EvaluationRecord`;
- the Winning Candidate reference when one exists;
- the matching Winning Energy Path reference when one exists;
- an outcome status.

Initial outcome statuses:

- `WINNER_SELECTED`
- `NO_VALID_CANDIDATE`

The Winning Candidate and Winning Energy Path must already exist in the input Candidate Set and must reference each other exactly as validated by that set.

## Atomicity and validation

Before comparison, the Evaluation Engine rejects input when:

- snapshot IDs differ;
- strategy versions differ;
- Candidate IDs and Outcome IDs do not match exactly;
- objective units or directions differ between Candidates for the same objective;
- duplicate objective outcomes exist for one Candidate;
- confidence or recoverability falls outside `0.0..1.0`;
- complexity or switching values are negative;
- an Evaluation Result would reference a Candidate or Energy Path outside the Candidate Set.

No partial Evaluation Result is returned for mismatched atomic inputs.

## Determinism

For identical immutable inputs and the same implementation version, Evaluation produces identical:

- objective order;
- comparison records;
- tie-break records;
- decisive step;
- winner or no-winner outcome;
- identifiers and ordering.

Random choice is never used.

Evaluation identifiers are derived deterministically from the snapshot, Candidate Set, strategy and implementation version.

## Initial implementation boundary

The first Evaluation Engine slice implements:

1. immutable outcome and evaluation domain records;
2. atomic input validation;
3. valid-Candidate filtering;
4. ordered per-objective comparison;
5. the complete deterministic tie-break sequence;
6. winner and Winning Energy Path selection;
7. complete immutable Evaluation Record output.

The first slice does not calculate financial results, self-consumption, wear, reserve or sustainability itself. Those outcomes must be supplied by accepted simulation or outcome-producing contracts.

Until such producers exist, unit tests use explicit deterministic Candidate Outcomes.

## Relationship to existing ADRs

- ADR-017: Evaluation compares complete Energy Paths and preserves explainability;
- ADR-018 and ADR-025: visible user preferences map to explicit internal objective weights;
- ADR-024: only the finite Candidate Set enters Evaluation;
- ADR-026: comparison remains per objective with a fixed tie-break order and no opaque aggregate score;
- ADR-027: Evaluation does not alter committed Execution Plans;
- ADR-030: Winning Candidate and Energy Path remain immutable and traceable;
- ADR-031: scenario construction remains separate from comparison.

## Consequences

- The Evaluation Engine can be implemented without hidden scoring policy.
- Objective outcomes remain unit-safe and comparable.
- Unknown recoverability or switching information is not silently converted into a disadvantage.
- Invalid Candidates remain explainable but cannot win.
- A no-valid-candidate result becomes an explicit diagnosable planner outcome.
- Outcome calculation remains separate from Evaluation without introducing a new architectural layer.

## Core principle

> Evaluation compares immutable Candidate outcomes in the exact order defined by the active Planner Strategy, records every objective and tie-break step, and selects one existing Candidate without hidden weights, invented values or opaque total scores.
