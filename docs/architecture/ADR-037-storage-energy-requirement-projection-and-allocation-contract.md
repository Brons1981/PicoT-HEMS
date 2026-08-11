# ADR-037 — Storage Energy Requirement, Projection and Candidate Allocation Contract

**Status:** Proposed  
**Date:** 2026-08-11

## Context

ADR-017 requires PicoT to evaluate complete energy paths over a rolling planning horizon, including projected SoC, future recovery and confidence. ADR-030 defines immutable `EnergyPath`, `PathSegment`, `ProjectedEnergyState` and `CapabilitySnapshotSet`. ADR-031 deliberately keeps cost-first charging and high-value discharge excluded until explicit energy-target, projected-state and power-allocation contracts exist.

ADR-036 now supplies canonical low-price and high-price Opportunities, but an Opportunity remains evidence only. It does not state how much energy a storage device should receive or release.

The current implementation therefore has a correct architectural stop:

- `LOWEST_PRICE_WINDOW` and `NEGATIVE_PRICE_WINDOW` reach Candidate Generation;
- `HIGH_EXPORT_VALUE_WINDOW` reaches Candidate Generation;
- Candidate Generation cannot yet construct a valid storage charging or discharge path because the required future energy state and allocation are not explicit.

Implementing a direct rule such as “charge at maximum power whenever the price is low” would reintroduce hidden planner policy and would violate ADR-017, ADR-023, ADR-030 and ADR-031.

## Decision

PicoT introduces a deterministic storage planning contract consisting of three related facts:

1. **Storage Planning State** — what PicoT knows about the storage device now;
2. **Energy Requirement** — what future stored-energy state must or should be achievable by a stated deadline;
3. **Candidate Allocation** — how a Candidate may allocate explicit charge or discharge power inside one or more accepted Opportunities while preserving the requirement and hard constraints.

These facts are planning-domain data. They are vendor-independent and immutable within one Planning Input Snapshot.

Price Opportunity Detection remains independent of storage state, SoC, household load and device actions.

## Storage Planning State

A storage Candidate may only be constructed when the Planner has sufficient explicit storage state to project the consequence of a power allocation.

The planning-domain storage state contains, where applicable:

- logical storage capability identifier;
- measured current SoC;
- usable energy capacity in Wh;
- charge efficiency;
- discharge efficiency;
- measurement timestamp;
- confidence;
- source/version references.

The current SoC is an observed state fact and belongs to the Planning Input Snapshot, not to price analysis.

Usable capacity and conversion efficiencies are technical storage facts. They may be supplied through the logical capability/configuration contract, but they may not be guessed from a vendor name, battery model label or nominal marketing capacity.

Unknown values remain explicitly unknown.

## Energy Requirement

An `EnergyRequirement` is an immutable future planning requirement. It is not a price Opportunity and it is not an Execution Plan.

A storage Energy Requirement contains at least:

- requirement identifier;
- target logical storage capability or execution scope;
- requirement kind;
- required deadline;
- required target state;
- hard/soft classification;
- confidence;
- source and version references.

Initial supported target state for storage is a target SoC. The equivalent required stored energy may be derived only when usable capacity is known.

Initial requirement kinds are:

- `MINIMUM_RESERVE`
- `TARGET_SOC`
- `RECOVERY_TARGET`

`MINIMUM_RESERVE` expresses a lower bound that may never be violated by a Candidate when the requirement is hard.

`TARGET_SOC` expresses a required or preferred storage state by a stated deadline.

`RECOVERY_TARGET` expresses the state that must be restored after a discretionary discharge sequence.

No implicit target is created merely because a cheap price window exists.

## Requirement sources

An Energy Requirement may originate only from explicit accepted planning inputs, for example:

- a hard system SoC boundary;
- an explicit user-configured target;
- a valid PicoT User Rule;
- an active Execution Commitment;
- an accepted device/Energy Profile requirement;
- a deterministic recovery requirement created as part of a complete discharge/recharge Candidate;
- a later accepted requirement-producing contract.

Price level alone is never a requirement source.

If no supported requirement exists, cost-first storage charging remains excluded. PicoT does not invent a target such as “charge to 100% because electricity is cheap”.

## Energy Requirement Set

One Planning Input Snapshot may contain multiple requirements.

PicoT represents them as one immutable `EnergyRequirementSet` tied to the same snapshot. Requirements remain individually traceable and retain their source, deadline, confidence and hard/soft classification.

