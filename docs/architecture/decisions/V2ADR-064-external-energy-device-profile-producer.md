# V2ADR-064 — External energy-device profile producer and optional card boundary

Status: **Accepted**

Date: 2026-09-06

## Context

ADR-019 defines Managed Energy Profiles for known future energy impacts. ADR-037
keeps those impacts separate from the ordinary household-load forecast and
forbids double counting. V2ADR-001 requires every external Home Assistant fact
to cross one explicit ingestion boundary. None of those decisions specifies
how a small, independently deployable application may learn device behaviour
without making PicoT dependent on that application.

User-managed devices such as a dryer, washing machine or EV charger can expose
power and energy through Home Assistant entities. Their recurring load shape is
useful planning evidence, but collection and refinement of that evidence is not
a planning responsibility. It must not increase the authority, availability
requirements or failure surface of MEP.

## Decision

### Independent producer

`PicoT Energy Devices` is an independent, read-only Home Assistant add-on. It
knows only:

- the entity identifiers explicitly registered by the user;
- the user-supplied display name;
- observed power and optional cumulative-energy values;
- its own sampling, session and profile history.

It does not know PicoT's installation topology, PV forecast, battery, tariff,
User Rules, Opportunities, Candidates, MEP plans, commitments or execution
state. It never switches a device and never selects, ranks or executes a plan.

### Neutral energy-device card

The producer exposes one versioned catalog containing neutral energy-device
cards. A card describes observation evidence and may contain:

- a stable card and device identifier;
- user-visible name and source entity identifiers;
- availability, active state and observation time;
- expected power, duration, energy and an optional bounded load shape;
- confidence, sample count and completed-session count;
- schema, method and profile revision.

A device name or category is metadata only. PicoT may not invent an energy
profile from a label such as `dryer`, `washing_machine` or `ev_charger`.

The producer publishes the catalog as one external Home Assistant source. It
does not publish PicoT Core objects. PicoT has one optional source adapter that
validates the neutral contract and projects accepted cards into its dashboard.

### Explicit user placement

Discovery grants no planning authority. Every newly discovered card is shown
as available in PicoT, but remains unselected. Only the user may create a
time-bound placement on the PicoT planning timeline.

A placement records the selected card, start, end and user action. It is a
Planning Hint candidate, not a command and not proof that the appliance will
run. A separate future acceptance slice may translate sufficiently reliable
placements into canonical Managed Energy Profiles. Until that slice is
accepted, placements remain observer-only and cannot alter Opportunities,
Candidates, MEP, commitments or execution.

### PicoT remains independently correct

The producer is always optional. Missing, unreachable, stale, malformed or
empty catalogs result in an explicit unavailable catalog and zero accepted
cards. This condition:

- does not block snapshot assembly or a Planner Run;
- does not change the household-load fallback;
- does not invalidate or retain a commitment;
- does not request replanning;
- does not affect execution or safety.

PicoT must continue to produce the same correct plan it would have produced if
the add-on had never been installed. Device cards may improve future forecast
quality and reduce avoidable replanning; they may never become a correctness or
availability dependency.

### One-way authority and materiality

The catalog flow is one way:

```text
user-selected HA entities
→ PicoT Energy Devices observations and learned cards
→ neutral catalog source
→ optional PicoT catalog adapter
→ explicit user timeline placement
```

The producer cannot emit `REPLAN_REQUIRED` or classify a change as material.
If placements later become planning input, PicoT's canonical observation
producer compares admitted expectations with reality. ADR-034 and V2ADR-063
remain the sole materiality and replanning contracts.

### No double counting

Before a card may influence MEP, the household-load forecast must have a
residual baseline for registered devices:

```text
whole-house historical load
- time-aligned registered-device observations
= residual household baseline

residual household baseline
+ explicitly placed future device profiles
= canonical household planning requirement
```

The producer supplies only device evidence. PicoT owns subtraction,
time-alignment, confidence propagation and the final canonical forecast. If
safe subtraction cannot be proved, the placement remains observer-only.

### Persistence, boundedness and diagnostics

The producer owns its registry, samples, sessions and learned profiles. It uses
bounded catalog payloads and does not copy raw history into each PicoT snapshot.
PicoT persists only its catalog status and user placements. Producer diagnostics
remain exportable independently so a producer defect can be diagnosed without
changing MEP.

Learning and compaction are lower priority than live sampling. Resource
evidence must expose sampling duration, database size, card count and producer
errors. PicoT runtime evidence continues to expose its own process cost; total
NUC qualification considers both processes.

## Compatibility

PicoT defaults to the catalog entity
`sensor.picot_energy_devices_catalog`. The binding is optional and may be
changed or left unavailable. Existing installations, snapshots, plans and
commitments are valid without migration.

Catalog schema versions are fail-closed: an unsupported catalog is visible as
unavailable and contributes no cards. Previously accepted cards are not used as
live planning facts merely because the producer disappears.

## Verification

Tests must prove that:

1. PicoT plans normally when the catalog entity does not exist;
2. malformed and unsupported catalogs are isolated without a Planner failure;
3. a newly published card becomes selectable without a Planner Run;
4. discovery alone never changes planning input or execution;
5. only explicit user action creates or removes a timeline placement;
6. placements survive a PicoT restart and remain observer-only;
7. the producer cannot call Home Assistant switch services;
8. samples form bounded, traceable session profiles;
9. source, schema, freshness, confidence and revision remain visible;
10. later planning activation cannot double count registered device energy.

## Relationship to existing ADRs

- ADR-019 owns Energy Profile semantics and learning boundaries.
- ADR-021 owns layer isolation and diagnostic bypass.
- ADR-022 permits a distinct producer but forbids a parallel planning engine.
- ADR-028 owns resource budgets and protects planning above learning.
- ADR-034 owns Runtime Monitor classification and fresh replanning.
- ADR-037 owns household requirements and the no-double-counting rule.
- V2ADR-001 owns single-ingestion authority.
- V2ADR-055 keeps MEP the sole canonical planner.
- V2ADR-063 owns committed-trajectory materiality thresholds.

## Core principle

> An energy-device card may improve PicoT only after explicit user placement;
> its producer is never required for PicoT to plan, remain safe or execute
> correctly.
