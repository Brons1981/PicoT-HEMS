# ADR-028 — Runtime Resource Governance

## Status
Accepted

## Context
PicoT must remain stable, predictable and explainable on different hardware profiles. Resource pressure may reduce optimisation depth, but may never compromise Safety, hard constraints or active execution commitments.

## Decision
PicoT governs CPU, memory, storage, planner runtime, queues and concurrent work through explicit resource budgets, pressure states and graceful degradation.

PicoT optimises only within the runtime resources that are safely available.

## Pressure states
Runtime Resource Governance uses at least:

- `NORMAL`
- `TRANSIENT_PRESSURE`
- `SUSTAINED_PRESSURE`

A short CPU, memory or I/O spike does not immediately cause structural degradation. PicoT first observes whether the pressure persists beyond the normal measured baseline and available margin.

Transient pressure may temporarily delay or limit non-critical work. Sustained pressure causes controlled degradation and a visible user notification.

Recovery uses hysteresis: scaling up is slower than scaling down so Resource Governance does not oscillate.

## Graceful degradation
PicoT prefers a less refined plan over an unstable runtime.

Possible degradation measures include:

- fewer Candidate Families;
- smaller Candidate Set;
- lower evaluation depth;
- delayed Learning;
- delayed historical analysis;
- reduced dashboard computation;
- lower sensitivity to minor replanning triggers.

The current runtime profile, reason, old and new limits and expected impact are logged and visible.

## Runtime priority order
When resources are scarce, PicoT protects functions in this order:

1. Safety Layer;
2. hard system and hardware constraints;
3. active Execution Commitments;
4. critical monitoring and capability status;
5. minimum viable Planner Core and required replanning;
6. User Rules;
7. Explainability and essential logging;
8. Learning and profile refinement;
9. extended optimisation;
10. non-critical dashboard and historical analysis.

Resource pressure may reduce optimisation quality, but never Safety, execution continuity or minimum system observation.

## Resource monitoring
PicoT records at minimum:

- total and available memory;
- PicoT process memory and peak memory;
- CPU usage and CPU time;
- Planner duration;
- storage and database growth;
- queue depth;
- Opportunity, Candidate and Evaluation counts;
- pressure-state transitions;
- degradation events;
- memory-after-run trend for leak detection.

## Runtime Health Indicator
The dashboard contains a compact coloured performance indicator for the Home Assistant platform and PicoT runtime.

Inputs include:

- CPU load;
- available memory;
- Planner duration;
- current pressure state;
- relevant I/O or storage delay.

Suggested states:

- green — healthy;
- yellow — transient limitation;
- orange — sustained degradation;
- red — critical resource margin.

A critical signal may not be hidden by averaging it with healthy signals. Opening the indicator shows the likely direction of the cause and the underlying measurements, for example memory pressure, external CPU load, slow Planner or storage delay.

## Planner-run discipline
PicoT runs at most one full Planner Run at a time.

There is always a fixed five-second stabilisation interval measured from the end of one Planner Run to the start of the next:

Planner Run start → Planner Run end → five seconds stabilisation → fresh Planning Input Snapshot → next Planner Run.

Events during the five-second interval do not become stale planning input. They only set `REPLAN_REQUIRED = true`.

After the stabilisation interval, PicoT creates a completely fresh, atomic Planning Input Snapshot containing current measurements, device states, commitments, User Rules, strategy version, prices and forecasts.

Safety and hard-limit responses may act immediately and do not wait for this interval. The subsequent full Planner Run still starts with a fresh snapshot.

Core rule:

> PicoT never plans from buffered stale state and never runs overlapping full Planner Runs.

## Platform qualification
PicoT is not qualified by hardware brand or model assumptions.

Platforms are classified using measured and reproducible runtime profiles:

- CPU capacity and sustained headroom;
- available memory and peak use;
- Planner duration distribution;
- storage performance;
- stability under representative load;
- frequency and duration of degraded mode.

A Raspberry Pi, NUC, virtual machine or other platform is described as validated, conditionally suitable or not recommended only after sufficient measurements exist.

## Future execution confirmation
A future enhancement may correlate direct device status and indirect power changes, such as P1 deltas, to confirm execution. This is not required for the initial architecture. The fixed five-second stabilisation interval and fresh snapshot remain the simple baseline.

## Core principles
> PicoT optimises never at the expense of runtime stability.

> Short resource spikes are tolerated; sustained pressure causes controlled and transparent degradation.

> Predictability and stability take priority over maximum parallelism or theoretical optimisation depth.
