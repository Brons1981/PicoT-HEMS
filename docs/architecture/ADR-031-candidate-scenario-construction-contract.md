# ADR-031 — Candidate Scenario Construction Contract

**Status:** Accepted  
**Date:** 2026-08-01  
**Amended:** 2026-08-11 by ADR-037

## Context

ADR-023 defines objective Opportunities without selecting devices, assigning power or choosing Execution Primitives. ADR-024 requires the Candidate Engine to build a small, diverse set of complete household energy scenarios. ADR-030 defines `CapabilitySnapshotSet`, `EnergyPath` and `CandidateSet`.

A remaining contract gap prevents a correct Candidate Engine implementation:

- an Opportunity does not prescribe an Execution Primitive;
- the same Opportunity may support several valid household scenarios;
- `LogicalCapabilitySnapshot` currently describes supported primitives and limits, but not the logical energy role needed to construct meaningful paths;
- a Candidate must be a complete Energy Path over the planning horizon, not a one-to-one conversion of an Opportunity into an action.

Implementing direct Opportunity-to-Primitive mapping in code would therefore introduce architectural policy outside an ADR.

ADR-037 later refined storage control: normal household storage behaviour uses integration-managed `BALANCE_*` primitives without `requested_power_w`; PicoT may project the expected battery flow, SoC trajectory and time-to-target, but does not prescribe instantaneous watts. Explicit `CHARGE_AT_POWER` / `DISCHARGE_AT_POWER` is reserved for accepted power-controlled scenarios, initially Dynamic Trading.

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
- `UNKNOWN`

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

For storage, scenario templates must also respect ADR-037's control-intent boundary: a balance-controlled Candidate may project expected battery power for feasibility without attaching a commanded wattage.

## Initial scenario templates

### PV-first storage charging

Applicable Opportunity:

- `PV_SURPLUS_WINDOW`

Required capability:

- role `ENERGY_STORAGE`;
- availability `AVAILABLE`;
- health `HEALTHY`;
- at least one accepted charge-capable balance primitive, normally `BALANCE_BIDIRECTIONAL` or `BALANCE_CHARGE_ONLY`;
- known charge-flow support and the technical limits required to validate the selected balance behaviour.

Construction:

- Candidate Family `PV_FIRST`;
- one balance-mode Path Segment within the Opportunity window;
- no `requested_power_w` is attached to the balance primitive;
- PicoT projects the expected battery charging flow from forecast PV surplus, household load, known capability limits and the assumed integration-managed NOM behaviour;
- the projected charging flow is planning evidence only and is never sent as a battery setpoint;
- projected state contains sufficient SoC points to evaluate feasibility and, where an explicit target exists, expected time-to-target;
- the path covers the full planning horizon, while only the controllable segment occupies the Opportunity window;
- confidence is bounded by the least-confident required Opportunity, capability and forecast fact.

If the required PV/load evidence or capability support is unavailable, or the required future state cannot be proven with sufficient support, the template is excluded. PicoT does not invent a battery wattage and does not fall back to `CHARGE_AT_POWER`.

### Cost-first storage charging

Applicable Opportunities:

- `NEGATIVE_PRICE_WINDOW`
- `LOWEST_PRICE_WINDOW`

Normal household cost-first charging is integration-managed.

Required capability:

- role `ENERGY_STORAGE`;
- availability `AVAILABLE`;
- health `HEALTHY`;
- an accepted charge-capable balance primitive, normally `BALANCE_BIDIRECTIONAL` or `BALANCE_CHARGE_ONLY`;
- known charge-flow support and sufficient capability/state facts for projected feasibility.

Construction:

- Candidate Family `COST_FIRST`;
- the Opportunity remains evidence for timing, not a command;
- the Candidate uses a supported `BALANCE_*` primitive without `requested_power_w`;
- PicoT projects expected battery energy flow, SoC trajectory and expected time-to-target from forecast household balance under the assumed integration-managed NOM behaviour;
- a cheap or negative price window never creates its own target SoC or energy requirement;
- multiple relevant price Opportunities may produce distinct Candidates and are not ranked or collapsed by Candidate Generation.

If an applicable hard future SoC state or other feasibility requirement cannot be proven under the selected balance control, the Candidate is excluded. PicoT may not convert the Candidate to `CHARGE_AT_POWER` as a fallback.

A separately accepted Dynamic Trading scenario is different: under ADR-037 it may use `CHARGE_AT_POWER` according to the explicit trading-power policy because deliberate grid import/export is itself the trading action.

### High-value storage discharge

Applicable Opportunity:

- `HIGH_EXPORT_VALUE_WINDOW`

Normal household discharge remains integration-managed where the accepted scenario is not Dynamic Trading.

Required capability:

- role `ENERGY_STORAGE`;
- availability `AVAILABLE`;
- health `HEALTHY`;
- an accepted discharge-capable balance primitive, normally `BALANCE_BIDIRECTIONAL` or `BALANCE_DISCHARGE_ONLY`;
- known discharge-flow support and sufficient projected-state support.

Construction requires explicit projected SoC, reserve requirements, household demand and a complete feasible recovery path where discretionary discharge is involved. The Candidate may project expected integration-managed discharge flow, but does not attach `requested_power_w` to a balance primitive.

Deliberate export trading is the explicit exception: an accepted Dynamic Trading Candidate may use `DISCHARGE_AT_POWER` under ADR-037's trading-power policy, but only when full-horizon feasibility, reserve and recovery requirements are satisfied.

Without sufficient projected-state, recovery or economic-cycle support, no discretionary discharge Candidate is created.

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

For `BALANCE_*` storage segments, projected battery power or energy is an expected planning flow and must remain distinguishable from a commanded setpoint.

## Matching and atomicity

Before generation, the Candidate Engine rejects mismatched inputs when:

- snapshot IDs differ;
- capability mapping versions differ;
- strategy versions differ;
- capture chronology is inconsistent.

No partial Candidate Set is returned for mismatched atomic inputs.

## Exclusions

Rejected templates produce immutable `CandidateExclusion` records. Reasons remain explicit in the exclusion text and source references include relevant Opportunity and capability IDs where available.

For storage, missing forecast/state evidence or inability to prove a required future SoC state is an exclusion reason; it never authorises hidden explicit-power control.

## Determinism

For identical immutable inputs and the same implementation version, Candidate Generation produces identical scenario families, Energy Paths, Candidates, exclusions, ordering and identifiers. Random UUID generation is not used.

## Initial implementation boundary

The first Candidate Engine slice implements:

1. atomic input validation;
2. deterministic baseline-path generation;
3. PV-first storage charging where all required facts are explicit;
4. explainable exclusions for unsupported or incomplete templates;
5. immutable `CandidateSet` output containing Candidates, Energy Paths and exclusions.

The storage extension defined by ADR-037 then adds integration-managed balance candidates with projected NOM energy flow, SoC trajectory and expected time-to-target. Explicit-power storage paths remain limited to accepted power-controlled scenarios, initially Dynamic Trading.

## Relationship to ADR-037

ADR-037 is authoritative for storage control intent and power ownership. Where earlier wording in this ADR implied that normal PV-first, cost-first or high-value storage behaviour universally requires `CHARGE_AT_POWER` or `DISCHARGE_AT_POWER`, ADR-037 supersedes that implication.

## Core principle

> An Opportunity is evidence, not an instruction. The Candidate Engine applies accepted scenario templates to explicit logical capability roles and constructs only complete, technically supported and explainable Energy Paths. For normal storage control, PicoT may project expected NOM battery flow for feasibility, but the integration controls instantaneous watts.