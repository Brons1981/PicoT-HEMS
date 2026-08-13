# ADR-048 — Economic Acquisition versus PV Sufficiency

**Status:** Proposed  
**Date:** 2026-08-13

## Context

ADR-044 currently requires that a broad cheap-price Opportunity does not create a grid-supported timed storage-acquisition Candidate when the simulated current-storage/PV path already satisfies the active `StorageEnergyRequirement`. Its acceptance test 4 makes this explicit.

ADR-041, accepted later, requires PicoT to compare complete Energy Paths using time-dependent storage value, future import/export prices and replacement cost. That contract explicitly allows economic comparisons where preserving storage, exporting PV now, or replacing energy later can be preferable even when the immediate requirement remains feasible without grid-supported acquisition.

Live validation on 2026-08-13 exposed the conflict. The current `CandidateEngine` follows ADR-044 and rejects `COST_FIRST` paths whenever `pv_only_feasibility.energy_sufficient` is true or `additional_acquisition_required` is false. As a result, Evaluation never receives an economically timed grid-acquisition alternative in situations where ADR-041 may require one for complete-path comparison.

Neither ADR-041 nor ADR-044 is modified by this ADR. Both remain immutable Accepted records.

## Decision

PicoT separates **requirement-driven acquisition necessity** from **economically relevant acquisition alternatives**.

`PVOnlyStorageEnergyFeasibility.energy_sufficient == true` means only that grid-supported acquisition is not required to satisfy the active StorageEnergyRequirement. It does not by itself prove that every grid-supported Energy Path is economically dominated over the complete planning horizon.

`StorageTechnicalRecoverability.additional_acquisition_required == false` has the same meaning: no additional acquisition is required for requirement feasibility. It is not a global prohibition on constructing an economic alternative.

Candidate Generation may therefore construct an economically timed storage-acquisition Candidate despite PV/current-storage sufficiency only when all of the following are true:

- an applicable `LOWEST_PRICE_WINDOW` or `NEGATIVE_PRICE_WINDOW` exists;
- complete canonical import and export settlement evidence is available for the compared horizon;
- canonical projected PV, load, storage state, storage limits and charging capability are available;
- an explicit charge-allocation target can be derived without inventing a fixed SoC target;
- the resulting Candidate remains within all hard limits and preserves every applicable StorageEnergyRequirement;
- Candidate Simulation can project the complete Energy Path;
- Candidate Outcome Production can derive `FINANCIAL_RESULT` for every compared Candidate under the same settlement evidence.

The existence of such a Candidate does not command charging. Evaluation remains solely responsible for winner selection under the active Planner Strategy.

## Allocation boundary

ADR-031 remains authoritative that Candidate Generation may not invent a charging amount. Economic acquisition therefore requires an explicit allocation basis.

An economic Candidate may acquire only energy that has a traceable role in the complete Energy Path, such as:

- replacing stored energy deliberately preserved for a higher-value later interval;
- replacing energy deliberately discharged during a higher-value interval;
- shifting an otherwise expected future import into a cheaper feasible interval;
- creating storage headroom/value trade-offs whose consequences are fully represented by Simulation and `FINANCIAL_RESULT`.

PicoT does not create a generic “fill the battery because it is cheap” Candidate and does not introduce a fixed universal target SoC.

## Relationship to ADR-044

ADR-044 remains authoritative for **requirement-driven timed acquisition**. Its rule that PV/current-storage sufficiency eliminates requirement-driven grid supplementation remains valid.

ADR-048 adds a distinct reason a `COST_FIRST` Candidate may exist: complete-path economic comparison under ADR-041.

Therefore Candidate Generation must distinguish at least these semantics internally:

- `requirement_driven_acquisition`
- `economic_path_acquisition`

This distinction is planning evidence, not a new execution mode.

## Evaluation and explainability

When an economic acquisition Candidate is generated while PV/current storage is already sufficient, PicoT must expose that grid charging was **not required for feasibility** and was considered only as an economic alternative.

The explanation must include the decisive import/export price consequences and the future energy-flow consequence that justified constructing the Candidate.

## Non-goals

This ADR does not:

- modify ADR-041 or ADR-044;
- permit price-to-action control;
- permit hidden price thresholds;
- create speculative battery filling without an allocation basis;
- introduce vendor-specific Zendure behaviour;
- bypass User Objectives, Evaluation, Execution authority or ADR-047.

## Acceptance criteria

1. PV/current storage sufficient for a requirement still produces no **requirement-driven** grid-acquisition Candidate.
2. The same state may produce an **economic-path** acquisition Candidate only when complete financial and allocation evidence exists.
3. Missing export settlement evidence prevents economic-path Candidate construction.
4. A cheaper grid interval alone is insufficient; Candidate Generation must have a traceable complete-path energy role for the acquired energy.
5. Evaluation, not Candidate Generation, determines whether the economic Candidate wins.
6. Existing ADR-044 requirement-driven acceptance behaviour remains covered by regression tests.
