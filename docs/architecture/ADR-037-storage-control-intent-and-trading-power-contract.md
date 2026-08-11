# ADR-037 — Storage Control Intent, Projection and Trading Power Contract

**Status:** Proposed  
**Date:** 2026-08-11

## Context

ADR-015 defines generic storage Execution Primitives and keeps vendor mode names out of the PicoT Core. The accepted Zendure integration strategy maps the balance primitives to the existing integration's NOM behaviour and maps `CHARGE_AT_POWER` / `DISCHARGE_AT_POWER` to explicit power commands.

PicoT deliberately uses the battery integration's mature closed-loop NOM regulation for normal household balancing. PicoT should decide **which storage behaviour is desired and when**, but should not continuously reproduce the integration's internal power controller.

The current ADR-031 cost-first section was written conservatively around `CHARGE_AT_POWER` because no later storage-control contract existed yet. That wording is too broad for the intended v1 architecture: normal charging/discharging behaviour must remain integration-managed, while deliberate market trading is the explicit exception where PicoT may request a power level.

ADR-036 supplies canonical low-price and high-price Opportunities, but an Opportunity remains evidence only. It does not prescribe a device mode, power value or action.

A precise contract is therefore required to separate:

1. integration-managed balancing;
2. explicit-power trading;
3. projected storage-state requirements used to prove complete-path feasibility.

## Decision

PicoT distinguishes two storage control intents.

### 1. Integration-managed balance control

Normal household battery behaviour uses balance primitives:

- `BALANCE_BIDIRECTIONAL`;
- `BALANCE_CHARGE_ONLY`;
- `BALANCE_DISCHARGE_ONLY`.

For these primitives:

- PicoT chooses the desired behaviour and its time window;
- PicoT does **not** attach `requested_power_w`;
- the Device Adapter translates the generic primitive to the supported integration mode;
- the battery integration determines instantaneous charge/discharge power using its own closed-loop balancing logic;
- PicoT observes the resulting power, SoC and grid balance and replans when reality materially changes.

For the current Zendure strategy this means, for example:

```text
BALANCE_BIDIRECTIONAL
→ Zendure adapter
→ Nul op de meter
```

```text
BALANCE_DISCHARGE_ONLY
→ Zendure adapter
→ Alleen slim ontladen
```

The exact vendor mode remains an Adapter concern under ADR-015.

### 2. Explicit-power trading control

Deliberate import/export trading may use:

- `CHARGE_AT_POWER`;
- `DISCHARGE_AT_POWER`.

These primitives intentionally bypass integration-managed NOM balancing for the duration of the trading segment because the trading objective requires a deliberate grid energy flow.

Only an accepted scenario explicitly classified as power-controlled may use these primitives. The initial accepted use case is Dynamic Trading.

Outside such a power-controlled scenario, PicoT must not convert an Opportunity or storage target into an explicit battery wattage.

## Normal control principle

For normal HEMS operation:

> PicoT controls storage intent, not instantaneous storage power.

A Candidate may therefore contain a balance-mode Path Segment without `requested_power_w`.

The Candidate Engine may choose among supported balance behaviours according to accepted scenario templates, but it must not calculate a constant charging/discharging wattage merely because a storage capability exposes a maximum power.

This preserves the existing battery integration as the local fast controller while PicoT remains the higher-level planner.

## Trading power policy

Trading requires explicit power because the objective is to deliberately import or export energy rather than merely balance the household.

The initial trading contract supports two explicit user/configuration policies per logical storage capability:

- `MAX_SUPPORTED` — use the explicitly known maximum trading power supported by the capability/control chain;
- `FIXED_W` — use an explicitly configured fixed trading power in watts.

`FIXED_W` must satisfy all known capability, phase, grid and system limits. Invalid values cause Candidate exclusion; they are never silently clamped to a different hidden value.

The initial contract does **not** let PicoT invent or optimise an arbitrary intermediate trading wattage. A future `PLANNER_SELECTED` trading-power policy requires a separate accepted extension defining bounded candidate construction and evaluation of alternative power levels.

This keeps the first implementation deterministic while allowing a user to choose less than the maximum when desired.

## Why a lower trading power can be useful

Maximum supported power may often be the best choice, especially when efficiency and available trade-window duration favour fast transfer. It is not universally required.

A lower explicit trading power can be useful when, for example:

- simultaneous household or EV load requires grid/phase headroom;
- export or import limits are lower than the battery's own maximum;
- a long trading window makes full power unnecessary;
- the user wants to preserve headroom for expected PV or other controllable loads;
- a device/control-chain constraint makes a lower operating point preferable.

These are feasibility or configuration reasons. Price Opportunity Detection remains unaware of them.

## Storage Planning State

Projected battery state remains necessary for complete-path feasibility even when the battery integration controls instantaneous NOM power.

The planning-domain storage state contains, where applicable:

- logical storage capability identifier;
- measured current SoC;
- usable energy capacity in Wh;
- measurement timestamp;
- confidence;
- source/version references.

For explicit-power trading projection, one-way charge/discharge efficiency is also required when the path depends on a quantitative stored-energy calculation.

Unknown values remain explicitly unknown. PicoT does not infer capacity or efficiency from a vendor/model name.

## Energy Requirements

An `EnergyRequirement` is an immutable future storage-state requirement, not a price Opportunity and not an Execution Plan.

Initial requirement kinds remain:

- `MINIMUM_RESERVE`;
- `TARGET_SOC`;
- `RECOVERY_TARGET`.

A requirement contains at least:

- requirement identifier;
- target logical storage capability or execution scope;
- deadline;
- required target state;
- hard/soft classification;
- confidence;
- source/version references.

Price level alone never creates an Energy Requirement.

A cheap price Opportunity therefore cannot silently create a rule such as “charge to 100%”.

## Relationship between requirements and balance control

An Energy Requirement may be used to test whether a complete Candidate remains feasible, but it does not force PicoT to replace integration-managed balance control with explicit power control.

For a balance-mode Candidate:

- the Path Segment expresses the supported balance primitive;
- no explicit wattage is attached;
- Simulation / projected-state logic uses accepted PV, load, storage and observed-control assumptions to estimate the resulting SoC trajectory;
- if the required future state cannot be proven with sufficient support, the Candidate is invalid or excluded rather than converted into `CHARGE_AT_POWER` as a fallback.

Thus a storage target is a feasibility fact, not permission to seize low-level power control.

## Projected storage state

Every complete storage Energy Path must contain sufficient projected state to prove the hard feasibility decisions it makes.

Projected state may include:

- battery SoC;
- expected household import/export;
- expected PV and load;
- confidence;
- explicit assumptions about integration-managed balance behaviour where applicable.

For explicit-power trading segments, quantitative energy projection uses explicit one-way efficiency:

```text
input_energy_wh × charge_efficiency = stored_energy_added_wh
```

```text
stored_energy_removed_wh × discharge_efficiency = delivered_energy_wh
```

A round-trip-efficiency number may not be silently split into two one-way values.

## Low-price Opportunities

`LOWEST_PRICE_WINDOW` and `NEGATIVE_PRICE_WINDOW` remain objective evidence from ADR-036.

They may support more than one type of Candidate depending on active strategy and accepted scenario templates.

Examples:

- a normal balance-control Candidate may choose a `BALANCE_*` behaviour during or around the Opportunity without setting power;
- a Dynamic Trading Candidate may deliberately use `CHARGE_AT_POWER` under the explicit trading-power policy.

The Opportunity Engine does not decide which interpretation is used.

Multiple Opportunities remain available to Candidate Generation. They are not ranked or collapsed by the Opportunity Engine.

## High-price Opportunities

`HIGH_EXPORT_VALUE_WINDOW` is evidence for a possible high-value discharge/export scenario.

Normal household discharge may still use integration-managed `BALANCE_DISCHARGE_ONLY` where an accepted Candidate template calls for that behaviour.

Deliberate export trading may use `DISCHARGE_AT_POWER`, but only when:

- the scenario is explicitly Dynamic Trading / power-controlled;
- the selected trading-power policy is valid;
- projected SoC remains above hard reserve requirements;
- a complete recovery trajectory exists where recovery is required;
- the full cycle can later be evaluated economically under PEP-RP-001.

A high price alone is insufficient.

## Dynamic Trading boundary

Dynamic Trading is the intentional exception to the normal “intent, not power” rule.

Trading Candidates may explicitly propose charge/discharge power because controlled grid import/export is itself part of the trading action.

The trading power remains separate from the trading SoC boundary:

- trading SoC limits determine how much battery capacity may participate;
- trading power policy determines the requested instantaneous trading power;
- capacity outside the allowed trading SoC range remains reserved according to the active planning constraints.

