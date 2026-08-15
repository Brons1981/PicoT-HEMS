# V2ADR-048 — Confidence-aware PV Planning for the Whole Household

Status: **Accepted for PicoT v2 rebuild**

## Context

PicoT v2 already ingests a central Solcast PV forecast and a confidence value per forecast interval. Solcast also exposes a lower estimate (`pv_estimate10`) and an upper estimate (`pv_estimate90`). Those interval bounds are currently not retained in the canonical PV energy timeline.

Actual PV production can differ materially from the central forecast. A realised deviation explains elapsed production, but it does not prove that every remaining forecast interval is wrong. Forecast confidence can also vary throughout the day: an uncertain morning may be followed by a substantially more reliable afternoon.

PicoT is a household energy management system. Confidence-aware PV planning therefore belongs to the complete household Energy Path and must not be implemented as a battery-only correction. The same canonical PV uncertainty affects household consumption, grid import and export, self-consumption, storage, EV charging, flexible appliances and every other planned household energy flow.

## Decision

PicoT v2 preserves the complete validated PV forecast range per canonical future interval and makes that range available as immutable Planning Input.

For every supported forecast interval PicoT records at least:

- interval start and end;
- lower forecast energy in Wh;
- central forecast energy in Wh;
- upper forecast energy in Wh;
- interval confidence;
- original source field names and semantics;
- forecast creation/capture time;
- source evidence reference;
- source mapping/configuration version;
- conversion method version;
- validation and availability status.

The initial Solcast mapping is:

```text
pv_estimate10 → lower forecast
pv_estimate   → central forecast
pv_estimate90 → upper forecast
```

The source adapter converts all three power estimates to interval energy with the same interval boundaries and the same explicit conversion method. It must validate:

```text
0 Wh ≤ lower forecast ≤ central forecast ≤ upper forecast
```

Malformed, incomplete or semantically ambiguous ranges are not repaired, reordered or invented silently.

## Confidence and forecast range are separate facts

The interval confidence and the lower/central/upper forecast range must both remain visible. PicoT may not replace the range with one confidence number, derive an undisclosed confidence from the range, or use confidence as an opaque multiplier on forecast energy.

If the source supplies its confidence calculation, PicoT preserves the source value and method identity. If PicoT later calculates an additional confidence value, that calculation requires its own deterministic, versioned and visible method and must not overwrite the source confidence.

## Closed-interval assessment

When reliable actual PV energy is available for exactly the same closed canonical interval, PicoT compares it with the forecast range that originally applied to that interval.

The assessment is deterministic:

```text
actual < lower forecast                  → below_range
lower forecast ≤ actual ≤ upper forecast → within_range
actual > upper forecast                  → above_range
```

The result preserves at least:

- actual, lower, central and upper energy in Wh;
- signed and absolute deviation from the central forecast;
- distance below or above the range where applicable;
- range assessment;
- actual and forecast confidence;
- actual and forecast evidence references;
- interval boundaries;
- calculation method version;
- evaluation time and deterministic result id.

No assessment is authoritative when interval alignment, actual coverage or the retained historical forecast range is insufficient. That condition remains explicit.

## Past reality and future uncertainty

Actual energy is authoritative for elapsed intervals. It replaces forecast energy for those elapsed intervals according to the canonical PV timeline contract.

A past deviation does not silently scale, dampen or overwrite all remaining PV intervals. Every future interval retains its own newest validated lower, central and upper forecast together with its own confidence.

Historical deviation may become material-change evidence and request a fresh Planner Run. The fresh run consumes:

- actual energy for elapsed intervals;
- the newest validated interval-specific forecast range for future intervals;
- the confidence and provenance belonging to each interval;
- the same immutable household inputs used by the complete pipeline.

Any learned orientation-, season-, obstruction- or time-specific forecast correction is a separate future model. Such a model must be deterministic, versioned, evidence-backed and visible and may not be introduced as an implicit global damping factor.

## Whole-household planning contract

The canonical forecast range is shared Planning Input for the complete household Energy Path. Downstream planning may use explicit forecast bases such as:

- `lower` for a conservative PV availability case;
- `central` for the source's central expectation;
- `upper` for an explicitly identified high-production opportunity case.

Every Candidate or projected household balance must state which forecast basis or deterministic combination method it uses per interval. A hidden weighted average, hidden daily correction factor or device-specific reinterpretation is prohibited.

Confidence-aware planning applies consistently to:

