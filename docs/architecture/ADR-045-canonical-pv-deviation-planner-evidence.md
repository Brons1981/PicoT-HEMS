# ADR-045 — Canonical PV Deviation as Planner Evidence

**Status:** Proposed  
**Date:** 2026-08-13

## Context

PicoT already records Solcast expected PV and GoodWe actual PV and contains an observation-only deviation evaluator. That evaluator still compares power samples and therefore remains sensitive to short cloud passages, inverter reporting jitter and sample timing.

ADR-039 now defines one canonical PV energy timeline and the live implementation integrates actual GoodWe production as measured energy over canonical quarter-hour boundaries. ADR-034 already defines the only accepted route from a material forecast change to replanning: an observation producer marks an accepted threshold/version transition as crossed, the Runtime Monitor classifies it, and a fresh atomic Planning Input Snapshot is required.

The remaining architectural gap is whether and how realised PV deviation may become authoritative planner evidence instead of remaining diagnostics-only.

## Decision

PicoT treats PV forecast-versus-actual deviation as planner-authoritative evidence only when the comparison is based on energy over the same canonical time interval.

Instantaneous GoodWe power versus instantaneous Solcast power remains diagnostic evidence only and may never directly request replanning, alter future forecast confidence, select a Candidate or change a device mode.

The authoritative PV-deviation producer compares:

- canonical actual PV energy derived under ADR-039;
- the Solcast forecast energy that applied to exactly the same interval;
- identical interval start and end boundaries;
- explicit evidence coverage and source references.

If interval coverage is incomplete, source semantics are ambiguous, or a reliable same-interval forecast cannot be reconstructed, no authoritative deviation is produced.

## Material-change ownership

The PV-deviation producer owns the numeric threshold used to decide whether a canonical energy deviation is material. ADR-034 remains authoritative for runtime classification and replanning orchestration and does not invent a tolerance.

The initial implementation may reuse the existing accepted live PV-deviation threshold configuration, but it must apply that threshold to canonical energy deviation rather than instantaneous power deviation.

A material canonical deviation produces a forecast-change observation marked as having crossed its accepted threshold. It does not execute a mode change.

The normal chain is:

```text
canonical actual-vs-forecast PV energy
→ material-change evidence
→ Runtime Monitor
→ REPLAN_REQUIRED
→ fresh Planning Input Snapshot
→ normal Planner pipeline
```

No separate replan engine, PV planner or direct control path is introduced.

## Confidence handling

This ADR authorises canonical PV deviation to be evidence used by the existing planner confidence/material-change process, but does not authorise arbitrary multiplication or scaling of future Solcast values.

A future forecast-confidence adjustment method must be deterministic, versioned and traceable. Until such a method is implemented, material canonical deviation may request replanning while the fresh Planner Run continues to consume the newest validated forecast and actual PV timeline under ADR-039.

Actual realised PV energy for elapsed time remains authoritative and replaces forecast for that elapsed time under ADR-039.

## Interval rules

The authoritative comparison uses canonical quarter-hour energy intervals.

A comparison interval is eligible only when:

- actual GoodWe energy coverage satisfies the accepted ADR-039 integration contract;
- the corresponding Solcast forecast energy is available for the same boundaries;
- expected energy is sufficient for a meaningful relative comparison;
- no long measurement gap has been silently interpolated;
- both source identities and method versions are traceable.

Partially elapsed quarters may be retained for diagnostics, but the initial planner-authoritative decision is made only from sufficiently covered canonical energy evidence. Short instantaneous spikes and cloud dips therefore cannot independently trigger a replan.

## Relationship to existing observer-only logic

The existing power-based PV deviation fields remain useful diagnostics during migration, but they cease to be the authoritative source for `pv_deviation_replan_candidate` once the canonical energy producer is connected.

`observer_only` is removed only for the canonical energy-based deviation path. It remains true for the old instantaneous comparison until that path is retired.

There must be exactly one authoritative PV-deviation replan signal.

## Explainability

For every authoritative PV-deviation decision PicoT records at least:

- canonical interval start and end;
- expected PV energy;
- actual PV energy;
- absolute and relative deviation;
- threshold used;
- coverage status;
- actual and forecast evidence references;
- integration/method versions;
- whether the threshold was crossed;
- resulting material-change/replan classification.

## Non-goals

This ADR does not:

- directly switch Zendure mode;
- create a second Planner;
- create a second Runtime Monitor;
- resample PV inside Candidate Generation;
- replace ADR-039 actual/forecast ownership;
- invent forecast values when data is missing;
- authorise arbitrary future-PV derating or amplification.

## Relationship to existing ADRs

- ADR-028 remains authoritative for fresh atomic Planning Input Snapshots.
- ADR-034 remains authoritative for material-change classification, five-second stabilisation and replanning.
- ADR-037 remains authoritative for projected household/storage energy requirements.
- ADR-039 remains authoritative for canonical actual and forecast PV energy over time.
- ADR-040 remains authoritative for validated observation-source ingestion.
- ADR-044 remains authoritative for downstream timed Candidate selection from canonical planner evidence.

## Consequences

Positive:

- clouds and short power spikes no longer directly destabilise the Planner;
- realised PV can become genuine Planner evidence;
- material PV errors are detected on the same energy basis used by the household balance;
- replanning remains on the existing ADR-034 route;
- evidence stays deterministic and exportable.

Costs:

- same-interval historical forecast evidence must be retained or reconstructable;
- insufficient coverage must fail closed;
- confidence adjustment beyond replan signalling requires a separate versioned implementation method.

## Core principle

> PicoT may react to PV forecast error only after reality and forecast have been reconciled as energy over the same canonical interval; instantaneous power mismatch is diagnostic, not a planning decision.