# PicoT HEMS Canonical Pipeline Contract

Status: **FROZEN REBUILD CONTRACT — Phase A**

Basis: Accepted ADR-001 through ADR-039 and `ARCHITECTURE_MAP.md`.

This document does not redesign PicoT. It converts the already accepted architecture into the implementation and live-validation contract for the clean rebuild.

## Non-negotiable rules

1. **One canonical fact → one owner.**
2. **One canonical derivation → one owner.**
3. Downstream stages may consume/reference canonical facts; they may not silently reinterpret, replace or mutate them.
4. A derived value must remain traceable to its canonical source facts and the versioned derivation that created it.
5. **No parallel path to the same result.** New functionality extends the canonical pipeline; it never creates a second planner, observer-planner, price planner, battery planner, ADR-specific runtime, or alternative execution path.
6. The atomic `PlanningInputSnapshot` is immutable for the entire Planner Run. It is never progressively enriched or changed by downstream stages.
7. Each stage may create only outputs owned by that stage.
8. A downstream stage may not suppress data merely because it considers that data irrelevant to another stage.
9. Every Planner Run has one stable `run_id`; all stage outputs and records reference that run.
10. Every stage must be observable in the live dashboard before additional intelligence is added to the next stage.
11. A stage is not complete because unit tests are green. It is complete only when its canonical output is produced through the single live pipeline and is end-to-end traceable.
12. ADR-040 and later are outside the Phase A architectural basis. They may be reconsidered only after the ADR-001–039 pipeline is working and proven.

## Canonical nine-stage dashboard pipeline

The Architecture Map remains authoritative for Core boundaries. For rebuild validation it is presented as nine fixed dashboard stages:

```text
1  Planning Input
        ↓
2  Opportunity Engine
        ↓
3  Candidate Engine
        ↓
4  Evaluation Engine
        ↓
5  Execution Plan Builder
        ↓
6  Execution Engine
        ↓
7  Execution Primitive
        ↓
8  Device Adapter
        ↓
9  Vendor Command / Observed Result
```

`Planner Strategy`, confidence, Runtime Governance, Safety/hard constraints, commitments, User Rules, diagnostics and traceability are cross-cutting contracts. They do not become alternative orchestration stages.

The PicoT Core pipeline is architecturally closed through `ExecutionPrimitiveRequest`; Device Adapter and vendor command/result are shown as stages 8–9 because the live rebuild dashboard must prove the complete physical closed loop.

---

## 1 — Planning Input

**Owner:** Planning Input / snapshot assembly.

**Allowed input:** validated canonical observations, persistent logical capability mappings, forecasts, Household State, current storage state, active Planner Strategy, applicable User Rules/commitments, runtime pressure and required version references.

**May do:** validate, normalise through the designated owner, assemble and freeze one atomic `PlanningInputSnapshot`; expose freshness/confidence/version metadata already owned by the relevant canonical contracts.

**Owns/creates:** `PlanningInputSnapshot` and its snapshot identity/version references.

**Must not:** plan; select an Opportunity, Candidate or device action; read vendor-specific entities inside Planner code; change the snapshot after the Planner Run starts; silently substitute unavailable sources; invent confidence.

**Dashboard minimum:** `run_id`, `snapshot_id`, captured-at, source/mapping versions, strategy version, capability snapshot references, storage state, forecast references, runtime pressure, snapshot completeness, blockers.

**Primary ADRs:** ADR-001–014, ADR-017, ADR-025, ADR-028, ADR-029, ADR-030, ADR-034, ADR-038, ADR-039.

## 2 — Opportunity Engine

**Owner:** Opportunity Engine.

**Allowed input:** immutable `PlanningInputSnapshot` and canonical evidence available to this stage.

**May do:** derive objective, evidence-backed Opportunities and constraints; describe price/PV/energy timing opportunities; attach evidence and confidence according to canonical contracts.

**Owns/creates:** `OpportunitySet` and Opportunity records.

**Must not:** select a device; assign execution power; create an Energy Path; select a winner; remove an alternative because another layer might prefer a different strategy.

**Dashboard minimum:** opportunity-set id, count, each opportunity type/window/value, evidence references, confidence, constraints, exclusions with explicit contractual reason.

**Primary ADRs:** ADR-017, ADR-023, ADR-025, ADR-036, ADR-037, ADR-039.

## 3 — Candidate Engine

**Owner:** Candidate Engine.

**Allowed input:** immutable `PlanningInputSnapshot`, `OpportunitySet`, immutable logical `CapabilitySnapshotSet`, Planner Strategy guidance and accepted scenario templates.

**May do:** hard technical reduction explicitly allowed by the ADRs; controlled branching; construct a small, diverse set of complete technically supported household Energy Paths; attach capability/evidence references.

**Owns/creates:** `CandidateSet`, Candidate records and Candidate `EnergyPath` records.

