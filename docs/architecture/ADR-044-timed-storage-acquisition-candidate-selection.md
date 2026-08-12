# ADR-044 — Timed Storage Acquisition Candidate Selection

**Status:** Accepted  
**Date:** 2026-08-12

## Context

ADR-036 defines broad price Opportunities. ADR-037 defines the canonical household-energy planning chain. ADR-043 separates storage protection semantics from additional energy-acquisition urgency.

Live validation exposed the next missing contract: a `LOWEST_PRICE_WINDOW` may span several quarter-hour price intervals, but that Opportunity is evidence only. It is not an execution window and it must not directly select NOM, charging or discharge modes.

The current runtime also has an architectural split that must be removed before timed selection can be trusted:

- Price Driven v2 builds a price-only `PlanningInputSnapshot` containing the normalized energy-price `ForecastSeries` and detects canonical price Opportunities from that snapshot.
- The live ADR-037 `PlanningInputSnapshot` contains storage, PV and household-load evidence but currently uses an empty `ForecastSet` for price evidence.
- Live ADR-037 then rebinds serialized price Opportunities from `planner_context` onto the live snapshot.

That bridge preserves opportunity facts, but Candidate Generation cannot trace a selected quarter-hour back to the original price point in the same atomic Planning Input Snapshot. A timed candidate therefore cannot be implemented correctly by reading only the broad Opportunity window or by adding another runtime heuristic.

PicoT must first make the live Planning Input Snapshot the single canonical evidence source for price, PV, load and storage. Candidate Generation may then select actual intervals from that evidence.

## Decision

PicoT introduces one canonical **timed storage-acquisition candidate** contract.

The implementation MUST remain inside the accepted planner pipeline:

```text
Planning Input Snapshot
  - current storage state
  - PV energy timeline
  - household-load forecast
  - energy-price ForecastSeries
→ Opportunity Detection
→ projected household energy balance
→ StorageEnergyRequirement
→ PV-only feasibility / technical recoverability
→ Candidate Generation
   - timed storage-acquisition candidate
→ Candidate Outcomes / Simulation
→ Evaluation
→ Execution
```

No runtime, dashboard, vendor adapter or legacy Price Driven strategy may select charge intervals independently.

## One atomic live Planning Input Snapshot

The live Planning Input Snapshot MUST include the authoritative normalized `ForecastSeries(kind=ENERGY_PRICE)` used for that Planner Run.

Price Opportunities used by ADR-037 MUST be detected from that same snapshot by the canonical Opportunity Engine.

The live planner MUST NOT depend on serialized/rebound Opportunities from another price-only snapshot as a decision source once this migration is complete.

Diagnostic serialization may remain for observability, but it is not planner evidence.

This removes the current split between:

- a price-only canonical snapshot; and
- a storage/PV/load live snapshot.

There is one Planner Run and one evidence graph.

## Opportunity semantics

A `LOWEST_PRICE_WINDOW` or `NEGATIVE_PRICE_WINDOW` defines an eligible **search region**, not a selected action window.

Candidate Generation resolves the Opportunity evidence references back to the exact energy-price `ForecastPoint` records in the same Planning Input Snapshot.

The original source intervals remain atomic. PicoT does not manufacture new price values by averaging or interpolating between intervals merely to make a candidate fit.

## Timed acquisition inputs

A timed storage-acquisition candidate may be generated only when all required canonical inputs are available atomically:

- `PlanningInputSnapshot` with energy-price forecast;
- canonical price `Opportunity` and its immutable evidence references;
- canonical `ProjectedHouseholdEnergyBalance`;
- `StorageEnergyRequirement` from ADR-043;
- `PVOnlyStorageEnergyFeasibility`;
- `StorageTechnicalRecoverability`;
- `CurrentStorageState`;
- `EffectiveStorageLimit`;
- current storage charging capability, including maximum charge power;
- source policy permitting grid support.

If any dependent input is unavailable or inconsistent, the timed candidate is excluded explicitly. PicoT does not fall back to a legacy selector.

## Eligible price intervals

For one storage-acquisition candidate, an energy-price point is eligible only when:

1. it is referenced by the relevant price Opportunity evidence;
2. it belongs to the authoritative `ENERGY_PRICE` forecast in the same snapshot;
3. its interval is not completed at `snapshot.captured_at`;
4. its usable portion ends no later than `requirement.protection_starts_at`;
5. charging during the interval is supported by the current storage capability;
6. the source policy explicitly permits the required source.

