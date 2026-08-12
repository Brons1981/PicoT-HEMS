# ADR-037 — Household Energy Requirement, Storage Reserve and Grid Use Contract

**Status:** Proposed  
**Date:** 2026-08-12

## Context

PicoT is a household energy management system. Battery charging is an instrument of household optimisation, not an isolated objective.

The Price Driven path can identify economically relevant price opportunities, but a cheap price window alone is not sufficient evidence that the battery should charge. Before cost-first storage Candidates can be constructed, PicoT needs an explicit and deterministic contract for expected household demand, projected household energy balance, required storage energy and reserve, historical-load confidence, grid-supported charging permission, and battery target SoC.

ADR-031 deliberately prevents cost-first charging Candidates while these contracts are absent. This ADR proposes those missing contracts without changing ADR-031 itself.

## Responsibility

This ADR has one architectural responsibility:

> Determine how much future household/storage energy is required, by when it is required, and under which conditions grid energy may be used as a source to satisfy that requirement.

Candidate Generation remains responsible for constructing complete Energy Paths. Evaluation remains responsible for selecting a winner according to the active Planner Strategy. Execution remains responsible for executing the selected path.

## Decision

PicoT plans the complete household energy path.

Unnecessary household dependency on grid energy is an outcome PicoT seeks to reduce within the active Planner Strategy. Grid use does not override the User Objectives or their priority defined by ADR-025. When grid energy remains necessary or is economically justified within that strategy, PicoT plans that energy at the most favourable feasible time without unnecessarily blocking future PV utilisation.

Price Driven remains the strategy basis where applicable. PV is preferred over grid energy where it can reliably satisfy the projected household requirement. Grid-supported battery charging is a last-option energy source, but it is a normal and required planning capability when PV alone cannot reliably provide the desired future energy state or when shifting otherwise unavoidable grid use prevents materially less favourable later import.

## HouseholdLoadForecast

PicoT introduces a deterministic `HouseholdLoadForecast` as a Planning Input. It describes expected non-controlled baseline household demand over the rolling planning horizon.

Each forecast interval contains at least:

- interval start and end;
- `expected_energy_wh`;
- confidence;
- historical source period/reference;
- forecast method/version.

The initial nominal interval is 15 minutes. The forecast covers the same rolling horizon used by the Planner, initially 36 hours under ADR-017.

The forecast method must be deterministic, versioned and explainable. The first implementation may use a simple weighted historical profile from sufficiently comparable recent periods. Advanced learning, appliance recognition, seasonal modelling and black-box prediction are outside this ADR.

Known future energy impacts represented by Energy Profiles, Planning Hints, User Rules or explicit commitments remain separate from baseline household demand and must not be counted twice.

## Historical data is an optimisation input

Historical household load data is not a runtime dependency. A clean installation, insufficient history, corrupt history or lost history must not prevent PicoT from planning.

```text
more reliable history
→ higher HouseholdLoadForecast confidence
→ more precise reserve requirement
→ more economically refined planning

less reliable or unavailable history
→ lower confidence
→ more conservative reserve requirement
→ PicoT continues operating
```

Loss of historical data therefore degrades optimisation quality, not system availability. Fallback use must be explicit in diagnostics and explainability.

## Conservative reserve principle

PicoT uses 100% SoC, or the effective configured/technical maximum SoC when lower, as the default storage planning target.

PicoT may deliberately plan for a lower target only when sufficiently reliable evidence demonstrates that the lower energy state is adequate.

Relevant evidence includes projected household demand, known future Energy Profiles and commitments, expected PV, current battery energy/SoC, future charging opportunities, prices, technical capabilities, conversion losses, recoverability, applicable reserve or battery-health requirements, and forecast confidence.

The burden of evidence lies with planning below the effective maximum target, not with planning toward it.

Low or unavailable HouseholdLoadForecast confidence increases the required reserve. PicoT must not become passive merely because history is unavailable.

A conservative target does not mean immediate charging at any price. PicoT still considers the complete rolling horizon and may wait for expected PV or a later materially better price opportunity when the required energy state remains reliably recoverable before it is needed.

## Projected Household Energy Balance

PicoT derives future storage need from the complete projected household balance rather than from free battery capacity alone.

```text
current usable storage energy
+ expected usable PV
+ planned grid energy
- HouseholdLoadForecast
- known future demand / commitments
- conversion losses
± other planned household energy flows
= projected storage energy over time
```

