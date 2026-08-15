# V2ADR-049 — Evidence-backed PV Attenuation Profiles

Status: **Accepted for PicoT v2 rebuild**

## Context

V2ADR-048 preserves the original interval-specific PV forecast range, source confidence and realised actual PV evidence. It explicitly prohibits an implicit global damping factor and reserves any orientation-, season-, obstruction- or time-specific correction for a separate deterministic, versioned and visible model.

A PV installation can have a stable local obstruction pattern that a general forecast source does not represent. Examples include trees, buildings, chimneys, dormers and horizon obstructions. The error can recur with a similar shape at a similar solar position: production follows the source forecast before an obstruction is reached, then drops through a repeatable attenuation curve.

The first live PicoT case is an east/west installation with a recurring late-day attenuation pattern towards sunset. Solcast exposes the two rooftop resources and daily energy separately, but the available Home Assistant detailed half-hour forecast is combined. GoodWe exposes total AC production and supporting DC string voltage/current. PicoT must not invent a hidden half-hour split between east and west when the source does not provide one.

The correction must be useful to the complete household Energy Path. It is not a battery-only adjustment and it must be reusable for other users and installations.

## Decision

PicoT v2 may derive an installation-specific `PVForecastAttenuationProfile` from aligned historical forecast and actual PV intervals.

The profile is a separate canonical evidence product. It never overwrites the original source forecast, source confidence or actual evidence. A corrected forecast is a derived planning assumption with its own identity, provenance, method version, availability and confidence.

The initial model operates on total installation PV because the available detailed Solcast forecast is combined. Separate rooftop or string correction is unavailable until aligned interval forecasts and reliable actual energy exist for those separate scopes.

## Canonical source evidence

Every learning observation preserves at least:

- installation scope id;
- canonical interval start and end;
- original lower, central and upper forecast energy;
- original source confidence;
- aligned actual PV energy and actual confidence;
- forecast and actual evidence references;
- forecast capture time;
- solar azimuth and elevation;
- minutes before or after local sunset;
- source mapping and conversion method versions;
- alignment, coverage and eligibility status;
- deterministic observation id.

Daily rooftop totals and instantaneous DC string measurements may be retained as supporting evidence. They may not be presented as separate half-hour forecast or actual energy when those semantics are unavailable.

For the first live installation, the confirmed source metadata is:

- east resource `e64c-9e1c-e927-5fb1`: 3.3 kWp DC, azimuth 90 degrees, tilt 24 degrees, loss factor 0.90;
- west resource `1de2-0fe4-8a58-1804`: 1.6 kWp DC, azimuth 270 degrees, tilt 24 degrees, loss factor 0.88.

These installation facts are test evidence, not hard-coded Core policy.

## Eligible structural evidence

A low actual result is not automatically structural attenuation. An observation may contribute to a profile only through an explicit, versioned eligibility method.

The method must consider at least:

- exact forecast/actual interval alignment;
- complete actual coverage;
- a finite central forecast above an explicit minimum energy floor;
- the original interval confidence and forecast range;
- continuity across neighbouring intervals;
- whether production followed the forecast sufficiently before the suspected attenuation window;
- recurrence across multiple distinct days;
- age and seasonal relevance of the evidence.

A single day, one isolated low interval, an unavailable source state or an unaligned interval cannot establish a reusable profile.

Cloud variability must not silently become permanent obstruction learning. Qualification results, rejected observations and rejection reasons remain visible.

## Sun-relative pattern

A fixed physical obstruction is associated with solar geometry, not one permanent clock time. Every observation therefore retains solar azimuth, solar elevation and sunset-relative time.

The first profile representation is a deterministic, bounded sequence of canonical attenuation buckets. Each bucket states its exact solar or sunset-relative applicability. A profile lookup may use sunset-relative buckets for an understandable projection while preserving the solar coordinates of all underlying observations.

Any bucket width, solar-position tolerance, seasonal cohort, interpolation rule or smoothing rule must be explicit and method-versioned. PicoT may not create a visually smooth curve that cannot be traced to retained bucket evidence.

The profile can describe:

- the structural attenuation onset;
- the remaining forecast fraction through successive intervals;
- the duration of the attenuation window;
- the stable low-production tail;
- the evidence dispersion around every bucket.

## Attenuation factor

For each eligible observation with central forecast energy above the configured floor, the raw ratio is:

```text
raw_ratio = actual_energy_wh / central_forecast_energy_wh
```

A dampening-only profile bounds an applied factor to:

```text
0.0 <= attenuation_factor <= 1.0
```

The deterministic aggregation method must be robust against isolated observations and state its statistic, sample count, distinct-day count, dispersion and configuration version. Median, quantile or another statistic is not implicit: the selected method and every threshold require a visible method version and tests before planning influence.

A factor below 1.0 is available only when minimum evidence, recurrence, dispersion, confidence and freshness requirements all pass. Otherwise the bucket status is unavailable and the effective factor remains explicitly `1.0` with reason `insufficient_structural_evidence`, `stale_profile` or another enumerated reason.

The profile does not increase a forecast above its original values.

## Derived forecast range

When an attenuation bucket is available, PicoT derives:

```text
corrected_lower   = original_lower   * attenuation_factor
corrected_central = original_central * attenuation_factor
corrected_upper   = original_upper   * attenuation_factor
```

Applying the same factor preserves the ordering and visible width semantics of the original source range. The original range remains available alongside the corrected range.