Intervals after `protection_starts_at` cannot satisfy that requirement and are not eligible for that candidate.

## Required energy is simulation-derived

`StorageTechnicalRecoverability.extra_energy_required_wh` MUST NOT be copied directly into a price-window charge schedule as though it were the exact grid-energy target.

That value compares the current stored energy with the protected target and is useful for acquisition urgency and physical recoverability. Expected PV and household load can still change the amount that actually needs grid-supported acquisition before protection starts.

The timed candidate therefore determines its scheduled acquisition by replaying the canonical projected household energy path with the proposed charge intervals applied.

The simulation MUST:

- start from the canonical current stored energy;
- use the same PV and household-load energy deltas represented by the canonical projected balance;
- enforce the effective storage ceiling so PV or planned charging that would exceed storage capacity is not reusable later;
- enforce the current maximum charge power and interval duration;
- prevent stored energy from falling below the canonical lower physical boundary;
- reach at least `required_energy_wh` at `protection_starts_at`;
- preserve the protected path through the requirement interval according to the candidate-outcome simulation contract.

A candidate that cannot satisfy those constraints is invalid/excluded.

## Price resolution versus energy-balance resolution

Price intervals and PV/load intervals may have different native boundaries.

PicoT MUST NOT create a second household-balance model inside Candidate Generation to compensate for that difference.

If the canonical projected balance cannot yet represent the temporal resolution needed to prove feasibility of a selected price interval, Candidate Generation fails closed for that timed selection until the canonical balance/timeline contract is extended.

Any future temporal normalization belongs in the canonical planning-input / projected-balance layer and is then consumed by Candidate Generation. It is not implemented as a private resampler in the price selector.

## Deterministic interval selection

Among feasible interval allocations, Candidate Generation chooses the economically best allocation deterministically.

For the first accepted implementation, ranking is lexicographic:

1. **feasibility first** — the storage requirement and physical limits must be satisfied;
2. **lowest total forecast acquisition cost** — sum of scheduled grid-supported energy per interval multiplied by that interval's forecast price;
3. **least scheduled grid-supported energy** when total cost ties;
4. **fewest charge-state transitions / contiguous blocks** when cost and energy tie;
5. **latest feasible start** when the previous criteria tie, avoiding unnecessarily early acquisition while preserving recoverability;
6. stable timestamp/ID ordering as the final deterministic tie-break.

This is not a rule that says “always wait for the absolute cheapest quarter”. Earlier energy is selected when it is required to remain physically feasible.

Negative-price intervals naturally rank economically ahead of positive-price intervals through the same cost function; they do not require a separate hidden mode-selection path.

## Partial final interval

If the remaining required acquisition is smaller than the energy that can be delivered during one full source interval, the candidate may request lower power for that interval, subject to the capability's minimum power and power-step constraints.

PicoT does not extend the selected window merely to force full-power charging when a lower valid power can satisfy the requirement more precisely.

## Adjacent intervals and execution segments

Selection happens at source-interval granularity.

Adjacent selected intervals with the same execution primitive, source policy and requested power may be merged into one `PathSegment` for execution efficiency.

Non-adjacent selected intervals remain separate segments. Candidate Generation does not bridge a more expensive unselected interval merely to make a visually continuous window.

The preference for fewer transitions is a tie-break after economic cost and feasibility; it is not permission to buy materially more expensive energy.

## PV-first semantics

Expected PV remains part of the canonical no-grid projected balance and therefore reduces or can eliminate grid-supported acquisition need.

A broad cheap-price Opportunity does not create a grid-charging candidate when the simulated PV/current-storage path already satisfies the requirement.

If future PV is expected but uncertain, confidence/reserve policy remains the accepted ADR-037 mechanism. Timed selection does not invent a separate PV-risk factor.

## Conversion losses

Candidate Generation MUST NOT invent its own round-trip or charge-efficiency constant.

The canonical projected household balance already exposes whether conversion losses are applied. When an accepted canonical conversion-loss input exists, timed candidate simulation consumes that same model.

Until then, the selector uses the same energy-accounting semantics as the canonical balance and exposes `conversion_losses_applied` in candidate evidence/diagnostics. There is no private efficiency workaround.

