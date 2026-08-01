# ADR-029 — Household Power Capacity Management

## Status
Accepted

## Context
PicoT must manage household energy flows within the physical electrical installation as it exists. It cannot move devices between phases or change wiring, but it can observe, plan, constrain, explain and advise.

## Decision
The physical phase distribution is a fixed system constraint.

PicoT may:

- monitor current, power and voltage per phase when available;
- model the phase connection of devices and sources;
- plan simultaneous loads within per-phase capacity;
- reduce, defer or stop controllable actions when a hard phase limit would be exceeded;
- replan after material changes;
- analyse long-term imbalance and voltage trends;
- provide evidence-based installation advice.

PicoT never physically reconfigures phase connections and never presents electrical installation work as an autonomous action.

## Capacity management
For each phase, PicoT may model:

- current and power;
- voltage;
- configured main-fuse rating;
- operational margin;
- PV injection;
- fixed and controllable loads;
- unknown or uncertain phase placement.

For devices and sources, PicoT may model:

- single-phase or three-phase connection;
- connected phase or phase distribution;
- controllable power range;
- interruptibility and commitment;
- control-chain capability.

PicoT plans within the existing phase distribution. It cannot move a one-phase EV charger from L1 to L3 through software.

## Hard limits versus User Objective
`Net Balance` is a User Objective in the Planner Strategy Model.

It determines how strongly PicoT prefers lower peaks, better phase balance and more grid-friendly operation when several valid plans remain.

A Net Balance setting of zero never disables hard technical limits.

Hard limits such as configured main-fuse current, supported device limits and required safety margins remain active at all times and cannot be overridden by a slider, User Rule or optimisation preference.

## Runtime response
When a planned or requested action would exceed a per-phase limit, PicoT may:

- not start the action;
- reduce controllable power;
- defer the action;
- stop or curtail a technically flexible action;
- preserve an existing commitment where possible and optimise around it;
- create a new Planner Run.

Every altered, denied or deferred action receives an explainable reason.

Example:

> EV charging was deferred because the expected current on phase L1 would rise to 27.1 A while the configured limit is 25 A. PicoT created a new plan with a later start time.

The technical audit record preserves the measured values, limit, phase, active commitments and governing constraint.

## Grid and voltage monitoring
Where supported by hardware and integrations, PicoT monitors phase voltage and may detect:

- sustained high voltage;
- sustained low voltage;
- large differences between phases;
- phase loss;
- correlation between high voltage and PV inverter curtailment or shutdown;
- recurrent overload or limited available phase capacity.

PicoT is not an electrical protection system. It uses these observations for planning, diagnostics, explanation and advice.

## Installation Insight and advice
PicoT may analyse historical measurements to identify structural limitations and improvement opportunities.

Examples include:

- EV, battery and dryer concentrated on one phase while another phase remains lightly loaded;
- PV connected to a phase with consistently higher voltage;
- repeated PV inverter shutdown coinciding with high phase voltage;
- recurring curtailment caused by phase-capacity limits.

Advice must be based on objective evidence and shown as a recommendation for assessment by a qualified installer.

Example:

> Phase L3 was above 250 V on 62 occasions during sunny periods, while L1 and L2 remained materially lower. Your PV inverter was unavailable on 14 of those occasions. Ask a qualified installer to assess whether another phase connection is technically possible and useful.

PicoT never claims that a physical change is certainly safe or beneficial without professional assessment.

## Explainability
PicoT always explains why an action was not started, reduced, stopped or postponed.

The user-facing explanation is concise and understandable. The audit trail preserves:

- requested action;
- affected phase;
- measured or projected current/power/voltage;
- configured limit and margin;
- governing hard constraint or User Rule;
- selected fallback or revised start time.

## Core principles
> The physical phase distribution is a given constraint. PicoT optimises within it and may advise about structural improvements, but never changes the electrical installation itself.

> Net Balance is an optimisation preference. Per-phase electrical limits are always enforced as hard system constraints.

> Every denied, reduced, stopped or deferred action is explicitly explainable.