The Opportunity Engine remains unaware of both.

## Relationship to ADR-027 Dynamic Power Allocation

ADR-027 currently states generally that PicoT may adjust battery charge/discharge power inside active commitments.

This ADR narrows that rule for storage:

- for integration-managed `BALANCE_*` commitments, the local integration controls instantaneous battery power and PicoT does not continuously set watts;
- for explicit-power commitments such as Dynamic Trading, the Execution Engine may apply the committed explicit power within the accepted trading policy and hard constraints;
- any future automatic optimisation of explicit trading power requires an accepted extension rather than hidden runtime behaviour.

## Relationship to ADR-031 Candidate construction

This ADR refines the earlier ADR-031 “Cost-first storage charging” boundary.

The requirement for `CHARGE_AT_POWER` is **not** universal for low-price storage Candidates.

Instead:

- normal storage Candidates use supported `BALANCE_*` primitives without requested power;
- Dynamic Trading Candidates may use `CHARGE_AT_POWER` / `DISCHARGE_AT_POWER` under this explicit trading contract;
- a missing quantitative projection may invalidate a Candidate, but may not silently change its control intent.

After acceptance, ADR-031 should be amended to reference this distinction explicitly.

## Exclusions

Candidate Generation emits an explainable exclusion when, for example:

- the required balance primitive is unsupported;
- the storage capability is unavailable or unhealthy;
- a hard future SoC requirement cannot be proven under the selected control intent;
- Dynamic Trading requests explicit power but no valid trading-power policy exists;
- `FIXED_W` violates capability, phase, grid or system limits;
- required quantitative trading projection lacks SoC, capacity or one-way efficiency;
- deliberate discharge lacks a required recovery path.

No exclusion is converted into a hidden fallback power value.

## Determinism

For identical immutable planning inputs and the same selected control/power policy, Candidate Generation produces identical:

- control intent;
- Path Segments;
- explicit trading power where applicable;
- projected-state assumptions;
- Candidate identifiers and ordering;
- exclusions and reasons.

## Initial implementation boundary

After acceptance, implementation will proceed in this order:

1. amend ADR-031 to distinguish balance-control Candidates from explicit-power trading Candidates;
2. clarify ADR-027 so integration-managed balance commitments do not imply PicoT watt control;
3. represent storage planning state / Energy Requirements needed for projected feasibility;
4. allow normal storage Candidate templates to use `BALANCE_*` primitives with no `requested_power_w`;
5. keep direct Home Assistant/vendor modes confined to the Device Adapter;
6. add explicit Dynamic Trading power policy with `MAX_SUPPORTED` and `FIXED_W`;
7. keep automatic planner-selected trading power out of scope until a later accepted extension;
8. preserve Evaluation → Winning Energy Path → Execution Plan → Execution Engine before any physical command.

## Relationship to existing ADRs and PEPs

- ADR-015: generic balance and explicit-power primitives remain the Core vocabulary;
- ADR-017: complete rolling-horizon planning and projected-state feasibility;
- ADR-023 and ADR-036: Opportunities remain evidence, not actions;
- ADR-027: commitment/dynamic allocation is narrowed by control intent for storage;
- ADR-030: Paths and Projected Energy States remain immutable planning records;
- ADR-031: scenario construction is refined so low-price does not imply `CHARGE_AT_POWER`;
- ADR-032: Evaluation remains separate and selects among complete Candidate outcomes;
- ADR-033: only a Winning Energy Path becomes an Execution Plan;
- PEP-RP-001: discretionary export/discharge still requires full-horizon feasibility, recovery and economic reasoning;
- `docs/integrations/ZENDURE_STRATEGY.md`: current v1 integration mapping already separates NOM balance modes from explicit power commands.

## Consequences

- PicoT does not duplicate the battery integration's working NOM power controller.
- Normal storage control remains behaviour-based and vendor-independent.
- Dynamic Trading can deliberately request a configurable power level.
- Maximum trading power remains available as the simple/default policy, while fixed lower power is possible when useful.
- A future PicoT-native battery adapter can implement the same generic control intents without changing Planner architecture.
- Low-price/high-price Opportunities remain reusable evidence for both balance and trading Candidates.

## Core principle

> For normal household storage control, PicoT chooses intent and timing while the battery integration controls instantaneous power. Explicit battery wattage is an intentional power-controlled action, initially reserved for Dynamic Trading and bounded by an explicit trading-power policy.