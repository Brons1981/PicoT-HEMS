# V2ADR-050 — Timed Delegated Storage Control

Status: **Accepted for PicoT v2 rebuild**

## Context

ADR-001 through ADR-039 establish that PicoT plans complete household Energy Paths, selects one Winning Candidate through Evaluation, and expresses execution through vendor-independent Execution Primitives. ADR-015 distinguishes balance primitives from explicit-power primitives, while ADR-037 determines how much stored energy is required, by when, and whether grid energy may be used.

The remaining gap is the construction of a timed storage-acquisition path when a Device Adapter can delegate instantaneous power control to an integration. For example, a storage system may expose a bidirectional net-balancing mode or a charge-only balancing mode. PicoT must be able to plan when such behaviour is useful without pretending that it selected a fixed power which the integration actually controls dynamically.

The gap is visible in the current observer-only `StorageEnergySourceNeed`: it can describe missing energy and PV/grid feasibility, but it does not yet create time-bound alternative Energy Paths. It can also overstate a PV contribution unless that contribution is bounded by the energy still needed at the target.

Zendure and `@gielz` mode names are adapter concerns. Core may not plan literal vendor modes such as `Nul op de meter`, `Slim ontladen` or `Stand-by`.

## Decision

PicoT v2 constructs a bounded set of complete, timed household Energy Paths for a storage-energy requirement. A path may use either delegated balance control or explicit-power control, but the two control forms remain semantically distinct.

The Candidate Engine constructs alternatives. The Evaluation Engine alone selects the winner. No Opportunity, energy-need record, dashboard projection or Device Adapter selects the winning time window.

## Generic control forms

PicoT Core uses only the generic Execution Primitives accepted by ADR-015.

### Delegated balance control

The initial delegated primitives are:

- `BALANCE_BIDIRECTIONAL`;
- `BALANCE_CHARGE_ONLY`;
- `BALANCE_DISCHARGE_ONLY` where a discharge purpose requires it;
- `STANDBY` or a baseline path where no active storage behaviour is selected.

A delegated balance segment contains no `requested_power_w`. Instantaneous power is determined by the validated Device Adapter/integration control chain within its capability and safety limits.

The Candidate simulation still projects the expected interval energy effect. That projection is planning evidence, not a fixed-power command. It is derived from the same canonical PV, household-load, storage-state, capability, confidence and source-policy evidence as the complete Energy Path.

### Explicit-power control

`CHARGE_AT_POWER` and `DISCHARGE_AT_POWER` retain their ADR-015 meaning. A segment using either primitive contains an explicit requested power and may only be constructed when the atomic Capability Snapshot proves the primitive and its required limits.

PicoT never invents a power limit. A missing or stale limit excludes the explicit-power alternative; it does not produce a default such as `2400 W`.

Delegated balance capability does not imply explicit-power capability, and explicit-power capability does not imply delegated balance capability.

## Adapter translation boundary

Vendor presentation and command mapping remain outside Core. For a validated Zendure adapter, an example mapping may be:

```text
BALANCE_BIDIRECTIONAL → Nul op de meter
BALANCE_CHARGE_ONLY   → charge-only balancing mode
BALANCE_DISCHARGE_ONLY → Slim ontladen
STANDBY               → Stand-by
CHARGE_AT_POWER       → explicit vendor charge-power command
```

These names are examples, not Core values and not proof of live capability. Every mapping requires an explicit, versioned Capability Snapshot and the adapter validation required by ADR-035 before execution authority is granted.

In particular, `BALANCE_BIDIRECTIONAL` is not synonymous with charging: it may charge during surplus and discharge during deficit. Candidate Generation must therefore not assume that bidirectional balancing is always the best way to acquire energy.

## Timed Candidate construction

For each relevant `StorageEnergyRequirement`, Candidate Generation considers a small, deterministic set of meaningful complete alternatives within the rolling horizon. Subject to available capabilities and evidence, these include:

- the baseline path;
- PV-surplus acquisition through delegated `BALANCE_CHARGE_ONLY`;
- PV-surplus balancing through delegated `BALANCE_BIDIRECTIONAL` when its possible discharge effect is included;
- explicit PV-only charging through `CHARGE_AT_POWER` where the capability and source control are proven;
- explicit grid-supported charging where ADR-037 permits grid supplementation and the capability and source control are proven;
- waiting for a later recoverable PV or price window.