## Candidate identity and evidence

A timed storage-acquisition Energy Path records at minimum:

- relevant Opportunity ID;
- requirement ID;
- projected-balance ID;
- price forecast ID and exact selected point indexes;
- storage capability ID;
- source policy;
- selected interval start/end;
- requested power and scheduled energy per interval;
- total scheduled grid-supported energy;
- projected acquisition cost;
- protection start and protected-through timestamps;
- confidence/evidence references;
- method/version identifier.

A dashboard may visualize the broad Opportunity and selected timed intervals separately, but it must not derive the selection itself.

## Evaluation boundary

Candidate Generation constructs one or more feasible timed Energy Paths. Candidate Outcomes/Simulation establishes the projected consequences. Evaluation chooses the winner.

Opportunity Detection does not choose the winner.

The live runtime does not choose the winner.

Execution only translates the already-selected winning Energy Path into supported execution primitives.

## Fail-closed behaviour

Timed candidate generation fails closed when, for example:

- authoritative price forecast is missing from the snapshot;
- Opportunity evidence cannot resolve to forecast points;
- price and planning intervals cannot be reconciled by the accepted canonical timeline;
- storage state or limits are unavailable;
- the protected requirement cannot be met before `protection_starts_at`;
- charge power/capability is insufficient;
- source policy does not permit grid support;
- candidate simulation cannot prove the protected path.

There is no fallback to Price Driven v1, a 24-block selector, `price_entry_best_later_*`, or a runtime “best quarter” heuristic.

## Migration sequence

Implementation proceeds in this order:

1. wire the normalized energy-price `ForecastSeries` into the live atomic `PlanningInputSnapshot`;
2. detect live price Opportunities directly from that snapshot;
3. retire the rebound `planner_context` Opportunity bridge as a planner decision source;
4. make projected balance available atomically to Candidate Generation for timed feasibility;
5. implement timed interval allocation and deterministic ranking;
6. add candidate-outcome simulation and acceptance tests;
7. expose separate diagnostics for `price_opportunity` and `selected_acquisition_intervals`;
8. only after live dry-run evidence is stable may the winning timed Energy Path become executable.

Each step modifies the canonical path. No temporary parallel planner path is introduced.

## Acceptance tests

At minimum the implementation must prove:

1. a broad four-hour low-price Opportunity with only one hour of required acquisition selects only the economically best feasible source intervals, not all four hours;
2. a cheaper later interval is rejected when waiting would violate physical recoverability;
3. expected PV reduces the scheduled grid-supported energy;
4. PV/current storage sufficient for the requirement creates no grid-supported timed candidate;
5. storage headroom prevents energy that would overflow the battery from being counted later;
6. a partial final interval uses valid reduced power when supported;
7. equal-cost solutions prefer fewer switching blocks;
8. price Opportunity and selected execution intervals remain separate in diagnostics;
9. missing price forecast or unresolved evidence fails closed;
10. no legacy Price Driven v1/24-block mode-selection or runtime best-quarter path participates.

## Consequences

Positive consequences:

- the chart can show a broad price Opportunity and a narrower actual selected acquisition window honestly;
- quarter-hour selection becomes traceable to exact forecast points;
- PV, household demand, storage requirement and price participate in one Planner Run;
- price evidence can no longer choose a vendor mode directly;
- the current price-only/live-snapshot split is removed;
- future execution remains explainable from one canonical Energy Path.

Costs:

- the live snapshot assembly must absorb price evidence;
- the current live `planner_context` Opportunity rebinding must be retired as a decision source;
- Candidate Generation requires richer simulation inputs;
- temporal resolution may need a canonical balance extension if live PV/load intervals do not align sufficiently with price intervals.

## Relationship to prior ADRs

- ADR-017 remains the authoritative Planning Decision Pipeline.
- ADR-023 remains authoritative that Opportunities are evidence, not actions.
- ADR-024/ADR-031 remain authoritative for Candidate construction boundaries.
- ADR-036 remains authoritative for price Opportunity detection.
- ADR-037 remains authoritative for household-energy/storage planning.
- ADR-043 remains authoritative for storage protection and acquisition-time semantics.

ADR-044 adds only the missing timed storage-acquisition candidate-selection contract and the required live price-evidence unification.