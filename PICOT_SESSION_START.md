# PicoT HEMS — mandatory session start

Upload this file at the start of every PicoT development session together with
the latest development handoff.  Read both completely before diagnosing,
designing or changing code.

This file is a routing index and guardrail.  The linked Accepted ADR files are
the architectural authority.  Current code, tests, comments, diagnostics and
earlier assistant memory are evidence, but they do not redefine ownership.

## Authority and reading order

1. `docs/rebuild/CANONICAL_PIPELINE_CONTRACT.md`
2. `docs/architecture/ADR-015-execution-primitives.md`
3. `docs/architecture/ADR-016-execution-plan-architecture.md`
4. `docs/architecture/ADR-017-planning-decision-pipeline.md`
5. `docs/architecture/ADR-023-opportunity-engine.md`
6. `docs/architecture/ADR-024-candidate-engine.md`
7. `docs/architecture/ADR-026-evaluation-engine.md`
8. `docs/architecture/ADR-027-execution-plan-commitment.md`
9. `docs/architecture/ADR-028-runtime-resource-governance.md`
10. `docs/architecture/ADR-030-energy-path-capability-snapshot-contract.md`
11. `docs/architecture/ADR-031-candidate-scenario-construction-contract.md`
12. `docs/architecture/ADR-032-candidate-evaluation-contract.md`
13. `docs/architecture/ADR-033-winning-energy-path-to-execution-plans.md`
14. `docs/architecture/ADR-034-runtime-monitor-material-change-replanning-contract.md`
15. `docs/architecture/ADR-035-home-assistant-adapter-contract.md`
16. `docs/architecture/ADR-036-price-opportunity-detection-contract.md`
17. `docs/architecture/ADR-037-household-energy-requirement-storage-reserve-grid-use.md`
18. `docs/rebuild/V2ADR-050-timed-delegated-storage-control.md`
19. `docs/rebuild/V2ADR-052-persistent-plan-commitment-and-material-replanning.md`
20. `docs/rebuild/V2ADR-055-mep-sole-canonical-planner.md`
21. `docs/architecture/decisions/V2ADR-057-measured-pv-charge-admission-and-visibility.md`
22. `docs/architecture/decisions/V2ADR-058-adaptive-market-commitments-and-execution-feedback.md`
23. `docs/architecture/decisions/V2ADR-059-financially-bounded-late-grid-fallback.md`
24. `docs/architecture/decisions/V2ADR-060-fast-vendor-mode-dispatch-failure-containment.md`
25. `docs/architecture/decisions/V2ADR-061-committed-segment-clock-boundary-execution.md`
26. `docs/architecture/decisions/V2ADR-062-material-replanning-and-commitment-comparison.md`
27. `docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md`

When two decisions appear inconsistent, do not silently choose one.  Identify
the controlling baseline and explicit superseding clause before changing code.

## Frozen canonical pipeline

```text
PlanningInputSnapshot
→ Opportunity Engine
→ OpportunitySet
→ MEP Candidate Generation and Simulation
→ CandidateSet + complete EnergyPaths
→ CandidateOutcomeSet
→ Evaluation Engine
→ Winning Candidate + Winning EnergyPath + EvaluationRecord
→ Execution Plan Builder
→ ExecutionPlanSet
→ Plan Store / commitment persistence
→ Execution Engine
→ ExecutionPrimitiveRequest
→ Device Adapter
→ Vendor Command and observed result
```

No stage may be replaced by a diagnostic projection, private planner result,
runtime shortcut or synthetic automatically winning record.

## Ownership boundaries

| Layer | Owns | Must not |
|---|---|---|
| Planning Input | Immutable current facts, evidence and versions | Plan, score or choose |
| Runtime Monitor | Classify producer-accepted material changes and request a fresh snapshot | Suppress observations, plan or modify plans |
| Opportunity Engine | Evidence-only opportunities and constraints | Select devices, assign power, build candidates or choose winners |
| MEP Candidate Generation | Complete physical candidates, Energy Paths and simulation outcomes | Select the winner, retain plans or dispatch |
| Evaluation Engine | Compare canonical outcomes and select exactly one winner | Generate candidates, build plans or choose vendor commands |
| Execution Plan Builder | Exact Winning Energy Path, including source policy, to scope-specific plans | Add, remove, merge or reinterpret actions |
| Plan Store | Persist one admitted plan and its revision per scope | Evaluate economics or invent replacements |
| Execution Engine | Due segment, live validation, retries and primitive requests | Re-rank, replace or economically redesign plans |
| Device Adapter | Primitive-to-vendor translation | Plan, evaluate or reinterpret strategy |
| Projection/UI | Present canonical records and lineage | Recalculate or become an authority |