The projection preserves confidence and evidence references. Free battery capacity is never, by itself, evidence that grid charging is required.

## StorageEnergyRequirement

PicoT introduces a `StorageEnergyRequirement` representing the stored energy that must be available by a future time to support the projected household path and applicable reserve policy.

It contains at least:

- required energy or equivalent required SoC;
- `required_by` time;
- reason/category;
- confidence;
- evidence references;
- reserve contribution where applicable.

A `StorageEnergyRequirement` is not a charging command and is not equivalent to a grid-charging requirement. It states what future stored energy is required. Candidate Generation determines which feasible Energy Paths could satisfy it.

## PV-first feasibility

For each relevant requirement, PicoT first evaluates whether the required future storage state is reliably reachable using the current storage state and expected PV within the complete household path.

If PV-only remains sufficient and recoverable, grid-supported charging is not required merely because a cheap price Opportunity exists.

If updated reality or forecasts show that PV-only is no longer sufficient, the normal event-driven replanning contract applies. Existing PV-deviation monitoring and material-change replanning remain the source of this trigger; this ADR introduces no duplicate PV-monitoring mechanism.

## Grid-supported charging

When PV alone cannot reliably satisfy the required future storage state, Candidate Generation may construct household Energy Paths using grid-supported battery charging.

Grid charging is an energy-source option inside a complete Candidate, not an independent strategy and not a reaction to price alone.

The Candidate Engine considers meaningful complete alternatives using canonical price Opportunities. It does not select the winning price window. Candidate Evaluation compares valid complete paths according to the active Planner Strategy.

Evaluation concerns the complete household outcome, including where available total grid import, grid import cost, PV utilisation/self-consumption, export consequences, storage losses, recoverability, confidence, switching/wear implications and technical feasibility. The active Planner Strategy remains authoritative for how these outcomes are compared.

PicoT avoids unnecessary fragmented charging throughout the day. Candidate Generation constructs a limited set of meaningful charging paths around materially relevant opportunities rather than continuously chasing marginal price differences.

## ChargeSourcePolicy

`CHARGE_AT_POWER` remains the vendor-independent Execution Primitive defined by ADR-015. The primitive itself does not grant permission to import energy from the grid.

A separate generic `ChargeSourcePolicy` expresses the permitted energy sources for a charging segment. The initial required distinction is:

- PV-only charging;
- PV-preferred charging with grid supplementation explicitly allowed.

Exact enum names and schema representation remain implementation details until implementation review, but the semantic distinction is mandatory.

> Grid import must never be inferred solely from `CHARGE_AT_POWER`. Grid use is allowed only when the Winning Energy Path explicitly permits it.

Device Adapters translate the generic charging intent and source permission into supported vendor behaviour. This ADR does not define runtime completion semantics or vendor-specific execution behaviour.

## Target SoC planning boundary

The effective target/max SoC is part of the planned energy requirement and selected Energy Path. The target is the effective configured/planned maximum, not a hard-coded literal 100% value.

How runtime execution detects that a target has been reached, terminates an active charging commitment, handles device standby, or returns to balancing/NOM is owned by the existing Execution/Runtime architecture and must be verified or extended separately before implementation. This ADR does not define that runtime behaviour.

## Battery health over time

A preferred battery-health SoC must not automatically become an instantaneous hard minimum that makes lower capacity unusable.

Where a future battery-health policy requires the battery not to remain below a preferred SoC for an excessive duration, it should create a time-bound storage requirement that the Planner can satisfy at an economically appropriate opportunity before its deadline.

The exact battery-health duration and policy are outside this ADR unless already provided by an accepted user/system contract.

## Integration ownership boundary

This ADR defines PicoT Core planning independent of the current Zendure integration.

The planning contract assumes only that a Device Adapter exposes capabilities that PicoT may rely on after normal capability validation. Whether the current Zendure/@gielz integration provides exclusive and deterministic control ownership is an integration/runtime verification concern and is outside this ADR.

No third-party integration may redefine PicoT Core planning architecture. If an integration cannot execute a required generic capability deterministically, that is a capability/integration limitation to resolve separately rather than a reason to weaken this planning contract.

## Candidate-generation boundary

This ADR provides planning concepts required to later enable the cost-first storage scenarios deliberately excluded by ADR-031. It does not authorize bypassing the existing Candidate pipeline.

