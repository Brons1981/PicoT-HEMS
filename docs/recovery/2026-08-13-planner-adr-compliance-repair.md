# Planner ADR compliance repair — 2026-08-13

## Status

In progress. This is an implementation-repair record, not a new architecture decision.

Accepted ADRs remain frozen and authoritative.

## Trigger

Live validation on 2026-08-13 showed a battery at approximately 39% SoC with canonical price Opportunities available, yet the live Planner produced only one `reserve_first` Candidate, an empty ExecutionPlanSet and no timed charging plan.

The expected PicoT behavior is the behavior already defined by the accepted architecture: compare complete energy paths over the rolling horizon and determine the financially/energetically best feasible timing for flexible energy acquisition. The same architecture is intended to scale beyond storage to EVs and other controllable loads through capabilities and Energy Profiles.

## Accepted contracts already covering the behavior

- ADR-017: complete future Energy Paths, projected energy state, expected PV charging, planned grid charging, recoverability and price-aware planning.
- ADR-019: explicit Energy Profiles / Planning Hints for future controllable or externally triggered demand.
- ADR-023: Opportunities are objective evidence only and never actions.
- ADR-024: Candidate Engine builds complete meaningful alternatives such as PV-first, cost-first and reserve-first.
- ADR-025: Planner Strategy / User Objectives govern which valid alternative wins.
- ADR-032: Evaluation selects only from comparable immutable Candidate Outcomes and may not invent hidden objective values.
- ADR-037: complete household/storage requirement, PV-first feasibility and explicit grid-supported charging when needed or economically justified.
- ADR-044: exact timed storage-acquisition intervals are selected inside canonical price Opportunities; Opportunity windows themselves never command charging.
- ADR-047: selected mode, execution control authority and physical device activity are execution/provenance concerns and must not redefine Planner economics.

No ADR-048 is justified by the current finding.

## Compliance findings

### 1. Live PV-surplus Opportunity input is incomplete

`OpportunityEngine` can produce `PV_SURPLUS_WINDOW` and `CandidateEngine` can already construct `PV_FIRST` Energy Paths using `CHARGE_AT_POWER` with `PV_ONLY` source policy.

However the live PlanningInputSnapshot carries future PV and load primarily as `PVEnergyTimeline` and `HouseholdLoadForecast`. Live Opportunity detection currently detects PV surplus only from `ForecastSeries(kind=PV_POWER)` plus `ForecastSeries(kind=HOUSEHOLD_LOAD)`.

The live runtime therefore sees price Opportunities but can omit the PV-surplus Opportunity even though the same atomic snapshot already contains the canonical PV and load energy evidence.

Observed symptom: `canonical_price_opportunity_count > 0` while `candidate_count = 1` and only the passive baseline exists despite current/future PV surplus evidence.

Repair principle: Opportunity Detection must consume the canonical PV/load evidence already present in the same PlanningInputSnapshot. Do not create a parallel PV planner.

### 2. Passive reserve-first baseline can win without proving the planned PV path

`ProjectedHouseholdEnergyBalance` includes expected usable PV, which is correct under ADR-037. But `reserve_first` currently contains zero controllable segments and is still considered valid whenever the energy-only PV feasibility result is sufficient.

That is not enough to prove that the selected complete Energy Path actually contains the controllable behavior needed to make the expected PV usable by storage. A current device mode must not define Planner economics, but a winning Candidate must still be a complete realizable Energy Path rather than relying on an unstated execution assumption.

Repair principle: expected PV remains part of requirement/recoverability evidence, while Candidate validity must be tied to a complete path that can actually realize the required energy flow using supported capabilities. No runtime mode-selector workaround is permitted.

### 3. Live PlannerStrategy currently has no objectives

The live snapshot currently builds `PlannerStrategy(..., optimisation_profile=BALANCED, objectives=())`.

Under ADR-032 this means no strategic objective can decide a winner. Evaluation therefore falls through to deterministic tie-breaks such as confidence and execution complexity. An empty baseline naturally tends to beat an otherwise valid charging path on those tie-breaks.

This prevents the live Planner from demonstrating the expected financially favorable charging-window behavior even when price and Candidate evidence exist.

Repair principle: wire the accepted User Objective / Objective Mapping contract into the live PlanningInputSnapshot. Do not invent hidden default financial weights in Evaluation or Candidate Generation. If a temporary development profile exists, it must be explicit, versioned and traceable as Planner Strategy input rather than hard-coded winner logic.

### 4. Candidate outcome production is intentionally incomplete

`ADR037CandidateOutcomeDeriver` explicitly does not yet derive comparable financial result, self-consumption, grid import, reserve or other objective values. ADR-032 correctly prevents Evaluation from inventing them.

Therefore a financially best timed Candidate cannot be selected correctly until the existing simulation/outcome-producing responsibility supplies comparable values for all valid Candidates.

Repair principle: extend the existing Candidate outcome/simulation path according to accepted ADR-017/032/037/044. Do not move financial scoring into Evaluation and do not add a hidden aggregate score.

## Repair order

1. Make live PV-surplus Opportunity detection consume the canonical PV/load evidence from the same PlanningInputSnapshot.
2. Add acceptance coverage proving that a live snapshot with PV surplus produces a PV-first Candidate and that price and PV Opportunities coexist atomically.
3. Tighten complete-path validity so a passive baseline cannot claim future controllable storage acquisition without a realizable path/capability basis.
4. Wire an explicit, versioned Planner Strategy / Objective Profile into the live snapshot instead of `objectives=()`.
5. Implement comparable Candidate Outcomes for the objectives required to select among reserve-first, PV-first and cost-first paths, including financial result where configured.
6. Re-run live dry-run validation and require the observer to expose the selected timed Energy Path and resulting ExecutionPlan segments before any adapter/dispatch work continues.

## Non-negotiable constraints

- No accepted ADR is modified for this repair.
- No Price Driven v1/24-block selector path is reintroduced.
- No vendor-specific mode logic enters Planner, Opportunity, Candidate or Evaluation layers.
- No runtime heuristic selects the “best quarter”.
- No workaround makes the current Zendure mode determine the preferred economic plan.
- Each layer retains one responsibility.
- Temporary bridging code, if unavoidable, must be explicitly marked in code and in this recovery record with its removal condition.

## Live validation target

For a representative live run with low storage SoC, future PV/load evidence and canonical price Opportunities, diagnostics must eventually show more than the passive baseline when controllable acquisition alternatives exist, with separate evidence for:

- PV-surplus Opportunity(s);
- price Opportunity(s);
- generated PV-first / cost-first alternatives as applicable;
- objective outcomes for all valid Candidates;
- deterministic winning Candidate and exact selected acquisition intervals;
- resulting immutable ExecutionPlanSet;
- ADR-047 authority independently determining whether that already-selected plan may execute.