An unavailable capability excludes only the affected alternative. Candidate Generation does not replace it silently with a different primitive.

Each controllable alternative contains explicit start and end times aligned to canonical planning intervals. Its timing comes from the complete combination of:

- requirement energy and deadline;
- current usable storage energy;
- canonical PV forecast basis and confidence;
- projected household load and confidence;
- canonical Price Opportunities;
- permitted charge sources;
- capability availability and limits;
- conversion losses;
- reserve, recoverability and applicable User Objectives;
- existing commitments and expected switching.

A cheap price window is evidence for a Candidate, never a direct reason to activate a mode. A PV-surplus window is likewise evidence, not a command.

## Energy accounting

For one storage requirement, projected source contributions are bounded by the energy still needed at the effective target.

```text
energy_to_target_wh = max(0, target_energy_wh - current_usable_energy_wh)

pv_storage_contribution_wh = min(
    energy_to_target_wh,
    reliably_usable_pv_surplus_for_storage_wh
)

remaining_energy_wh = max(
    0,
    energy_to_target_wh - pv_storage_contribution_wh
)
```

Grid contribution may be projected only when the Candidate explicitly permits grid supplementation under ADR-037. Total projected storage acquisition may not exceed the energy needed at the target after conversion losses and other explicitly modelled constraints.

PV energy remaining after the storage target is satisfied remains available to the rest of the complete household path; it is not attributed to storage.

## Source-policy separation

The permitted energy source and the selected Execution Primitive are separate properties.

- A PV-only path may not silently import grid energy.
- A grid-supported path must state that grid supplementation is allowed and why it is justified under ADR-037.
- A delegated balance mode is eligible for a source policy only when the validated adapter/integration behaviour can enforce or reliably preserve that policy.
- If the integration cannot distinguish PV-only from grid-supported behaviour, PicoT must mark the affected Candidate infeasible or unavailable rather than infer compliance.

## Candidate outcomes and Evaluation

Every timed alternative is simulated as a complete household Energy Path. Its immutable outcome exposes at least:

- storage energy at the requirement deadline;
- PV energy attributed to storage, bounded by energy need;
- grid energy attributed to storage;
- total household grid import and cost;
- PV self-consumption and export consequence;
- storage conversion loss;
- reserve satisfaction;
- possible discharge caused by bidirectional balancing;
- confidence and its evidence;
- recoverability;
- execution complexity and expected switching;
- capability and mapping references.

Low or fallback confidence remains explicit. A value of `0` must not be described as certainty, and `pv_only_feasible` must not hide the confidence or recoverability assumptions on which feasibility depends.

Evaluation compares these complete outcomes according to ADR-025, ADR-026 and ADR-032. It does not prefer delegated control, explicit power, PV, grid or a particular time window through an unrecorded rule.

## Execution boundary

The Winning Energy Path converts unchanged into scope-specific Execution Plans under ADR-033. A delegated Path Segment becomes a delegated Execution Plan Segment without requested power. An explicit-power Path Segment preserves its requested power exactly.

Observer-only Candidate construction and Evaluation may be implemented before live dispatch support. Actual execution of a delegated balance segment is prohibited until all of the following are proven:

- the primitive is present and healthy in the atomic Capability Snapshot;
- the adapter mapping and service call are explicit and versioned;
- dispatch is idempotent and acknowledgement/observation semantics are defined;
- current-state validation and hard safety constraints pass;
- source-policy behaviour is compatible with the selected path;
- a confirmed manual user action is not silently overwritten;
- fallback and reset behaviour are explicitly validated.

ADR-035 currently proves only its accepted initial adapter scope. This V2ADR does not silently expand live adapter authority; balance-mode dispatch requires a separate test-backed adapter extension.

## Explainability

PicoT must be able to explain the selected result in ordinary language without recalculating it in the dashboard. For example:

> Zendure is 1,387 Wh below its planned target. PicoT expects 1,387 Wh of usable PV surplus for storage between 12:00 and 14:00, so no grid charging is planned. The selected path enables delegated charge-only balancing in that window. Confidence is low because household load currently uses a fallback forecast.

