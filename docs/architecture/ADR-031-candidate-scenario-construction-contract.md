# ADR-031 — Candidate Scenario Construction Contract

**Status:** Proposed  
**Date:** 2026-08-01

## Context

ADR-023 defines objective Opportunities without selecting devices, assigning power or choosing Execution Primitives. ADR-024 requires the Candidate Engine to build a small, diverse set of complete household energy scenarios. ADR-030 defines `CapabilitySnapshotSet`, `EnergyPath` and `CandidateSet`.

A remaining contract gap prevents a correct Candidate Engine implementation:

- an Opportunity does not prescribe an Execution Primitive;
- the same Opportunity may support several valid household scenarios;
- `LogicalCapabilitySnapshot` currently describes supported primitives and limits, but not the logical energy role needed to construct meaningful paths;
- a Candidate must be a complete Energy Path over the planning horizon, not a one-to-one conversion of an Opportunity into an action.

Implementing direct Opportunity-to-Primitive mapping in code would therefore introduce architectural policy outside an ADR.

## Decision

PicoT introduces a deterministic Candidate Scenario Construction contract.

The Candidate Engine constructs complete Energy Paths from:

- one matching `PlanningInputSnapshot`;
- one matching `OpportunitySet`;
- one matching `CapabilitySnapshotSet`;
- the immutable `PlannerStrategy` contained in the Planning Input Snapshot;
- explicit scenario-family rules defined by this ADR and later accepted extensions.

The Candidate Engine never treats an Opportunity as an instruction.

## Logical capability role

Each `LogicalCapabilitySnapshot` includes one explicit logical role:

- `ENERGY_STORAGE`
- `FLEXIBLE_CONSUMER`
- `CONTROLLABLE_PRODUCER`
- `GRID_INTERFACE`
- `BALANCING_RESOURCE`

A role describes how a logical capability participates in household energy paths. It is vendor-independent and does not replace supported Execution Primitives or technical limits.

Unknown roles remain explicit and are not guessed from names, entities or vendor integrations.

## Scenario construction principle

The Candidate Engine uses accepted scenario templates. A template defines:

- applicable Opportunity kinds;
- required logical capability roles;
- required Execution Primitives;
- required capability limits and state;
- Candidate Family;
- path-segment construction rule;
- projected-state requirements;
- objective exclusion reasons when construction is impossible.

A template may create zero, one or several representative Energy Paths. It may not generate arbitrary minute-by-minute variants.

## Initial scenario templates

The first implementation supports only the templates below.

### PV-first storage charging

Applicable Opportunity:

- `PV_SURPLUS_WINDOW`

Required capability:

- role `ENERGY_STORAGE`;
- availability `AVAILABLE`;
- health `HEALTHY`;
- primitive `CHARGE_AT_POWER`;
- known positive maximum power;
- known charge flow support.

Construction:

- Candidate Family `PV_FIRST`;
- one Path Segment within the Opportunity window;
- requested power is the minimum of expected PV-surplus power and capability maximum power;
- capability minimum power and power step are enforced when known;
- the path covers the full planning horizon, while only the controllable segment occupies the Opportunity window;
- confidence is the minimum of Opportunity confidence and capability confidence.

If expected PV-surplus power is unavailable, maximum power is unknown, or the resulting requested power cannot satisfy the capability limits, the template is excluded. PicoT does not invent a power value.

### Cost-first storage charging

Applicable Opportunities:

- `NEGATIVE_PRICE_WINDOW`
- `LOWEST_PRICE_WINDOW`

Required capability:

- role `ENERGY_STORAGE`;
- availability `AVAILABLE`;
- health `HEALTHY`;
- primitive `CHARGE_AT_POWER`;
- known positive maximum power;
- known charge flow support.

Construction:

- Candidate Family `COST_FIRST`;
- one Path Segment within the Opportunity window;
- requested power requires an explicit supported planning value derived from known capability limits and future energy requirements;
- without a required energy target, Energy Profile or accepted power-allocation rule, no charging Candidate is created.

This prevents the Candidate Engine from assuming that maximum charging is always desirable.

### High-value storage discharge

Applicable Opportunity:

