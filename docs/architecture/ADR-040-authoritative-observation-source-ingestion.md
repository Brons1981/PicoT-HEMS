# ADR-040 — Authoritative Observation Source Ingestion Contract

**Status:** Accepted  
**Date:** 2026-08-12

## Context

PicoT Core and the Planner are vendor-independent. The Project Constitution and ADR-001 require the Planner to consume logical capabilities and canonical planning-domain records rather than Home Assistant entity identifiers or vendor integrations directly.

Live validation during the 2026-08-10 test phase showed that realtime planning and replanning behave more reliably when PicoT reads the already selected authoritative Home Assistant source entities directly, such as Shelly, Zendure, GoodWe or Solcast source entities, rather than first mirroring those values into intermediate `sensor.picot_*` entities and then reading those mirrors back into Core.

Intermediate mirror entities can introduce unnecessary update latency, timestamp skew, temporary availability differences and duplicated calculations. They also blur ownership: a copied value may look PicoT-owned even though the authoritative observation belongs to an external source.

The development log already records the operational invariant that PicoT planner/runtime uses real selected Home Assistant source entities as source data and that PicoT diagnostic/mirror entities are for display, Recorder history, migration and diagnosis only. This rule is now captured in this Accepted ADR.

## Responsibility

This ADR has one architectural responsibility:

> Define how an already selected authoritative external observation enters PicoT Core without introducing intermediate PicoT Home Assistant mirror entities as planner/runtime inputs.

It does not select the source. Discovery, semantic validation, capability-role selection, persistence, source replacement and fallback remain governed by ADR-002 through ADR-010.

It does not define Candidate Generation, Evaluation, execution commands, dashboard entities or vendor-specific control logic.

## Decision

PicoT reads the already selected and validated authoritative source directly at the Home Assistant adapter/input boundary and normalizes that value immediately into an immutable, vendor-independent planning-domain record.

The canonical flow is:

```text
Selected authoritative Home Assistant source
→ validated source mapping / input adapter
→ normalized immutable PicoT domain record
→ atomic PlanningInputSnapshot or RuntimeObservation
→ Planner / Runtime Monitor
```

The following flow is not permitted for Core consumption when the mirror represents the same underlying source value:

```text
Selected authoritative source
→ sensor.picot_* mirror
→ Planner / Runtime Monitor
```

## Source-selection boundary

ADR-040 does not rank competing candidate sources and does not silently replace an existing mapping.

When multiple sources or roles exist, the accepted discovery and mapping contracts determine which source is authoritative for each logical role. For example, a primary meter and a faster realtime-power source may deliberately be different sources under ADR-008.

Once a source has been selected for a logical role, ADR-040 governs only how its observation enters Core: directly through the validated input adapter and canonical normalization path, not through a PicoT mirror entity.

Where a direct measurement and a derived value both claim to represent the same already-selected logical quantity, the mapping/semantic-validation layer must resolve which representation is authoritative before ADR-040 ingestion. ADR-040 does not create a second source-selection rule.

## PicoT entity ownership

PicoT Home Assistant entities are reserved for PicoT-owned outputs such as:

- diagnostics;
- planner state;
- decision records;
- confidence and feasibility results;
- deviation and replan state;
- user-facing derived values;
- Recorder-friendly semantic timelines.

Such entities may be displayed and stored by Home Assistant Recorder but must not become an indirect input back into Core when they merely mirror an already selected external source.

A derived PicoT entity remains valid when it represents a genuinely new PicoT-owned quantity rather than a copy of an external observation.

## Mapping and traceability

The selected external source remains represented by an explicit, persistent and versioned mapping according to ADR-004, ADR-007, ADR-009 and ADR-010.

Core domain records remain vendor-independent and do not carry Home Assistant entity IDs as planning semantics. Evidence and mapping references must nevertheless make it possible to trace a canonical value back to the selected mapping and source observation used for that Planner Run.

Temporary source unavailability does not silently replace the selected source. Any fallback or replacement must follow the existing discovery and mapping rules and remain visible in confidence, evidence and diagnostics.

## No duplicate physical calculations

The same logical physical quantity must have one authoritative normalization/calculation owner per Planner Run.

Other layers reuse the resulting immutable domain value rather than independently recomputing the same quantity from equivalent source observations. This prevents timestamp mismatch, inconsistent sign conventions and divergent rounding or aggregation rules.

This does not prohibit domain-owned derivations that create a genuinely different quantity. For example, ADR-038 owns the canonical SoC-to-stored-energy derivation and ADR-039 owns PV power/actual data conversion into the canonical PV energy timeline.

## Relationship to existing ADRs

- Project Constitution principle 3 and ADR-001 remain unchanged: the Planner itself does not know Home Assistant entity IDs or vendor integrations.
- ADR-002 through ADR-010 remain authoritative for discovery, semantic validation, role selection, persistent mappings, source replacement and traceability; ADR-040 begins only after a source has been selected.
- ADR-008 remains authoritative where different sources deliberately fulfil distinct measurement roles.
- ADR-017 continues to require fresh atomic planning inputs after material change.
- ADR-030 continues to expose only logical capabilities to Candidate Generation.
- ADR-034 continues to consume immutable Runtime Observations rather than raw Home Assistant state.
- ADR-038 continues to define one canonical CurrentStorageState reused during one Planner Run and remains owner of its domain derivations.
- ADR-039 continues to define one canonical PV energy timeline and the replacement of elapsed forecast with measured reality.

## Consequences

- Realtime source data reaches Core with fewer unnecessary transformations and less timing skew.
- PicoT diagnostic entities remain useful without becoming hidden dependencies of planning.
- Vendor independence is preserved because vendor/entity knowledge stays at the adapter/mapping boundary.
- Existing source-selection and fallback contracts are preserved rather than duplicated.
- Source ownership remains explicit.
- Duplicate normalization or calculation of the same logical physical quantity is prevented.

## Core principle

> PicoT ingests the already selected authoritative source once at the adapter boundary, normalizes it directly into immutable vendor-independent domain data, and never routes Core planning back through a `sensor.picot_*` mirror of that same source.
