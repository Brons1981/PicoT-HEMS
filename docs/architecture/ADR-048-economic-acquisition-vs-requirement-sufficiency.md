# ADR-048 — Economic Acquisition versus Requirement Sufficiency

**Status:** Proposed  
**Date:** 2026-08-13

## Context

ADR-044 currently requires that a broad cheap-price Opportunity does not create a requirement-driven grid-supported timed storage-acquisition Candidate when the simulated current-storage/PV path already satisfies the active `StorageEnergyRequirement`. Its acceptance test 4 makes this explicit for the ADR-044 PV-first requirement path.

ADR-041, accepted later, requires PicoT to compare complete Energy Paths using time-dependent storage value, future import/export prices and replacement cost. That contract applies across seasons and energy-source conditions. It explicitly allows economic comparisons where preserving storage, exporting available generation, replacing energy later, shifting future import, or retaining storage for higher-value future use can be preferable while all requirements remain feasible.

Live validation on 2026-08-13 exposed the conflict. The current `CandidateEngine` follows ADR-044 and rejects `COST_FIRST` paths whenever `pv_only_feasibility.energy_sufficient` is true or `additional_acquisition_required` is false. As a result, Evaluation never receives an economically timed grid-acquisition alternative in situations where ADR-041 may require one for complete-path comparison.

The architectural problem is not specific to PV. A requirement may already be feasible because of current storage, expected PV, another accepted future energy contribution, or a combination of sources. Conversely, in winter there may be little or no usable PV and the economically preferable complete path may depend mainly on timed grid acquisition and later storage use. Candidate diversity must therefore not depend on PV being present.

Neither ADR-041 nor ADR-044 is modified by this ADR. Both remain immutable Accepted records.

## Decision

PicoT separates **requirement-driven acquisition necessity** from **economically relevant acquisition alternatives**.

A feasibility result stating that no additional acquisition is required means only that the applicable StorageEnergyRequirements are already achievable under the canonical projected path. It does not by itself prove that every alternative acquisition Energy Path is economically dominated over the complete planning horizon.

`PVOnlyStorageEnergyFeasibility.energy_sufficient == true` is one possible feasibility signal within the ADR-037/ADR-044 path. It means grid-supported acquisition is not required to satisfy the active StorageEnergyRequirement under that projected PV/current-storage path. It is not a global economic prohibition.

`StorageTechnicalRecoverability.additional_acquisition_required == false` similarly means no additional acquisition is required for requirement feasibility. It is not a global prohibition on constructing an economic alternative.

Candidate Generation may therefore construct an economically timed storage-acquisition Candidate regardless of whether usable PV is present, provided all of the following are true:

- an applicable economic Opportunity exists;
- complete canonical settlement evidence required for the comparison is available;
- canonical household-load, storage state, storage limits and charging capability are available;
- any available generation or other accepted future energy contribution used by the Candidate is represented explicitly in canonical evidence;
- an explicit charge-allocation target can be derived without inventing a fixed SoC target;
- the resulting Candidate remains within all hard limits and preserves every applicable StorageEnergyRequirement;
- Candidate Simulation can project the complete Energy Path;
- Candidate Outcome Production can derive every active decisive objective outcome for the compared Candidates under equivalent evidence.

The existence of such a Candidate does not command charging. Evaluation remains solely responsible for winner selection under the active Planner Strategy.

## Source-independent planning principle

Economic acquisition is **source-independent** at the planning-contract level.

The presence, absence or seasonal scarcity of PV must not switch PicoT into a different planning architecture. The same Candidate/Simulation/Evaluation pipeline applies when:

- substantial PV is available;
- limited PV is available;
- no usable PV is forecast;
- current storage alone already satisfies the requirement;
- grid acquisition is required for feasibility;
- grid acquisition is not required for feasibility but may still participate in a better complete economic path.

Available PV remains important canonical evidence and may materially change Candidate outcomes, but it is not a prerequisite for economic Candidate construction.

## Allocation boundary

ADR-031 remains authoritative that Candidate Generation may not invent a charging amount. Economic acquisition therefore requires an explicit allocation basis.

An economic Candidate may acquire only energy that has a traceable role in the complete Energy Path, such as:

- replacing stored energy deliberately preserved for a higher-value later interval;
- replacing energy deliberately discharged during a higher-value interval;
- shifting an otherwise expected future grid import into a cheaper feasible interval;
- supplying a future requirement when no sufficient generation is expected;
- combining available generation and grid acquisition when that complete path is preferable;
- creating storage headroom/value trade-offs whose consequences are fully represented by Simulation and applicable objective outcomes.

PicoT does not create a generic “fill the battery because it is cheap” Candidate and does not introduce a fixed universal target SoC.

## Relationship to ADR-044

ADR-044 remains authoritative for **requirement-driven timed acquisition** and its PV/current-storage feasibility semantics. Its rule that PV/current-storage sufficiency eliminates requirement-driven grid supplementation remains valid for that path.

ADR-048 adds a distinct reason a `COST_FIRST` Candidate may exist: complete-path economic comparison under ADR-041, independent of whether PV is available.

Therefore Candidate Generation must distinguish at least these semantics internally:

- `requirement_driven_acquisition`
- `economic_path_acquisition`

This distinction is planning evidence, not a new execution mode.

## Evaluation and explainability

When an economic acquisition Candidate is generated while the active requirement is already feasible, PicoT must expose that grid charging was **not required for feasibility** and was considered only as an economic alternative.

When little or no PV is available, PicoT must likewise expose the future demand, storage requirement, relevant price intervals and replacement/preservation consequences that justify the Candidate.

The explanation must include the decisive price/settlement consequences and the future energy-flow consequence that justified constructing the Candidate.

## Non-goals

This ADR does not:

- modify ADR-041 or ADR-044;
- permit price-to-action control;
- permit hidden price thresholds;
- create speculative battery filling without an allocation basis;
- make economic planning conditional on PV availability;
- introduce a separate winter planner or seasonal code path;
- introduce vendor-specific Zendure behaviour;
- bypass User Objectives, Evaluation, Execution authority or ADR-047.

## Acceptance criteria

1. PV/current storage sufficient for a requirement still produces no **requirement-driven** grid-acquisition Candidate under ADR-044.
2. The same state may produce an **economic-path** acquisition Candidate only when complete objective and allocation evidence exists.
3. With no usable PV forecast, PicoT can still construct an economic-path acquisition Candidate when future demand/storage requirements, price evidence, storage capability and allocation evidence support it.
4. Absence of PV does not select a separate planner, Candidate Engine or seasonal code path.
5. Missing settlement/objective evidence required for financial comparison prevents a financially justified economic-path Candidate.
6. A cheaper grid interval alone is insufficient; Candidate Generation must have a traceable complete-path energy role for the acquired energy.
7. Evaluation, not Candidate Generation, determines whether the economic Candidate wins.
8. Existing ADR-044 requirement-driven acceptance behaviour remains covered by regression tests.
9. Equivalent canonical inputs produce equivalent Candidate semantics regardless of whether the available future energy contribution originates from PV, grid acquisition or another accepted source model.
