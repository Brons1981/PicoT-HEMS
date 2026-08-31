# V2ADR-063 — Committed trajectory materiality thresholds

Status: **Accepted**

Date: 2026-08-31

## Context

V2ADR-062 restores material-change replanning during an active commitment, but
ADR-034 deliberately leaves numeric thresholds with the observation producer.
Those thresholds cannot be derived from raw SoC changes alone: household
support, planned export, charging and forecast uncertainty all cause expected
storage movement.

Incident 67 showed a plan selected around 43% SoC and a later observed state
around 21%.  The measured overnight household load was broadly in the same
order as its rolling forecast.  A rule based only on instantaneous household
power or absolute SoC movement would therefore either miss the incident or
replan during valid planned discharge.

## Decision

### The admitted plan carries its monitoring baseline

Every newly admitted commitment persists:

- the snapshot time at which it was selected;
- the exact household-load forecast intervals used by that plan;
- lower, central and upper expected storage energy at each canonical trajectory
  checkpoint;
- the source plan, schedule, forecast and simulation lineage.

These records are monitoring evidence.  They do not rank Candidates and do not
grant the Plan Store or Runtime Monitor selection authority.

A legacy commitment without this baseline is not silently assigned a synthetic
trajectory.  On restart it is rejected for one fresh canonical replan so a new
baseline can be admitted.

### Storage trajectory deviation

The storage producer compares current stored energy with the latest completed
checkpoint of the committed lower/central/upper corridor.

Movement inside the corridor is expected progress and is non-material.  A
transition is material only when current energy lies outside the corridor by at
least:

```text
max(250 Wh, 5% of usable storage capacity)
```

The rule is symmetric.  An unexpected shortage can threaten recoverability;
an unexpected surplus can remove a planned charge need or create a materially
different feasible path.  Central-scenario deviation alone never crosses the
threshold while the actual state remains inside the uncertainty corridor.

### Household-load energy deviation

The household producer evaluates only contiguous, fully closed committed
forecast intervals.  At least two canonical intervals (initially 30 minutes)
must have usable observations.  Every evaluated interval requires at least two
samples spanning at least half of the interval.

For the covered interval set, a transition is material when the absolute
difference between cumulative actual and committed expected household energy
is at least:

```text
max(250 Wh,
    5% of usable storage capacity,
    25% of cumulative expected household energy)
```

This is also symmetric.  Missing or insufficient history is explicitly
unavailable evidence, not a zero-load assumption and not a material event.

### Hysteresis and repeated observations

Thresholds are evaluated in whole materiality buckets.  One plan revision
emits at most one observation for each crossed bucket and evidence kind.  A
further observation requires a larger crossed bucket or a newly admitted plan
revision.  Process restart may conservatively re-emit a still-material bucket;
the resulting canonical comparison remains authoritative.

The household producer creates `HOUSEHOLD_STATE_CHANGED` observations.  This
decision extends the runtime observation kinds with `STORAGE_STATE_CHANGED`
for the storage-corridor producer.  Both create immutable `RuntimeObservation`
records with `material_transition=True`.  The Runtime Monitor remains the sole
classifier and fresh-snapshot authority.  The producer cannot start a Planner
Run, retain or replace a commitment, construct a Candidate, or dispatch a
command.

## Configuration boundary

The initial constants above are versioned domain policy.  They are not hidden
Home Assistant tuning values.  Changing them requires an explicit policy
version and regression evidence against ordinary progress, planned discharge,
forecast uncertainty and material incident replay.

## Compatibility

The commitment method version advances because the monitoring baseline is a
required part of newly admitted state.  Deserialization remains backward
compatible so old records can be diagnosed, but restart recovery rejects an
old active commitment and requests normal replanning rather than inventing the
missing evidence.

## Verification

Tests must prove that:

1. expected SoC progress inside the lower/upper corridor is non-material;
2. a one-to-four-percent storage difference remains non-material;
3. storage energy outside the corridor by the accepted threshold is material;
4. planned explicit discharge represented by the trajectory does not trigger;
5. household variation below the combined threshold is non-material;
6. cumulative household deviation over sufficient closed intervals is
   material;
7. missing or incomplete history does not invent an event;
8. baselines survive Plan Store restart with their lineage intact;
9. old baseline-less commitments fail closed into a fresh replan;
10. a material producer event flows through ADR-034 to a second atomic snapshot
    and one canonical Planner Run.

## Relationship to existing ADRs

- ADR-017 owns fresh rolling Planning Input and recoverability.
- ADR-034 owns classification and replanning coordination.
- ADR-037 owns the deterministic HouseholdLoadForecast and storage need.
- V2ADR-052 owns durable commitment context.
- V2ADR-062 owns symmetric incumbent/challenger comparison after a material
  event.

## Core principle

> Compare reality with the admitted plan's uncertainty corridor, not with raw
> telemetry movement or a baseline invented after the fact.