```text
Planning Input Set
  └─ includes HouseholdLoadForecast and its confidence
→ Opportunity Engine
→ canonical Opportunities
→ projected household energy balance
→ StorageEnergyRequirement
→ PV-only feasibility / recoverability
→ meaningful complete Candidate Energy Paths
→ simulation/outcomes
→ Candidate Evaluation under active Planner Strategy
→ selected Planner Decision
→ Execution Plan
```

An Opportunity remains evidence, not a command. A `StorageEnergyRequirement` remains a requirement, not a command. Candidate Generation constructs alternatives; Evaluation selects the winner.

## Explainability and diagnostics

A decision involving storage reserve or grid-supported charging exposes at least:

- effective target SoC and why it was selected;
- whether effective maximum or a lower target was planned;
- HouseholdLoadForecast confidence;
- whether historical fallback/conservative reserve was active;
- projected household demand used;
- expected PV used;
- relevant price Opportunities;
- StorageEnergyRequirement and deadline;
- whether grid supplementation was permitted;
- why waiting for PV or another charging window was or was not recoverable;
- why the winning complete path was preferred over the closest alternatives under the active Planner Strategy.

If history is missing, corrupt or unavailable, diagnostics state this explicitly together with the conservative fallback used.

## Non-goals

This ADR does not define:

- a machine-learning or AI load forecaster;
- appliance recognition;
- a complete self-learning Energy Profile engine;
- Zendure-specific mode names or commands;
- runtime target-completion behaviour;
- Zendure/@gielz control ownership or a replacement execution engine;
- a new PV deviation monitor;
- Candidate ranking inside Price Driven;
- direct execution from Opportunities;
- a fixed universal household reserve percentage;
- a fixed universal battery-health duration;
- dynamic trading policy.

## Relationship to existing ADRs

- ADR-015 remains authoritative for vendor-independent Execution Primitives.
- ADR-016 remains authoritative for Execution Plan structure and runtime validation.
- ADR-017 remains authoritative for the rolling planning horizon, confidence, projected energy state and recoverability.
- ADR-019 remains authoritative for explicit Energy Profiles and Planning Hints; these remain separate from baseline household load.
- ADR-023 remains authoritative for Opportunity Engine input/output boundaries; `HouseholdLoadForecast` is a Planning Input available before Opportunity Detection.
- ADR-024 remains authoritative for complete Candidate generation.
- ADR-025 remains authoritative for Planner Strategy and User Objective priority; grid dependency is not a hidden overriding objective.
- ADR-026 / ADR-032 remain authoritative for winner selection and evaluation.
- ADR-031 remains unchanged and authoritative for the existing cost-first Candidate exclusion until implementation satisfies the required contracts.
- ADR-034 remains authoritative for material-change replanning.
- ADR-036 remains authoritative for the canonical Price Driven Opportunity path while it is developed toward acceptance.

## Consequences

Positive consequences:

- PicoT remains operational on a clean installation without historical household data.
- Loss of history degrades economic refinement rather than stopping planning.
- More reliable history naturally improves economic precision.
- PV remains preferred without making grid charging impossible when genuinely needed.
- The battery is not optimised independently from the household.
- Grid charging cannot be accidentally implied by a generic charge-power command.
- Price Opportunities remain evidence rather than commands.
- Planner Strategy remains authoritative for the final trade-off between financial result, self-consumption, reserve, net balance and other User Objectives.
- The design remains vendor-independent.

Costs and risks:

- Household load forecast confidence must be implemented and calibrated deterministically.
- Conservative operation with little history may intentionally buy more energy than later refined planning would have bought.
- Projected household balance and reserve calculation add Planner complexity.
- Source-policy capability and adapter support must be verified before execution.
- Runtime target completion and integration control ownership require separate verification before relying on active grid-supported charging in production.

## Core principles

> PicoT optimises the complete household energy path, not the battery in isolation.

> Unnecessary grid dependency is reduced within the active Planner Strategy; grid use does not silently override User Objective priorities.

> Grid energy should be avoided where reliable PV and stored energy can satisfy household demand; when grid energy remains necessary, its timing and cost are optimised across the complete household path.

> PicoT plans toward the effective maximum battery SoC by default. It deliberately plans less only when sufficiently reliable evidence shows that less is enough.

> Historical load data improves optimisation but is never required for PicoT to keep planning.

> Uncertainty increases reserve; it does not disable Price Driven planning.

> Grid import is an explicit property of the Winning Energy Path and is never implied solely by `CHARGE_AT_POWER`.