Source confidence and profile confidence remain separate facts. Neither value overwrites the other, and PicoT may not hide them inside an undisclosed combined confidence. If planning later requires a combined confidence, that combination needs its own accepted deterministic contract.

## Whole-household planning

An available corrected range is one explicit forecast basis for the complete household Energy Path. It applies consistently to:

- household consumption and grid-import requirements;
- PV self-consumption and export;
- storage charging, discharging and reserve requirements;
- EV charging;
- flexible and managed appliances;
- every affected Candidate and projected household balance;
- Evaluation and replanning evidence.

No device receives a private attenuation factor. Candidate records state whether they use the original or corrected forecast basis and reference the exact profile and bucket evidence.

Planning influence is unavailable until observer-only evidence proves deterministic behaviour, sufficient coverage, bounded runtime cost and complete lineage.

## Rooftop and string boundaries

PicoT may preserve Solcast rooftop metadata and GoodWe string observations for diagnosis and future extension.

It may not:

- split a combined half-hour forecast using daily rooftop totals;
- infer half-hour east/west energy from panel capacity alone;
- treat instantaneous string voltage multiplied by current as canonical AC interval energy;
- claim a rooftop-specific attenuation profile without aligned rooftop-specific interval evidence;
- hard-code one user's entity ids, panel counts, orientation or obstruction times in Core.

A future rooftop-specific profile may reuse this contract when both forecast and actual evidence share the same explicit scope and interval semantics.

## Explainability

The pipeline projection must expose, without recalculation:

- original lower, central and upper forecast values;
- original source confidence;
- profile and bucket ids;
- attenuation factor;
- corrected lower, central and upper values;
- profile confidence;
- sample and distinct-day counts;
- dispersion;
- evidence period and last-updated time;
- solar azimuth, elevation and sunset-relative bucket;
- eligibility method and aggregation method versions;
- contributing and rejected evidence references;
- availability or rejection reason;
- forecast basis used by every affected Candidate;
- snapshot, run and downstream lineage references.

Historical records must allow a user to reconstruct why a factor existed, changed, expired or was not applied.

## Replanning boundary

A newly available or materially changed profile does not create a separate PV planner or runtime monitor.

The accepted route remains:

```text
new canonical evidence
→ deterministic profile update
→ visible material-change classification
→ replan request
→ fresh atomic Planning Input Snapshot
→ normal whole-household pipeline
```

Thresholds, hysteresis and minimum evidence for profile-triggered replanning must be explicit, versioned and observer-validated.

## Failure and fallback behaviour

- Missing or invalid actual evidence does not update the profile.
- Missing solar context makes the relevant observation ineligible.
- Missing source bounds preserves the original central forecast rules from V2ADR-048 but makes range correction unavailable where required.
- An unavailable, stale or low-evidence profile leaves the original forecast unchanged.
- Profile storage or ingestion failure is visible and must not produce a cached-looking valid factor.
- Conflicting evidence reduces profile confidence or makes the bucket unavailable; it is not silently discarded.
- Removal or replacement of a physical obstruction requires new evidence and explicit profile ageing rather than manual hidden constants.

## Non-goals

This V2ADR does not:

- introduce control authority;
- define battery-only planning;
- guarantee weather classification;
- reconstruct unavailable per-rooftop interval forecasts;
- prescribe a Solcast-wide damping setting;
- authorise an opaque machine-learning model;
- derive a profile from screenshots;
- treat one clear-looking day as sufficient evidence;
- alter original source observations;
- create a parallel pipeline.

## Relationship to the reliable architecture baseline

- ADR-001 through ADR-039 remain the reliable original architecture foundation.
- V2ADR-001 remains authoritative for Home Assistant source ingestion.
- V2ADR-048 remains authoritative for original PV ranges, local source confidence and whole-household forecast assumptions.
- Historical ADR-040 through ADR-047 are not architectural authority for this v2 decision.
- This V2ADR adds a separate evidence-backed correction product without changing accepted pipeline ownership.

## Consequences

Positive:

- recurring local shading can influence planning without corrupting source forecasts;
- the correction generalises to different users and obstruction types;
- a stable attenuation shape is represented instead of one crude daily factor;
- every corrected value remains reconstructable from historical evidence;
- insufficient or conflicting evidence fails visibly and safely to the original forecast.

Costs:

- aligned historical forecasts, actuals and solar context must be retained;
- learning requires evidence across multiple days and cannot be enabled immediately;
- profile ageing and seasonal relevance require explicit policy;
- projections and storage grow with bucket and observation lineage;
- rooftop-specific correction remains unavailable without rooftop-specific intervals.

## Implementation order

1. Define immutable attenuation observation and profile contracts without changing planning.
2. Capture and project sun-relative, aligned historical evidence in observer-only mode.
3. Add deterministic eligibility classification with visible rejection reasons.
4. Add bounded bucket aggregation and profile-confidence calculation in observer-only mode.
5. Project original and corrected forecast ranges side by side.
6. Add an explicit corrected whole-household forecast basis to bounded Candidates.
7. Connect material profile changes to the existing fresh-snapshot replan route.
8. Grant control influence only after CI and live observer evidence prove correctness, lineage, stability and bounded cost.

## Core principle

> PicoT may correct a forecast only where recurring local evidence proves a visible sun-relative attenuation pattern; the original forecast remains intact, every factor remains reconstructable, and insufficient evidence means no hidden correction.