**Must not:** perform final economic/strategic winner selection; mutate canonical facts; create vendor commands; reinterpret capabilities; remove a Candidate on an evaluation criterion owned by Evaluation unless an accepted Candidate-reduction contract explicitly permits it.

**Dashboard minimum:** candidate-set id/count, candidate ids/families, Energy Path ids, capability roles/versions, opportunity references, reduction reason, completeness/technical-validity status.

**Primary ADRs:** ADR-017, ADR-024, ADR-025, ADR-029, ADR-030, ADR-031, ADR-037.

## 4 — Evaluation Engine

**Owner:** Evaluation Engine.

**Allowed input:** immutable Candidates and their canonical simulated/derived outcomes plus immutable Planner Strategy.

**May do:** compare supplied Candidate outcomes in strategy order; apply deterministic tie-breaks; record every comparison; select exactly one existing Candidate when selection is possible.

**Owns/creates:** `CandidateOutcomeSet` where evaluation contract assigns outcome representation, `EvaluationRecord`, Winning Candidate reference and Winning Energy Path reference.

**Must not:** create a new Candidate; change an Energy Path; alter canonical input facts; use hidden aggregate scoring; add a device action that was not in the winning path.

**Dashboard minimum:** evaluated candidates, available/unavailable outcomes, objective order, comparison results, tie-breaks, winner id, winning Energy Path id, explicit no-winner/blocker reason.

**Primary ADRs:** ADR-017, ADR-025, ADR-026, ADR-032, ADR-037.

## 5 — Execution Plan Builder

**Owner:** Execution Plan Builder.

**Allowed input:** successful immutable `EvaluationRecord`, Winning Candidate and Winning Energy Path plus the references required by the accepted execution-plan contract.

**May do:** deterministically convert the Winning Energy Path into an atomic `ExecutionPlanSet`; split it into scope-specific immutable plans and time-bound segments.

**Owns/creates:** `ExecutionPlanSet`, `ExecutionPlan`, `ExecutionPlanSegment`.

**Must not:** reinterpret optimisation; change timing/energy intent to improve the result; create a different energy decision; introduce vendor-specific commands.

**Dashboard minimum:** plan-set id, plan count, scope, segment ids, start/end, intended primitive/behaviour, power/energy parameters, winning-path reference, commitment/flexibility metadata.

**Primary ADRs:** ADR-016, ADR-027, ADR-033.

## 6 — Execution Engine

**Owner:** Execution Engine.

**Allowed input:** immutable due Execution Plan segments, current logical capability conditions, commitments, hard constraints/Safety state and accepted execution fallback policy where applicable within ADR-001–039.

**May do:** select due segments; validate current capability/constraint conditions; produce explicit validation outcomes; emit an approved vendor-independent `ExecutionPrimitiveRequest`; record execution lifecycle state.

**Owns/creates:** `CommandValidationOutcome`, execution lifecycle/record data and approved `ExecutionPrimitiveRequest` handoff.

**Must not:** re-optimise; choose a better price window; modify the Winning Energy Path; create a new energy decision; emit vendor commands directly.

**Dashboard minimum:** due segment, validation inputs/references, authority/commitment state, validation result, primitive request id or explicit no-dispatch/replan reason.

**Primary ADRs:** ADR-015, ADR-016, ADR-027, ADR-029, ADR-034.

## 7 — Execution Primitive

**Owner:** generic Execution Primitive contract / validated primitive request boundary.

**Allowed input:** only an Execution Engine-approved primitive request.

**May do:** represent desired generic energy behaviour with explicit scope, parameters, timing and provenance.

**Owns/creates:** canonical `ExecutionPrimitiveRequest` representation handed to the adapter boundary.

**Must not:** contain vendor entity ids, service names, Zendure/Home Assistant modes or other integration-specific semantics; make planning decisions.

**Dashboard minimum:** primitive request id/type, logical scope, requested parameters, originating plan/segment/evaluation/run references, validation status.

**Primary ADRs:** ADR-015, ADR-016, ADR-035.

## 8 — Device Adapter

**Owner:** selected Device Adapter / Home Assistant adapter mapping.

**Allowed input:** one validated generic `ExecutionPrimitiveRequest` plus one explicit versioned adapter mapping.

**May do:** deterministic translation to the vendor/integration-specific service call or command; use identical translation for dry-run and live operation.

**Owns/creates:** adapter translation record / concrete service-call representation.

**Must not:** change requested energy intent; optimise; choose another device because it appears preferable; silently remap capabilities; feed vendor semantics back into Core planning.

**Dashboard minimum:** adapter id/version, mapping id/version, primitive request reference, translated target/action/parameters, dry-run/live gate, translation result.

**Primary ADRs:** ADR-001, ADR-004, ADR-007, ADR-009, ADR-010, ADR-011, ADR-015, ADR-035.