Conflicting hard requirements cause Candidate exclusion or a diagnosable planning-input conflict; they are not silently reconciled.

Soft requirements may be represented in Candidate outcomes later, but they never override hard system or capability limits.

## Stored-energy projection

For storage Candidates, projected SoC is derived from explicit energy flow and one-way efficiency.

For charging over an interval:

```text
grid_or_source_energy_wh
× charge_efficiency
= stored_energy_added_wh
```

For discharge over an interval:

```text
stored_energy_removed_wh
× discharge_efficiency
= delivered_energy_wh
```

The projected storage energy is bounded by the usable energy capacity and by explicit capability minimum/maximum SoC constraints.

A Candidate may use only one-way efficiencies that are explicit in the planning input. A round-trip efficiency value may not be silently split into two one-way values without a separate accepted rule.

If a required projection depends on unknown capacity, SoC or efficiency, the Candidate is excluded rather than approximated with an invented default.

## Required Projected Energy States

A storage Energy Path must contain sufficient `ProjectedEnergyState` points to prove every hard storage-feasibility decision it makes.

For the initial cost-first charging template, projected state points are required at least at:

- horizon start;
- each storage Path Segment boundary that changes projected storage energy;
- the applicable Energy Requirement deadline;
- horizon end when it differs from the last requirement deadline.

Each projected state records the projected battery SoC and confidence used by the Candidate.

Additional projected dimensions remain optional unless required by another hard feasibility contract.

## Candidate allocation principle

Candidate Generation allocates power only after it has:

1. an applicable Opportunity;
2. a matching healthy and available storage capability;
3. an explicit Energy Requirement;
4. sufficient storage planning state;
5. explicit supported power limits and power step where applicable.

The Candidate Engine never chooses power merely because a device can support that power.

The allocation must be the smallest supported constant power that can satisfy the applicable target within the Candidate's selected Opportunity window and before the requirement deadline.

Formally, for one charging segment:

```text
required_stored_energy_wh
= max(0, target_stored_energy_wh - projected_stored_energy_at_segment_start_wh)

required_input_energy_wh
= required_stored_energy_wh / charge_efficiency

raw_required_power_w
= required_input_energy_wh / available_segment_hours
```

The requested power is then adjusted upward to the smallest explicitly supported power step that can still satisfy the requirement, while respecting minimum and maximum capability power.

If the resulting supported power cannot satisfy the requirement before the deadline, that Candidate is excluded.

This rule prevents “always charge at maximum power” from becoming hidden policy.

## Multiple price Opportunities

ADR-036 may produce several low-price Opportunities over the rolling horizon. Candidate Generation does not rank or collapse them.

For the initial cost-first template:

- each individual low-price or negative-price Opportunity that can satisfy the requirement on its own may produce a separate `COST_FIRST` Candidate;
- multiple such Candidates are preserved for later Simulation and Evaluation;
- the Candidate Engine does not mark one Opportunity as “best”;
- tomorrow's Opportunity does not invalidate today's Opportunity merely because its price is lower.

The first implementation does not construct combinatorial multi-window charge paths when no single Opportunity can satisfy the requirement. Such paths require an explicit bounded scenario-construction extension to avoid uncontrolled Candidate explosion.

## Negative-price Opportunities

`NEGATIVE_PRICE_WINDOW` remains a separate objective Opportunity kind.

A negative price may improve the financial outcome of a Candidate, but it still does not create an Energy Requirement by itself. The storage Candidate must satisfy the same state, capability and projection contracts as any other cost-first Candidate.

## High-value discharge

`HIGH_EXPORT_VALUE_WINDOW` remains evidence for a possible discharge scenario.

A discretionary high-value discharge Candidate may only be generated when PicoT can construct the complete discharge-and-recovery sequence required by ADR-017 and PEP-RP-001.

That sequence must explicitly establish:

- current projected storage state;
- the amount of storage energy proposed for discharge;
- the post-discharge SoC;
- all applicable reserve/target requirements;
- a feasible `RECOVERY_TARGET`;
- one or more explicit future recovery Opportunities;
- sufficient charge power and time to restore the required energy;
- conversion losses using explicit efficiency facts;
- a complete projected SoC trajectory that never violates hard constraints.

A high export price alone is insufficient.

Until the complete recovery sequence and the required economic outcome producer exist, high-value discharge remains excluded by Candidate Generation.

## Relationship to Dynamic Power Allocation

