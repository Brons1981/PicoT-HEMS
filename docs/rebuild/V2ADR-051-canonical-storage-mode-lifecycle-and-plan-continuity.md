# V2ADR-051 — Canonical Storage Mode Lifecycle and Plan Continuity

Status: **Partially superseded by V2ADR-052**

The plan-continuity, persistence and replanning sections of this decision are
superseded by V2ADR-052. The normal delegated lifecycle and BMS-calibration
sections remain accepted where they derive from ADR-001 through ADR-039 and
accepted V2 ADRs. The former reference to ADR-047 is not architectural
authority for the v2 rebuild.

## Context

V2ADR-050 allows timed delegated storage acquisition, but it does not yet
define the complete device-control lifecycle around those acquisition
segments. The current implementation can therefore activate a charge-only
mode without expressing the normal mode before and after the segment.

ADR-027 protects an action after it becomes an Execution Commitment. A future
window that was selected but has not started is not yet represented in the
next Planning Input Snapshot. Repeated rolling-horizon runs can consequently
replace it without accounting for plan stability or switching cost.

Zendure may also start a BMS-owned SOC calibration independently. During that
cycle, observed grid charging is neither a PicoT command nor a manual user
takeover. Treating it as either would make authority and diagnostics wrong.

## Decision

PicoT represents one complete canonical storage-mode lifecycle, explicit BMS
authority evidence, and continuity of a selected future window.

### Normal delegated lifecycle

For the currently validated Zendure/@gielz capability mapping:

- a selected PV-acquisition segment uses `BALANCE_BIDIRECTIONAL` when that
  capability is available, translated by the adapter to `Nul op de meter`;
- outside a selected PV-acquisition segment, the normal baseline is
  `BALANCE_DISCHARGE_ONLY`, translated to `Alleen slim ontladen`;
- `BALANCE_CHARGE_ONLY` remains available for a later explicit purpose such as
  preventing home-battery discharge while an EV is charging; it is not the
  default primitive for ordinary PV acquisition;
- vendor names remain adapter mappings and never enter Core selection rules.

The Execution Plan must cover the due control state, including the transition
out of an ended acquisition segment. Runtime code may not invent a vendor mode
because no segment is due.

### BMS calibration authority

The authoritative Home Assistant calibration signal is captured as immutable
source evidence. While calibration is explicitly active:

- control authority for ordinary storage commands is temporarily `bms`;
- PicoT continues observing, planning and explaining;
- ordinary mode and power dispatch is suppressed;
- observed grid charging is attributed to BMS SOC calibration, not to PicoT
  planning and not to a manual user override;
- after an explicitly inactive, fresh signal is observed, the next normal
  canonical cycle may resume the applicable planned mode.

Missing, stale or unknown calibration evidence never proves calibration.
Unexplained external charging remains diagnosable and is not silently labelled
as cell balancing.

Cell-balance quality sensors are diagnostic context only. They do not grant
BMS authority by themselves.

### Future plan continuity

The selected not-yet-started storage window is recorded as an immutable
`PlannedWindowCommitment` and supplied to every subsequent Planning Input
Snapshot until it starts, is superseded, expires or becomes infeasible.

The record contains at least:

- execution scope and stable commitment identity;
- selected start and end timestamps;
- source policy and canonical primitive;
- expected energy and economic evidence;
- selection timestamp and revision;
- status and explicit replacement reason where applicable.

Evaluation optimises around this prior selection. A challenger may replace it
only when a deterministic accepted condition is met:

- Safety, a hard limit, a User Rule or capability loss requires replacement;
- the retained window is no longer feasible;
- energy reserve is insufficient to wait for it;
- materially changed PV, load or price evidence crosses its accepted
  replanning threshold;
- the challenger improves the accepted total objective by more than the
  configured switching margin.

Equal or immaterial improvement retains the existing window. Near-term,
fragmented rolling quarters do not displace a coherent later window merely
because they remain inside the horizon. As start time approaches, the retained
window's commitment strength may increase, but this never overrides Safety,
hard limits or explicit User Rules.

Every retain or replace result records the incumbent, challenger, objective
difference, applicable margin and normal-language reason.

### Persistence and determinism

Plan continuity is persisted per execution scope. It is not process-local
memory. Restart recovery validates the persisted record against fresh time,
capability and source evidence before reuse. Invalid or unverifiable continuity
fails closed to an uncommitted planning state and is reported.

For identical Planning Input, prior commitment and configuration, Candidate
Evaluation produces the same result. Wall-clock reads and hidden mutable state
inside Core remain forbidden.

## Initial implementation boundary

This slice includes:

1. NOM as the ordinary PV-acquisition primitive when bidirectional delegated
   capability is available;
2. the canonical baseline transition to discharge-only outside the selected
   PV window;
3. explicit Zendure SOC-calibration evidence and BMS dispatch suppression;
4. persisted future-window continuity with a deterministic replacement margin;
5. traceable Dutch diagnostics for activation, retention, replacement and
   calibration hold.

This slice does not include EV detection, explicit grid charging, fast
charge/discharge modes, weather/temperature inputs or a new fiscal objective.

## Relationship to accepted decisions

- ADR-015 remains authoritative for generic Execution Primitives.
- ADR-027 remains authoritative once execution has started; this decision adds
  continuity before start.
- ADR-034 remains authoritative for material-change replanning.
- User/manual authority must be derived from an accepted v2 decision based on
  ADR-001 through ADR-039; ADR-047 is not authoritative for the v2 rebuild.
- V2ADR-050 remains authoritative for timed delegated storage candidates and
  adapter separation.

## Core principle

> PicoT selects the right complete storage-control lifecycle, respects a
> proven BMS calibration, and changes a reserved future window only for a
> traceable material improvement or higher-priority necessity.
