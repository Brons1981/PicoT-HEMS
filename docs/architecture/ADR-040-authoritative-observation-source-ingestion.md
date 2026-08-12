# ADR-040 — Authoritative Observation Source Ingestion Contract

**Status:** Proposed  
**Date:** 2026-08-12

## Context

PicoT Core and the Planner are vendor-independent. The Project Constitution and ADR-001 require the Planner to consume logical capabilities and canonical planning-domain records rather than Home Assistant entity identifiers or vendor integrations directly.

Live validation during the 2026-08-10 test phase showed that realtime planning and replanning behave more reliably when PicoT reads the selected physical Home Assistant source entities directly, such as actual Shelly, Zendure, GoodWe or Solcast source entities, rather than first mirroring those values into intermediate `sensor.picot_*` entities and then reading those mirrors back into Core.

Intermediate mirror entities can introduce unnecessary update latency, timestamp skew, temporary availability differences and duplicated calculations. They also blur ownership: a copied value may look PicoT-owned even though the authoritative measurement belongs to an external physical source.

The development log already records the operational invariant that PicoT planner/runtime uses real physical Home Assistant entities as source data and that PicoT diagnostic/mirror entities are for display, Recorder history, migration and diagnosis only. This rule is not yet captured in an Accepted ADR.

## Responsibility

This ADR has one architectural responsibility:

> Define how authoritative external observations enter PicoT Core without introducing intermediate PicoT Home Assistant mirror entities as planner/runtime inputs.

It does not define discovery, Candidate Generation, Evaluation, execution commands, dashboard entities or vendor-specific control logic.

## Proposed decision

PicoT reads validated authoritative source entities directly at the Home Assistant adapter/input boundary and normalizes those values immediately into immutable, vendor-independent planning-domain records.

The canonical flow is:

```text
Authoritative physical Home Assistant source entity
→ validated source mapping / input adapter
→ normalized immutable PicoT domain record
→ atomic PlanningInputSnapshot or RuntimeObservation
→ Planner / Runtime Monitor
```

The following flow is not permitted for Core consumption:

```text
Authoritative physical source
→ sensor.picot_* mirror
→ Planner / Runtime Monitor
```

## Authoritative source rule

When multiple values claim to represent the same physical quantity, PicoT prefers a semantically validated direct measurement from the selected authoritative source over a locally mirrored or recomputed equivalent.

Examples include:

- direct grid power from the selected meter rather than a copied PicoT sensor;
- direct battery SoC and charge/discharge power from the selected storage source rather than a mirror;
- direct inverter production from the selected PV source rather than a copied PicoT sensor;
- direct Solcast forecast source data at the adapter boundary rather than a mirrored forecast entity when both represent the same external value.

A derived PicoT value remains valid when it represents a genuinely new PicoT-owned quantity rather than a copy of an external measurement.

## PicoT entity ownership

PicoT Home Assistant entities are reserved for PicoT-owned outputs such as:

- diagnostics;
- planner state;
- decision records;
- confidence and feasibility results;
- deviation and replan state;
- user-facing derived values;
- Recorder-friendly semantic timelines.

Such entities may be displayed and stored by Home Assistant Recorder but must not become an indirect input back into Core when the underlying authoritative source is already available.

## Mapping and traceability

The selected physical source remains represented by an explicit, persistent and versioned mapping according to ADR-004, ADR-007, ADR-009 and ADR-010.

Core domain records do not carry vendor-specific planning semantics, but evidence and mapping references must make it possible to trace a canonical value back to the source mapping and source observation used for that Planner Run.

Temporary source unavailability does not silently replace the selected source. Any fallback must follow the existing discovery and mapping rules and must remain visible in confidence, evidence and diagnostics.

## No duplicate physical calculations

The same physical quantity must have one authoritative normalization/calculation owner per Planner Run.

Other layers reuse the resulting immutable domain value rather than independently recomputing the same quantity from equivalent source entities. This prevents timestamp mismatch, inconsistent sign conventions and divergent rounding or aggregation rules.

## Relationship to existing ADRs

- Project Constitution principle 3 and ADR-001 remain unchanged: the Planner itself does not know Home Assistant entity IDs or vendor integrations.
- ADR-002 through ADR-010 continue to govern discovery, validation, persistent mappings, source replacement and traceability.
- ADR-017 continues to require fresh atomic planning inputs after material change.
- ADR-030 continues to expose only logical capabilities to Candidate Generation.
- ADR-034 continues to consume immutable Runtime Observations rather than raw Home Assistant state.
- ADR-038 continues to define one canonical CurrentStorageState reused during one Planner Run.
- ADR-039 continues to define one canonical PV energy timeline and the replacement of elapsed forecast with measured reality.

## Consequences

- Realtime source data reaches Core with fewer unnecessary transformations and less timing skew.
- PicoT diagnostic entities remain useful without becoming hidden dependencies of planning.
- Vendor independence is preserved because vendor/entity knowledge stays at the adapter/mapping boundary.
- Source ownership and fallback behaviour remain explicit.
- Duplicate calculations of the same physical quantity are prevented.

## Proposed core principle

> PicoT reads the selected authoritative physical source once at the adapter boundary, normalizes it directly into immutable vendor-independent domain data, and never routes Core planning back through a `sensor.picot_*` mirror of that same source.