- household load and grid-import requirements;
- PV self-consumption and grid export;
- storage charging, discharging and reserve requirements;
- EV charging;
- flexible and managed appliance profiles;
- complete Candidate Energy Paths;
- Evaluation results and replanning evidence.

No device receives a private PV forecast. Device-specific feasibility constraints remain owned by their capability and Energy Path contracts.

## Candidate and Evaluation responsibilities

Planning Input owns the canonical forecast range and provenance.

The Opportunity Engine may describe uncertainty-backed opportunities and constraints but does not choose a device or winning forecast case.

The Candidate Engine constructs complete household Energy Paths from explicit forecast bases. When uncertainty can materially change feasibility or household outcome, the relevant alternative must remain visible as a distinct Candidate or explicit Candidate assumption rather than being hidden inside one energy value.

The Evaluation Engine compares those complete Candidates using the accepted deterministic strategy order. It may not invent a new PV estimate, erase uncertainty or collapse alternatives into an opaque score.

Execution Plan Builder and Execution Engine consume the selected Energy Path. They do not reinterpret PV confidence or forecast ranges.

## Missing range handling

If a validated central forecast exists but one or both bounds are absent:

- the central forecast may remain available under the canonical forecast contract;
- range status is `unavailable` or another explicit validated status;
- missing bounds are never copied from the central value or synthesised silently;
- range-based assessment and range-dependent Candidates are unavailable;
- diagnostics state exactly which source fields are missing and which planning possibilities are consequently excluded.

## Replanning boundary

This V2ADR does not create a second Runtime Monitor or a PV-specific Planner.

The accepted replan route remains:

```text
canonical closed-interval evidence
→ deterministic material-change classification
→ replan request
→ fresh atomic Planning Input Snapshot
→ normal whole-household pipeline
```

The materiality method, thresholds, hysteresis and minimum evidence coverage must be deterministic, versioned and projected visibly before they can influence replanning. Observer-only validation precedes control authority.

## Explainability requirements

The existing nine-card pipeline dashboard must be able to expose, without recalculation:

- all three forecast values and interval confidence;
- source and conversion method;
- range validation status;
- closed-interval assessment and deviations;
- materiality inputs, threshold and result;
- the forecast basis used by every affected Candidate;
- the resulting household balance and confidence;
- the exact reason a replan was or was not requested;
- snapshot, run, Candidate and downstream lineage references.

Diagnostic projection remains passive. It may present these canonical records but may not calculate an alternative forecast, Candidate or replan decision.

## Non-goals

This V2ADR does not:

- define battery-only planning;
- introduce device control or remove observer-only status;
- prescribe a Solcast-wide damping setting;
- implement obstruction learning for east/west PV orientations;
- assume that one elapsed forecast error applies to the remaining day;
- authorise hidden weights, corrections or fallback estimates;
- create a parallel PV, household or replan pipeline.

## Relationship to the reliable architecture baseline

- ADR-001 through ADR-039 remain the reliable original architecture foundation.
- V2ADR-001 remains authoritative for Home Assistant source ingestion at the v2 adapter boundary.
- Later historical ADR-040 through ADR-047 are not architectural authority for this v2 decision.
- This V2ADR extends the v2 rebuild with an explicit, versioned uncertainty contract without changing the accepted pipeline-stage ownership.

## Consequences

Positive:

- reliable future intervals are not discarded because earlier intervals were wrong;
- uncertain future PV is represented explicitly instead of through hidden damping;
- every household Energy Path uses the same traceable PV uncertainty;
- battery, EV, appliances, import and export cannot diverge through private forecast logic;
- actual-versus-forecast evidence becomes explainable in relation to the original forecast range.

Costs:

- all three source estimates and their historical evidence must be retained;
- canonical contracts and projections must grow before confidence-aware planning can be enabled;
- Candidate growth must remain bounded and measurable;
- range-dependent planning must fail visibly when required source evidence is missing.

## Implementation order

1. Preserve and project lower, central and upper forecast energy per interval without changing planning behaviour.
2. Add deterministic closed-interval range assessment in observer-only mode.
3. Add cumulative and interval-specific evidence without applying a global correction.
4. Add bounded, explicit whole-household Candidate assumptions for future uncertainty.
5. Connect accepted material-change evidence to the existing fresh-snapshot replan route.
6. Grant control influence only after CI and live observer verification prove lineage, stability and bounded runtime cost.

## Core principle

> PicoT plans the whole household from one visible interval-specific PV uncertainty contract: elapsed reality remains truth, future confidence remains local to its forecast interval, and no hidden correction may replace traceable evidence.