## Commitment rules

- MEP does not choose the winner; canonical Evaluation does.
- A commitment never prevents creation of a fresh challenger after an accepted
  material change.
- Incumbent and challengers are complete remaining-horizon Energy Paths.
- They are evaluated from the same fresh snapshot and current physical state.
- Past cost and revenue are sunk; persisted outcomes are provenance only.
- Strictly better valid and executable wins.
- Equivalent or worse retains the incumbent.
- Physical infeasibility, reserve failure, Safety and hard constraints cannot
  be hidden by a financial switching margin.
- Ordinary progress is non-material; material SoC, household, PV, price,
  forecast, capability or execution changes remain observable.
- Clock-boundary execution and material replanning are independent signals.

## Mandatory change contract

Before editing, state:

1. observed problem and first bad canonical boundary;
2. controlling ADRs;
3. responsible layer;
4. layers explicitly out of scope;
5. invariant to preserve;
6. regression evidence required;
7. rollback boundary.

If implementation requires changing an out-of-scope layer or contradicting an
Accepted ADR, stop and revise the contract or write an explicit superseding ADR
before continuing.

## Mandatory implementation rules

- Fix defects in the owning layer; never compensate in a downstream layer.
- Do not build a parallel pipeline, planner, evaluator, commitment path or
  dispatch path.
- Do not use current code structure as proof of architectural ownership.
- Do not let an adapter, projection or live runtime invent planning policy.
- Do not accept an empty canonical outcome set for evaluated candidates.
- Do not construct an `EvaluationRecord` around a winner selected before the
  canonical CandidateSet and CandidateOutcomeSet exist.
- Do not hand-build live Execution Plans outside the canonical Plan Builder.
- Do not suppress canonical input before the Runtime Monitor can classify it.
- Add diagnostics before policy when the first bad boundary is not proven.
- Keep each PR to one architectural boundary and one observable result.

## Required verification

Every functional slice needs:

- a regression replay that fails for the original defect;
- focused unit or contract evidence at the owning boundary;
- canonical lineage assertions across adjacent stages;
- architecture ownership checks;
- relevant golden end-to-end scenarios;
- Ruff, mypy and the affected pytest suites;
- explicit confirmation of unchanged out-of-scope behavior;
- live verification only after local and CI evidence passes.

Green CI alone is not architectural proof.  Diagnostics must show the same
canonical identities and records across the full affected chain.

## Current recovery checkpoint — 2026-08-31

Audit of pre-recovery `main` commit
`808c4cf0b81556c8095c228f8bbeb44a43b5084e` identified these repair targets:

Completed and merged through PR #575:

1. live observations reach general Runtime Monitor material classification;
2. MEP emits a complete CandidateSet and non-empty CandidateOutcomeSet before
   ADR-032 Evaluation selects a winner;
3. incumbents and challengers use one fresh snapshot and comparison horizon;
4. equivalent/worse retains the incumbent, invalid loses, and persisted
   financial results are provenance only;
5. diagnostics expose comparable incumbent/challenger outcomes.
6. the Winning Energy Path passes exclusively through the canonical ADR-033
   Execution Plan Builder; source policy and all segment intent are preserved.

The identified recovery checkpoint is merged on `main` as commit
`6e99c82f477fdb31ea613ab23652f9ea7ec99a08`; all three GitHub CI workflows
passed.  Release `2.0.0-dev.207` failed before runtime startup because its
add-on image omitted the new `picot.architecture_ownership` module and
`picot.runtime` package.  Dev.208 packaged those components but then failed at
the ownership guard because Python exposes a module started with `-m` as
`__main__`.  Release `2.0.0-dev.209` makes the executable live-runtime declare
its fixed canonical identity while keeping the ownership registry strict.  It
is the dedicated live-validation release for this boundary recovery.  Do not
start new functional work before its live startup, planning, commitment and
segment-dispatch evidence has been reviewed.