ADR-027 Dynamic Power Allocation applies after a plan has been selected and committed. It may adjust power inside the flexibility of an active Execution Commitment.

This ADR concerns Candidate construction before Evaluation.

Therefore:

- Candidate Allocation determines a proposed power/time path for comparison;
- Dynamic Power Allocation may later adjust a committed plan only within the limits allowed by ADR-027 and without invalidating the commitment's required energy state.

The two responsibilities must not be merged.

## Relationship to Energy Profiles

ADR-019 Energy Profiles may supply expected energy demand or duration for flexible consumers and external actions.

An Energy Profile is not automatically a storage target. It may contribute to a future Energy Requirement only through an explicit accepted requirement-producing rule.

PicoT never converts an appliance label or unverified profile into a battery target.

## Confidence

Candidate projection confidence is bounded by the least-confident required fact used in the projection, including where applicable:

- current SoC confidence;
- capacity/configuration confidence;
- efficiency confidence;
- Energy Requirement confidence;
- Opportunity confidence;
- capability confidence.

Unknown confidence is not silently treated as `1.0`.

## Exclusions

Candidate Generation emits an immutable explainable exclusion when, for example:

- no Energy Requirement exists;
- current SoC is unknown;
- usable capacity is unknown;
- required one-way efficiency is unknown;
- storage capability is unavailable or unhealthy;
- required charge/discharge primitive is unsupported;
- power limits are unknown;
- the Opportunity ends after too little usable time;
- the supported power step cannot meet the requirement;
- projected SoC would violate a hard bound;
- a discharge Candidate lacks a complete recovery path.

No exclusion is converted into a fallback guess.

## Determinism

For identical immutable Planning Input, Opportunity, Requirement and Capability data, Candidate Allocation produces identical:

- required energy;
- requested power;
- projected state points;
- Candidate identifiers and ordering;
- exclusions and reasons.

Random variation and hidden heuristics are not permitted.

## Initial implementation boundary

The first implementation after acceptance will:

1. add immutable storage planning-state and Energy Requirement domain records;
2. include them atomically in the Planning Input contract;
3. extend logical storage capability data with explicit usable capacity and one-way efficiency facts where available;
4. implement projected storage SoC for candidate charging;
5. implement the single-Opportunity cost-first charging template defined above;
6. preserve one Candidate per individually feasible low/negative Opportunity;
7. keep high-value discharge explicitly excluded until a complete recovery and economic-cycle contract is available;
8. keep all physical dispatch behind Evaluation, Winning Energy Path selection and Execution Plan construction.

## Relationship to existing ADRs and PEPs

- ADR-017: complete rolling-horizon planning, SoC projection and recoverability;
- ADR-019: Energy Profiles remain separate expected-energy descriptions;
- ADR-023 and ADR-036: Opportunities remain objective evidence and never prescribe storage actions;
- ADR-024: Candidate Generation preserves a small set of meaningful alternatives;
- ADR-027: committed-task Dynamic Power Allocation remains an Execution responsibility;
- ADR-030: storage paths use immutable `EnergyPath`, `PathSegment`, `ProjectedEnergyState` and logical capabilities;
- ADR-031: this ADR supplies the previously missing target/projection/allocation contract for cost-first construction;
- ADR-032: Candidate Evaluation remains separate and compares outcomes without hidden aggregate scoring;
- ADR-033: only a Winning Energy Path may become an Execution Plan;
- PEP-RP-001: discretionary discharge requires a complete feasible recovery path and full-horizon economic reasoning.

## Consequences

- Cost-first charging can be implemented without turning a price Opportunity into an instruction.
- Multiple price Opportunities remain available as separate candidate scenarios.
- Storage power is derived from an explicit energy requirement rather than from maximum device capability.
- Missing SoC, capacity or efficiency data becomes visible instead of being hidden by assumptions.
- Tomorrow's cheaper prices cannot directly suppress today's opportunities; they become alternative evidence inside complete Candidates.
- High-price export remains conservative until PicoT can prove both recovery and economic value over the complete sequence.
- Projected SoC becomes a real planning-domain contract rather than an informal diagnostic value.

## Core principle

> Price Opportunities identify when energy may be economically attractive. Energy Requirements define what future storage state must be achieved. Candidate Allocation connects the two using explicit storage state, capability limits and projected SoC. No price window creates its own target, and no discretionary discharge is allowed without a complete recovery path.