The underlying projection exposes at least:

- target energy and missing energy;
- requirement deadline;
- considered time windows and alternatives;
- selected generic primitive and whether power is delegated or explicit;
- source policy;
- PV and grid contributions;
- price, PV, load and capability evidence;
- confidence and recoverability;
- the decisive Evaluation step;
- Candidate, Energy Path, Execution Plan and snapshot lineage.

Vendor mode names may be shown only as adapter translation details alongside, never instead of, the generic Core intent.

## Non-goals

This V2ADR does not:

- authorise live storage control;
- define Zendure-specific policy in Core;
- select a universal preferred vendor mode;
- introduce a default storage charge power;
- let the Opportunity Engine select times, devices or winners;
- allow the Device Adapter to replan or reinterpret the Winning Energy Path;
- define a second battery-only planning pipeline;
- override the user-override boundary from ADR-016;
- incorporate ADR-040 through ADR-047 as architectural authority.

## Relationship to the reliable architecture baseline

- ADR-001 through ADR-014 remain authoritative for capability-based, traceable and deterministic operation.
- ADR-015 remains authoritative for generic Execution Primitives and vendor translation.
- ADR-016 remains authoritative for time-bound plans, validation and manual overrides.
- ADR-017 remains authoritative for the rolling horizon, confidence and recoverability.
- ADR-023 remains authoritative for Opportunities as evidence rather than actions.
- ADR-024 and ADR-031 remain authoritative for bounded, complete Candidate construction. This V2ADR adds the missing delegated-balance timed scenario contract without changing their ownership boundaries.
- ADR-025, ADR-026 and ADR-032 remain authoritative for strategy and winner selection.
- ADR-027 and ADR-029 remain authoritative for commitments, switching and hard power constraints.
- ADR-030 remains authoritative for atomic Capability Snapshots and explicit timed Path Segments.
- ADR-033 remains authoritative for exact conversion of the Winning Energy Path.
- ADR-035 remains authoritative for the accepted Home Assistant adapter boundary; delegated balance dispatch requires an explicit extension.
- ADR-036 remains authoritative for preservation of meaningful price windows without hidden ranking.
- ADR-037 remains authoritative for energy need, PV-first feasibility and explicit grid-source permission.
- ADR-038 and ADR-039 remain authoritative for current storage state and the canonical PV energy timeline.
- V2ADR-048 remains authoritative for interval-specific PV uncertainty and whole-household forecast assumptions.
- V2ADR-049 remains authoritative for evidence-backed PV attenuation profiles.
- Historical ADR-040 through ADR-047 are not authority for this decision and are not incorporated by reference.

## Consequences

Positive:

- PicoT can plan when delegated integration behaviour should be active without claiming to control its instantaneous power;
- explicit-power and delegated-control paths remain unambiguous;
- no invented storage power limit enters planning;
- PV and grid contributions are bounded and explainable;
- a noon PV/price window can be compared with other complete household paths;
- vendor mode names remain isolated in the adapter;
- observer-only planning can mature before control authority expands.

Costs and risks:

- Candidate simulation needs a deterministic energy-impact model for delegated modes;
- bidirectional balancing requires explicit modelling of possible discharge;
- source-policy enforcement must be proven per adapter capability;
- Candidate growth must remain bounded;
- live control requires a separate adapter-contract implementation and manual-override validation.

## Implementation order

1. Correct observer-only energy accounting by capping storage PV contribution at `energy_to_target_wh` and preserving explicit low confidence.
2. Add immutable timed delegated-control Candidate contracts and failing tests without live dispatch.
3. Construct a bounded set of complete baseline, delegated and explicit-power alternatives from canonical intervals and capabilities.
4. Simulate complete household outcomes and route winner selection only through Evaluation.
5. Project ordinary-language explanations and full lineage without dashboard recalculation.
6. Validate the required Zendure/`@gielz` capabilities and mappings in observer/dry-run mode.
7. Extend ADR-035 adapter support in a separate test-backed slice before any live authority is considered.

## Core principle

> PicoT decides the complete timed household Energy Path; a validated integration may determine instantaneous device power only inside a delegated generic primitive, while explicit-power primitives remain explicit and no adapter makes a planning decision.
