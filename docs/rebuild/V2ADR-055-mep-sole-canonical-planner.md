# V2ADR-055 — MEP as Sole Canonical Planner

Status: **Accepted**

Date: 2026-08-28

## Controlling decisions

ADR-001 through ADR-037 and the accepted V2 ADR series are authoritative for
this decision. The legacy ADR-038 and higher files are not part of the active
architecture baseline. A V2 ADR may extend, but may not contradict, ADR-001
through ADR-037.

This decision ends the temporary three-planner comparison described in
V2ADR-054. CP and EP are removed from the live runtime. MEP is the sole planner
and the sole source of plans admitted to the canonical pipeline.

## Planner responsibility

MEP owns planning and nothing downstream of planning. It consumes one immutable
`PlanningInputSnapshot` and produces complete, physically coherent candidate
plans. It does not consume, restore, compare or depend on CP or EP output.

A deadline derived by the removed CP Candidate Engine is CP output and is not
part of MEP's Planning Input. MEP derives physically feasible timing inside its
own planning responsibility. Continuity of an already selected feasible plan
is enforced by Evaluation and the canonical Plan Store, not by importing a CP
deadline into MEP.

The validated EP physical planning behaviour is retained inside MEP as its
native physical planning logic. That retained behaviour is not a second planner
and has no separate runtime, worker, state, persistence or execution authority.
MEP extends it with the accepted market routes and settlement evidence.

CP and EP may remain represented only by frozen regression fixtures or incident
replays. They do not run in production, publish dashboard plans or influence
MEP.

## Canonical pipeline ownership

Every planner cycle follows the single canonical pipeline:

1. one immutable input snapshot;
2. evidence-only opportunities;
3. MEP candidate generation;
4. complete `EnergyPath` construction;
5. physical and financial simulation outcomes;
6. evaluation and selection of exactly one winner;
7. durable canonical plan persistence;
8. canonical execution intent;
9. adapter-only vendor translation and dispatch.

MEP may not select a winner in a private execution runtime. Evaluation is the
only owner of candidate comparison and challenger-versus-committed-plan
selection. The canonical Plan Store is the only owner of plan continuity,
restart restoration and commitment persistence. Execution may enforce safety
but may not invent, replace or economically re-rank plans.

## Market-route boundaries

Market prices and forecast intervals become opportunity evidence before MEP
uses them. MEP may generate complete necessary-acquisition, negative-price,
storage-export and linked trading candidates. Raw price scanning may not create
a second selection authority.

Every market candidate retains complete energy lineage, physical feasibility,
signed settlement and the V2ADR-054 admission evidence. Necessary grid charging
for a proven energy deficit remains distinct from optional trading.

## Execution and vendor boundaries

There is one execution authority switch for the whole canonical pipeline:
`execution_mode`, with values `observer` or `live`. No planner-specific or
canary-specific execution authority exists.

Core planning contracts use canonical intents only. Zendure or Home Assistant
mode names are translated solely by the adapter. Vendor mode strings may not
appear in MEP planning policy.

## Removal requirements

The promotion removes:

- the CP runtime planner and its execution authority;
- the EP observer runtime and worker;
- the private MEP worker-to-execution path;
- planner-comparison persistence and dashboard presentation;
- separate CP, EP, MEP and canary execution-mode configuration;
- private MEP commitment, challenger and dispatch decisions.

Historical diagnostic data may remain readable, but no removed component may
be instantiated in the live runtime.

The dashboard projects the selected plan directly from the canonical
`ExecutionPlanSet`. Optional or removed CP/EP outcome projections may enrich
historical diagnostics, but their absence may not hide an available MEP plan or
its exact future segments.

## Acceptance evidence

Before live release, tests must prove:

1. MEP preserves the frozen EP physical regression outcomes when no optional
   market route is decisive;
2. exactly one planner run and one canonical execution runtime exist;
3. MEP does not contain a private execution or commitment layer;
4. one `execution_mode` option controls observer versus live authority;
5. the planner contains no vendor mode policy;
6. MEP timing and incumbent-first Evaluation prevent a later cheap interval
   from replacing the currently committed feasible plan when that alternative
   cannot satisfy the MEP-owned physical horizon;
7. the canonical Plan Store persists and restores the selected plan, and only
   Evaluation can replace it using material challenger evidence;
8. restart, stale evidence, missing feedback, BMS protection and user override
   continue to fail closed;
9. the existing nine-stage diagnostic projection observes the canonical path
   without duplicate planning calculations;
10. planner runtime remains measured and bounded after removal of CP and EP.

## Core principle

PicoT has one planner, one canonical pipeline and one execution authority. Each
layer owns exactly one decision responsibility; a defect is corrected in that
owner rather than compensated for in another layer.
