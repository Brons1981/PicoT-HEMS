# PicoT HEMS Closed-Loop Readiness Audit — 2026-08-12

## Purpose

Assess how close current `main` is to a real closed loop:

```text
observe → normalize → snapshot → plan → evaluate → commit → execute → observe result → replan
```

The audit also checks recent Solcast/PV-energy work and direct source usage against accepted architecture.

## Executive conclusion

PicoT Core is substantially ahead of the old project-status files. The deterministic planning and execution contracts are largely implemented and covered by CI. The primary remaining gap to real autonomous operation is not Candidate/Evaluation logic; it is live integration wiring between authoritative Home Assistant observations, atomic snapshot construction, planner invocation, execution-plan dispatch and runtime feedback.

## Readiness by stage

### 1. Observe — PARTIALLY LIVE

Present:

- direct Home Assistant adapters/observers exist for GoodWe, Solcast, Zendure and household/grid state;
- live PV deviation/recovery was validated in Home Assistant;
- diagnostic and planner-timeline entities exist;
- Runtime Monitor contracts and tests exist.

Gap:

- there is no single general live observation/snapshot pipeline that supplies every required planner-domain input atomically from selected authoritative mappings;
- Home Assistant subscriptions and source-to-RuntimeObservation wiring are not yet the accepted complete runtime path.

### 2. Normalize to canonical domain data — PARTIALLY IMPLEMENTED

Present:

- vendor-specific Home Assistant values are normalized by adapters before Core use;
- canonical `HouseholdState`, `CurrentStorageState`, capability snapshots and PV-energy timeline contracts exist;
- ADR-039 prevents elapsed PV forecast from remaining reality once measured production exists.

Gap:

- normalization ownership is not yet uniformly enforced across all physical measurements;
- the rule that `sensor.picot_*` mirrors must never become Core input is operationally documented but not yet Accepted architecture.

### 3. Atomic Planning Input Snapshot — CONTRACT PRESENT, LIVE PROVIDER GAP

Present:

- immutable `PlanningInputSnapshot` and versioning contracts;
- current storage state and PV-energy timeline can be attached to planning evidence;
- Runtime Monitor requires a fresh snapshot after material change.

Gap:

- a production Home Assistant snapshot provider that atomically captures the selected live inputs and invokes the planner is not yet the closed live path.

### 4. Project household/storage need — IMPLEMENTED

Present:

- projected household energy balance;
- relative evidence-confidence policy;
- `StorageEnergyRequirement` derivation;
- PV-only storage feasibility;
- technical storage recoverability;
- explicit PV-only versus PV-preferred/grid-allowed source policy.

ADR-037/038/039 acceptance tests cover the integrated storage-requirement path.

### 5. Generate and evaluate plans — IMPLEMENTED CORE

Present:

- Opportunity Engine;
- Candidate Engine and complete Energy Paths;
- grid-supported Candidate generation when PV-only is insufficient;
- Candidate Outcome derivation;
- deterministic Evaluation Engine;
- end-to-end ADR-037 pipeline tests including `NO_VALID_CANDIDATE` handling.

Known boundary:

- comparable projected objective values such as full financial result, self-consumption and net-balance remain unavailable where the Energy Path does not yet contain the physical projection needed to derive them. PicoT deliberately does not invent proxies.

### 6. Commit winner to execution plans — IMPLEMENTED CORE

Present:

- deterministic Winning Energy Path to scope-specific immutable Execution Plans;
- commitment and dynamic-power-allocation contracts;
- due-segment selection and capability validation.

### 7. Dispatch to Home Assistant — IMPLEMENTED COMPONENT, NOT FULLY WIRED

Present:

- Home Assistant command mappings;
- generic Execution Primitive translation;
- DRY_RUN and LIVE dispatch modes;
- explicit transport gate;
- support includes `CHARGE_AT_POWER` and accepted balance-mode primitives in current adapter code.

Gap:

- the live planner output is not yet the continuously connected source of real Zendure commands in one autonomous closed loop.

### 8. Observe result and replan — PARTIALLY IMPLEMENTED

Present:

- Runtime Monitor and immutable runtime observations;
- material-change classification;
- five-second stabilisation;
- fresh-snapshot-required signalling;
- prior live Plan Review/deviation observation with anti-flip behaviour.

Gap:

- execution dispatch result → authoritative runtime observation → fresh snapshot → full planner rerun is not yet one continuously wired production path.

## Architecture consistency findings

### Solcast / ADR-039

No fundamental conflict found with the accepted pipeline. ADR-039 strengthens ADR-017 by converting PV to energy over time and replacing elapsed forecast with measured production. It also supports ADR-038/037 by ensuring one canonical PV-energy representation is reused rather than recalculated independently.

### Direct physical source usage

The accepted Project Constitution and ADR-001 remain correct: the Planner must never depend directly on Home Assistant entity IDs or vendor integrations.

Live validation established a separate input-boundary rule:

```text
physical HA source → input adapter/mapping → canonical immutable domain data → Core
```

not:

```text
physical HA source → sensor.picot_* mirror → Core
```

The 2026-08-10 development log already records this as a hard runtime invariant, but it is not yet an Accepted ADR. ADR-040 is therefore proposed with exactly this responsibility.

### Duplicate calculation risk

The audit found no reason to introduce additional parallel planning layers. Existing canonical records should remain single owners of their physical calculations. In particular, CurrentStorageState, PVEnergyTimeline and ProjectedHouseholdEnergyBalance should be produced once per Planner Run and reused downstream.

## Practical distance to autonomous observe-plan-control

The remaining work is best described as integration slices rather than a new planner redesign:

1. accept and implement ADR-040 authoritative source ingestion;
2. build the live Home Assistant atomic snapshot provider over selected physical mappings;
3. wire fresh snapshot → existing planner pipeline → winning Energy Path → Execution Plan;
4. connect controlled Execution Plan output to the existing Home Assistant adapter/dispatcher, initially DRY_RUN and then explicitly gated LIVE;
5. wire dispatch/observed device outcome back into Runtime Monitor and fresh-snapshot replanning;
6. run a controlled end-to-end live validation with full traceability before autonomous operation is considered ready.

## Phase conclusion

PicoT remains ALPHA and is not production ready. Architecturally it is no longer merely in Discovery/Canonical Data Model work. It is in late Phase 3 with a substantial implemented Core and a remaining emphasis on authoritative observation ingestion and closed-loop Home Assistant integration/validation.