## 9 — Vendor Command / Observed Result

**Owner:** vendor/integration boundary for command dispatch; canonical observation owner for subsequent observed facts.

**Allowed input:** adapter-produced concrete command after live dispatch gating.

**May do:** dispatch the exact translated command; record acknowledgement/failure separately; ingest resulting physical observations through the appropriate canonical observation path for a future fresh snapshot/replan.

**Owns/creates:** vendor command/acknowledgement record and observed-result references. A physical observation does not mutate the active Planner Run; it may become evidence for a future snapshot.

**Must not:** rewrite the active plan; alter previous canonical facts; bypass Runtime Monitor/replanning; treat acknowledgement as proof of physical behaviour without observation evidence.

**Dashboard minimum:** command id, target/action/parameters, dispatch timestamp, acknowledgement/result, observed behaviour references, deviation/replan indication, next-snapshot reference when created.

**Primary ADRs:** ADR-002–012, ADR-015, ADR-028, ADR-034, ADR-035.

---

## Cross-cutting ownership rules

### Planner Strategy

Owned by the accepted Objective/Strategy contracts. It guides Opportunity, Candidate and Evaluation behaviour but is not a pipeline stage and may not be locally reinterpreted by a stage.

### Confidence

Confidence belongs to the canonical fact/evidence contract that derives it. A downstream layer consumes the confidence value; it may not replace it with an arbitrary value such as `1.0`. A downstream layer may create a new confidence only when an accepted contract explicitly defines that derived confidence and its evidence.

### Safety and hard constraints

Safety, phase-current limits, voltage/fuse limits, capability health and hardware limits override optimisation. Enforcement must occur at the contractually designated boundary; other stages may consume their state but may not redefine the limits.

### Commitments

Execution commitments are canonical execution state. Planner Runs optimise around them according to ADR-027. They are not reconstructed independently by Candidate or Evaluation logic.

### Runtime governance

One full Planner Run at a time. Material change produces a replan request; after the fixed five-second stabilisation interval a new atomic snapshot starts a new run. Existing snapshots are never patched with new live data.

## End-to-end lineage contract

Every live run must be traceable through stable immutable identifiers. At minimum:

```text
run_id
  └─ PlanningInputSnapshot.snapshot_id
      ├─ CapabilitySnapshotSet / mapping versions
      └─ OpportunitySet.opportunity_set_id
          └─ CandidateSet.candidate_set_id
              └─ Candidate.candidate_id
                  └─ EnergyPath.energy_path_id
                      └─ EvaluationRecord.evaluation_id
                          └─ Winning Candidate / EnergyPath refs
                              └─ ExecutionPlanSet.plan_set_id
                                  └─ ExecutionPlan.plan_id
                                      └─ ExecutionPlanSegment.segment_id
                                          └─ ExecutionPrimitiveRequest.request_id
                                              └─ Adapter translation/command id
                                                  └─ Execution/observed-result id
```

For each derived canonical record the trace must expose:

- `created_by_stage`;
- `derived_from` references;
- `method/contract version` where derivation occurs;
- source mapping/version references where relevant;
- `run_id`;
- creation timestamp;
- immutable payload identity/hash where practical.

### Lineage status

The dashboard/test harness must be able to classify relevant lineage as:

- **UNCHANGED** — the canonical fact is referenced without reinterpretation;
- **DERIVED** — a new canonical value was created by the designated owner with explicit `derived_from` provenance;
- **NOT_CONSUMED** — a stage did not require the fact; this is informational and must not remove the fact from the immutable run context;
- **LINEAGE_BREAK** — a required source/reference disappeared;
- **ILLEGAL_MUTATION** — a canonical fact changed without a new authoritative observation or an explicitly owned derivation.

`LINEAGE_BREAK` and `ILLEGAL_MUTATION` are rebuild-gate failures.

## Dashboard contract

The rebuild dashboard always contains the same nine stage cards. Cards are never added to test new planner functionality.

Every card has a common header:

```text
stage_status
run_id
input_reference(s)
output_reference(s)
created_at
confidence/evidence status where applicable
blocker/error
lineage_status
```

The body contains the stage-specific minimum fields listed above and grows only when intelligence/functionality belonging to that stage is implemented.

A feature is not accepted until:

1. its value appears in the owning stage card;
2. required downstream references remain traceable;
3. no unrelated stage mutated/reinterpreted the value;
4. the same `run_id` can be followed through all applicable cards;
5. the complete canonical pipeline remains operational without a parallel test path.

## Phase A completion gate

Phase A is complete when this contract is frozen before rebuild implementation starts.

No production intelligence is implemented in Phase A.

Phase B starts by constructing the minimal end-to-end canonical pipeline and nine-card dashboard against this contract. The first valid run may intentionally contain empty Opportunities, a baseline/no-action path and no physical dispatch; it must nevertheless prove the single canonical route and complete lineage.
