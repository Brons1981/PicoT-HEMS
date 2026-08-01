# ADR-030 — Energy Path and Capability Snapshot Contract

**Status:** Accepted  
**Date:** 2026-08-01

## Context

ADR-017 and ADR-024 require the Candidate Engine to build a small set of complete household energy paths over the planning horizon. ADR-015 requires vendor-independent Execution Primitives, and ADR-016 defines the structure of a later immutable Execution Plan.

The current architecture does not yet define the runtime domain contract that connects these decisions:

- what a complete candidate energy path contains before Evaluation;
- which logical device capabilities the Candidate Engine may use;
- how capability availability, limits, health, freshness and mapping versions remain traceable;
- how path segments remain distinct from committed Execution Plan segments.

Without this contract, implementing the Candidate Engine would require design decisions inside the code.

## Decision

PicoT introduces two immutable planning-domain contracts:

1. `CapabilitySnapshotSet`, containing the logical capabilities available to one Planning Input Snapshot;
2. `EnergyPath`, containing one complete possible household energy scenario over the planning horizon.

Both contracts are vendor-independent, versioned and fully traceable to the Planning Input Snapshot.

## Capability Snapshot Set

A `CapabilitySnapshotSet` is an immutable, atomic view of the logical controllable capabilities available to the Planner at the moment a Planning Input Snapshot is created.

It contains at least:

- snapshot identifier;
- capability mapping version;
- capture time;
- ordered logical capability snapshots.

Each `LogicalCapabilitySnapshot` contains at least:

- capability identifier;
- logical device or execution-scope identifier;
- supported Execution Primitives;
- availability state;
- health state;
- freshness timestamp;
- confidence;
- minimum and maximum supported power where applicable;
- supported energy-flow directions;
- supported SoC constraints where applicable;
- phase association where known;
- source mapping reference;
- adapter contract version.

The Candidate Engine consumes only these logical snapshots. It never consumes vendor entity IDs, integration modes or vendor-specific command names.

## Capability states

Availability and health are separate facts.

Initial availability states:

- `AVAILABLE`
- `TEMPORARILY_UNAVAILABLE`
- `UNAVAILABLE`
- `UNKNOWN`

Initial health states:

- `HEALTHY`
- `DEGRADED`
- `INVALID`
- `UNKNOWN`

Temporary unavailability does not automatically invalidate the persistent mapping. This follows ADR-004 and ADR-005.

A capability may be used for Candidate Generation only when its current state and the relevant hard constraints permit it. Rejected use remains explainable.

## Capability limits

Capability limits describe what the logical device can support, not what the Planner should choose.

Where applicable, a capability snapshot may expose:

- minimum controllable power;
- maximum controllable power;
- charge support;
- discharge support;
- bidirectional balancing support;
- minimum and maximum SoC;
- ramp or step restrictions;
- minimum on-time or off-time;
- anti-flipper or switching restrictions;
- supported phase or phases.

Unknown limits remain explicitly unknown. PicoT does not invent defaults.

## Energy Path

An `EnergyPath` is one complete possible household energy scenario for the full planning horizon. It is not a single Opportunity, device action or committed Execution Plan.

It contains at least:

- path identifier;
- Planning Input Snapshot identifier;
- Candidate Family;
- horizon start and end;
- ordered path segments;
- projected household energy states;
- referenced Opportunity and Constraint identifiers;
- referenced capability identifiers;
- strategy version;
- assumptions;
- confidence.

## Path Segment

A `PathSegment` describes planned logical behaviour for one execution scope during one time interval.

It contains at least:

- segment identifier and order;
- execution-scope identifier;
- explicit start and end time;
- one generic Execution Primitive;
- requested power where required by the primitive;
- optional SoC constraints;
- optional Energy Profile reference;
- purpose;
- evidence references;
- capability reference.

For one execution scope, path segments may not overlap. Adjacent identical segments should be merged during path construction.

A Path Segment is a candidate-planning object. It becomes an Execution Plan segment only after Evaluation, winner selection and plan construction.

## Projected Energy State

An `EnergyPath` includes ordered projected state points across the planning horizon.

A projected state point may contain, where available:

- timestamp or interval;
- projected household import and export;
- projected PV production;
- projected household demand;
- projected battery SoC;
- projected EV energy state;
- projected controllable load;
- projected conversion losses;
- projected per-phase load;
- confidence.

Unknown state dimensions remain explicitly unknown. A path is invalid when a required future state cannot be calculated with sufficient support for a hard feasibility decision.

## Candidate Set output contract

The Candidate Engine returns one immutable `CandidateSet` containing:

- the generated Candidates;
- the complete immutable Energy Paths referenced by those Candidates;
- exclusion records for rejected scenario families.

Every Candidate references exactly one Energy Path in the same Candidate Set through `energy_path_id`. Every Energy Path in the Candidate Set belongs to exactly one Candidate. Candidate and Energy Path must reference the same Planning Input Snapshot, Candidate Family, strategy version, opportunities, constraints, capabilities, assumptions and confidence.

PicoT does not introduce a separate Candidate Generation Result wrapper. The Candidate Set itself is the complete output contract of the Candidate Engine.

## Candidate Engine use

The Candidate Engine:

- receives one Planning Input Snapshot;
- receives the matching Opportunity Set;
- receives the matching Capability Snapshot Set;
- builds complete Energy Paths using meaningful Opportunity Windows and supported capabilities;
- rejects objectively impossible paths before Candidate creation;
- records exclusion reasons;
- preserves a small, diverse set of valid alternatives.

The Candidate Engine does not:

- select the winner;
- assign evaluation scores;
- translate primitives into vendor commands;
- create or commit an Execution Plan;
- silently assume missing capability limits or energy profiles.

## Traceability

Every Energy Path and resulting Candidate references:

- Planning Input Snapshot ID;
- strategy version;
- capability mapping version;
- logical capability IDs;
- Opportunity and Constraint IDs;
- assumptions and confidence.

Every rejected path family records the objective exclusion reason and relevant source references.

## Relationship to existing ADRs

- ADR-001: the Planner consumes logical capabilities only;
- ADR-004 and ADR-005: persistent mappings and temporary unavailability remain distinct;
- ADR-010: decisions reference mapping versions;
- ADR-015: Path Segments use generic Execution Primitives;
- ADR-016: the winning Energy Path is later converted into an immutable Execution Plan;
- ADR-017: Energy Paths span the full rolling planning horizon;
- ADR-019: Energy Profiles may support expected energy impact;
- ADR-024: the Candidate Engine builds a small, diverse and meaningful Candidate Set;
- ADR-027: committed execution and dynamic power allocation remain separate from candidate generation;
- ADR-029: projected per-phase load must respect hard household capacity limits.

## Consequences

- The Candidate Engine can be implemented without vendor-specific knowledge.
- Complete paths can be validated and simulated before Evaluation.
- Capability health, limits, freshness and mapping versions remain explainable.
- Candidate paths remain distinct from committed Execution Plans.
- Candidate Engine output remains one coherent immutable aggregate without an extra wrapper layer.
- Missing capability information causes explicit exclusion or reduced confidence rather than invented defaults.

## Core principle

> The Candidate Engine builds complete, vendor-independent Energy Paths from an atomic Capability Snapshot Set. The Candidate Set contains both the Candidates and their complete Energy Paths. Capabilities define what is technically supported; Energy Paths describe complete possible household scenarios; Evaluation chooses the winner; Execution commits and translates it.
