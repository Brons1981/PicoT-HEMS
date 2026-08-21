# V2ADR-053 — Traceable Confidence Propagation

Status: **Accepted for PicoT v2 rebuild**

## Context

V2ADR-048 preserves interval-local PV source confidence and prohibits hidden
confidence multipliers. V2ADR-049 keeps attenuation-profile confidence
separate from source confidence. PicoT nevertheless needs confidence for a
projected household balance, storage requirement and Candidate Outcome.

An earlier implementation used the minimum confidence across an entire
horizon. One weak interval could consequently reduce a complete plan to a
single-digit percentage. Replacing that minimum with an energy-weighted mean
stopped the pathological result, but the aggregation and its inputs were not
yet represented as a versioned, visible confidence product.

Elapsed forecast performance is also distinct from confidence in remaining
future intervals. Reusing the worst elapsed interval as “PV confidence” makes
those meanings ambiguous.

## Decision

PicoT represents confidence propagation as an immutable, versioned assessment.
It never changes confidence merely to obtain a preferred percentage.

### Preserved components

For every relevant projected interval PicoT preserves separately:

- storage-state measurement confidence;
- household-load forecast confidence;
- PV source confidence when forecast PV contributes energy;
- capability confidence where execution depends on that capability;
- attenuation-profile confidence, when present, as separate evidence.

No component overwrites another. Actual and forecast evidence remain distinct
under ADR-039 and V2ADR-048.

### Interval projection confidence

The confidence of one projected household-balance interval is the lowest
confidence of the independent inputs required for that projection. PV source
confidence participates only when forecast PV contributes to that interval.

Method identity:

`projected-household-interval-required-input-min:v1`

This is a conservative dependency rule, not a forecast-energy multiplier.

### Requirement confidence

Storage-requirement confidence is the energy-throughput-weighted arithmetic
mean of the relevant projected-interval confidence values, bounded by the
storage-state measurement confidence. Weight equals expected usable PV energy
plus expected household-load energy, with an explicit minimum weight of 1 Wh
for a non-empty interval.

Method identity:

`storage-requirement-energy-weighted-confidence:v1`

The assessment records interval identifiers, weights, component values,
result and evidence. A simple unweighted minimum across the horizon is not
permitted.

### Candidate Outcome confidence

Candidate Outcome confidence is the lower of:

- the traceable storage-requirement confidence; and
- the energy-throughput-weighted confidence of intervals relevant to the
  Candidate's charge window and deadline.

Method identity:

`delegated-storage-outcome-confidence:v2`

The outcome stores both inputs and the resulting limiting component. Execution
Plan Builder, Execution Engine, runtime and Device Adapter may display this
assessment but may not reinterpret it.

### Elapsed performance versus future confidence

Forecast-versus-actual deviation is performance evidence. It is not renamed
to source forecast confidence and does not overwrite confidence belonging to
remaining future intervals.

Adaptive regime selection receives separately:

- remaining-future PV confidence, aggregated only over relevant future PV
  intervals with the versioned energy-weighted method; and
- elapsed cumulative deviation, duration and range evidence.

The UI uses distinct labels and method identities for these facts.

### Presentation

Every displayed plan confidence exposes:

- final percentage;
- PV component;
- household-load component;
- storage-state component;
- requirement component;
- charge-window/outcome component;
- limiting component;
- aggregation method version.

Unavailable components remain unavailable and are never shown as zero.

## Verification

Tests prove that:

- one weak, negligible-energy interval does not dominate a complete horizon;
- a weak high-energy interval materially affects the weighted result;
- source component values remain unchanged;
- elapsed deviations do not overwrite future confidence;
- identical evidence produces an identical assessment;
- every displayed final value is reproducible from its exposed components.

## Authority

This decision derives from ADR-017, ADR-026, ADR-032, ADR-037, ADR-039,
V2ADR-048 and V2ADR-049. ADR-040 through ADR-047 are not used as authority.