- `HIGH_EXPORT_VALUE_WINDOW`

Required capability:

- role `ENERGY_STORAGE`;
- availability `AVAILABLE`;
- health `HEALTHY`;
- primitive `DISCHARGE_AT_POWER`;
- known positive maximum power;
- known discharge flow support.

Construction:

- Candidate Family `COST_FIRST`;
- one Path Segment within the Opportunity window;
- requested power requires an explicit supported allocation derived from projected SoC, reserve requirements, household demand and capability limits;
- without sufficient projected-state support, no discharge Candidate is created.

This prevents the Candidate Engine from assuming available energy or sacrificing required reserve.

## Baseline path

Candidate Generation always preserves one technically valid baseline path when the available contracts support it.

The baseline path:

- uses Candidate Family `RESERVE_FIRST`;
- contains no speculative charge or discharge segment;
- preserves the current controllable state through a supported non-power primitive where such a primitive is explicitly available;
- otherwise contains no controllable segments;
- spans the complete planning horizon;
- records assumptions and capability references actually used.

The baseline is not automatically the winner. It provides a safe comparison alternative for Evaluation.

## Complete Energy Path requirement

Every generated Candidate references exactly one Energy Path contained in the same `CandidateSet`.

An Energy Path:

- spans the full Planning Input Snapshot horizon;
- contains only segments supported by matching logical capabilities;
- contains sufficient projected state points for every hard feasibility decision made during generation;
- references every Opportunity, Constraint and capability it actually uses;
- records all assumptions explicitly;
- remains immutable after creation.

A path is not complete merely because it contains one valid Path Segment.

## Matching and atomicity

Before generation, the Candidate Engine rejects mismatched inputs when:

- snapshot IDs differ;
- capability mapping versions differ;
- strategy versions differ;
- capture chronology is inconsistent.

No partial Candidate Set is returned for mismatched atomic inputs.

## Exclusions

Rejected templates produce immutable `CandidateExclusion` records.

The initial objective exclusion reasons include:

- no matching logical role;
- unsupported Execution Primitive;
- unavailable capability;
- unhealthy capability;
- unknown required power limit;
- missing projected-state support;
- insufficient SoC or reserve evidence;
- unsupported energy-flow direction;
- hard boundary violation.

Source references include the relevant Opportunity and capability IDs where available.

## Determinism

For identical immutable inputs and the same implementation version, Candidate Generation produces identical:

- scenario families;
- Energy Paths;
- Candidates;
- exclusions;
- ordering;
- identifiers.

Identifiers are derived deterministically from source snapshot, template, Opportunity and capability references. Random UUID generation is not used inside Candidate Generation.

## Initial implementation boundary

The first Candidate Engine slice implements:

1. atomic input validation;
2. deterministic baseline-path generation;
3. PV-first storage charging where all required facts are explicit;
4. explainable exclusions for unsupported or incomplete templates;
5. immutable `CandidateSet` output containing Candidates, Energy Paths and exclusions.

Cost-first charging and high-value discharge remain excluded until the required energy-target, projected-state and power-allocation contracts are implemented.

## Relationship to existing ADRs

- ADR-001: only logical capabilities enter the Planner;
- ADR-015: Path Segments use generic Execution Primitives;
- ADR-017: Candidates are complete paths over the full horizon;
- ADR-023: Opportunities remain objective and do not prescribe actions;
- ADR-024: Candidate Generation uses hard reduction and controlled branching;
- ADR-025: strategy guides families without overriding hard constraints;
- ADR-029: hard phase capacity limits remain mandatory;
- ADR-030: Capability Snapshots, Energy Paths and Candidate Sets are immutable and traceable.

## Consequences

- Opportunity-to-action policy is no longer hidden in code.
- The Candidate Engine can generate its first meaningful path without pretending every Opportunity is executable.
- Logical capability roles become explicit and vendor-independent.
- Missing power, SoC or reserve information results in exclusions rather than invented behaviour.
- Later scenario templates can extend the same contract without creating another planner layer.

## Core principle

> An Opportunity is evidence, not an instruction. The Candidate Engine applies accepted scenario templates to explicit logical capability roles and constructs only complete, technically supported and explainable Energy Paths.
