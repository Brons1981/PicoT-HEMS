# V2ADR-001 — Home Assistant Authoritative Source Policy

Status: **Accepted for PicoT v2 rebuild**

## Context

The PicoT v1 implementation introduced PicoT-rendered sensor entities as intermediate sources for planning data. Live validation showed that using those rendered PicoT sensors as the source for later PicoT processing was unreliable and could create an unnecessary second representation of data already available in Home Assistant.

PicoT Core must remain vendor-independent. This does not require physical observations to be re-rendered into PicoT sensor entities before canonical ingestion. Vendor/integration-specific Home Assistant entities may exist at the external ingestion boundary, provided they are converted exactly once into the appropriate canonical PicoT record before entering Planner/Core logic.

## Decision

For PicoT v2, direct use of configured Home Assistant entities as authoritative external input sources is explicitly permitted for:

- Zendure;
- P1 / grid-meter data;
- Solcast;
- PV / inverter production data;
- Nord Pool price data.

These Home Assistant entities are **external source bindings**, not logical Planner capabilities and not permission for vendor-specific entity ids to enter PicoT Core.

The required direction is:

```text
HA source entity
→ designated source adapter / canonical ingestion owner
→ canonical immutable PicoT fact or forecast
→ PlanningInputSnapshot
→ canonical PicoT pipeline
```

A PicoT-rendered diagnostic/dashboard sensor may expose a canonical value for humans, but that rendered sensor must not become the source from which PicoT reads the same fact back into its own planning pipeline.

## Ownership rules

1. Each configured physical/external fact has one designated authoritative HA source binding.
2. The designated ingestion owner reads that source and creates the canonical PicoT representation exactly once.
3. Downstream layers consume the canonical representation; they do not read the HA entity again.
4. Dashboard and diagnostic entities are projections only and never become authoritative feedback sources for the same fact.
5. Source entity id, integration/source type, capture time, freshness/availability and mapping/configuration version remain traceable in diagnostics.
6. Changing the configured HA source creates a new source/mapping version; it does not silently mutate historical records.
7. Missing, unavailable, stale or malformed HA source data must remain explicit. No layer may silently substitute a PicoT-rendered sensor or another source unless an accepted source-selection contract explicitly permits that fallback.

## Core boundary

Direct HA entity access is permitted only at the adapter/ingestion boundary. After canonical ingestion:

- Opportunity Engine does not read HA entities;
- Candidate Engine does not read HA entities;
- Evaluation Engine does not read HA entities;
- Execution Plan Builder does not read HA entities;
- Execution Engine uses logical/canonical state according to its accepted contract;
- vendor-specific translation remains at the Device Adapter boundary.

This preserves the original architecture principle: **the Planner consumes logical/canonical data, never vendor-specific entities.**

## Diagnostic requirement

For each canonical fact originating from Home Assistant, the v2 diagnostic projection must be able to show at minimum:

- canonical fact/record id;
- source category (`zendure`, `p1`, `solcast`, `pv`, `nordpool`);
- configured HA entity id;
- raw observed value/unit where appropriate;
- canonical value/unit;
- captured-at timestamp;
- freshness/availability status;
- mapping/configuration version;
- owning ingestion component;
- downstream snapshot/run reference.

The diagnostic projection observes these records passively and must not perform a second HA read or recalculate the canonical value.

## Consequences

- PicoT v2 may use the proven Home Assistant integration entities directly as external physical/data sources.
- No duplicate PicoT sensor layer is required merely to feed PicoT its own input.
- PicoT dashboard sensors remain presentation/diagnostic outputs only.
- Vendor independence is maintained because vendor-specific semantics stop at the ingestion boundary.
- Source provenance becomes directly visible in the nine-card pipeline diagnostics.

## Scope

This V2ADR is a rebuild implementation clarification. It does not change the original planning-stage responsibilities or create an additional orchestration layer. It records the permitted external-source binding strategy learned from v1 live operation.