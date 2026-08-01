# ADR-027 — Execution Plan Commitment and Dynamic Power Allocation

## Status
Accepted

## Context
A Winning Candidate must become a stable and trustworthy execution contract. PicoT must adapt to reality without causing frequent device switching or abandoning actions it has already started.

## Decision
An Execution Plan is a stable execution contract with live monitoring.

Once an action starts, it becomes an Execution Commitment and remains part of the Planning Context for subsequent Planner Runs. New plans optimise around existing commitments unless a higher-priority condition requires change.

Higher-priority conditions include:

- Safety Layer activation;
- hard system or hardware constraints;
- explicit User Rules;
- device failure or loss of capability;
- technically unavoidable recovery.

## Commitment model
A running task may move through states such as:

- `PLANNED`
- `COMMITTED`
- `RUNNING`
- `COMPLETED`
- `INTERRUPTED`
- `FAILED`

Commitment applies to the task, but not always to an exact fixed power level.

## Device and control-chain flexibility
Execution flexibility is determined by the complete control chain, not merely by the device label.

Relevant properties include:

- interruptible;
- power adjustable;
- start controllable;
- pause controllable;
- resume controllable;
- load-balancing support;
- dynamic-power support;
- verified restart behaviour;
- minimum runtime;
- minimum off-time;
- restart delay;
- maximum interruptions per cycle.

A non-smart appliance may become partially controllable through a smart plug only when its resume behaviour is explicitly known or verified. PicoT never assumes this behaviour from the appliance type.

User preferences may further restrict flexibility, but may never grant a capability that the control chain does not have.

## Anti-flipper policy
Interruptible does not mean freely switchable.

All interruption or resume behaviour must respect explicit anti-flipper limits such as minimum runtime, minimum off-time, restart delay and maximum interruptions.

## Dynamic Power Allocation
PicoT keeps commitments stable while continuously optimising the remaining controllable power space.

Within the active commitments, Planner Strategy and device capabilities, PicoT may:

- adjust battery charge power;
- adjust battery discharge power;
- place the battery in standby;
- allocate available PV surplus;
- minimise or deliberately use export;
- use available grid capacity;
- schedule newly available flexible loads;
- trigger replanning after a material change.

Core distinction:

- Execution Commitment defines what task remains in force.
- Dynamic Power Allocation determines how the remaining controllable energy and power are used.

## Example
If EV charging is committed and PV production increases, PicoT does not stop the EV merely to start the battery. It keeps the EV commitment and may use the remaining PV surplus to charge the battery.

If the EV charger supports dynamic power control, the task may remain committed while its power is adjusted. If the charger is only on/off and interruption is not allowed, the Planner must optimise around the fixed EV load.

## No separate orchestrator layer
Execution coordination remains an internal responsibility of the existing Execution Engine.

The pipeline remains:

Execution Plan → Execution Engine → Execution Primitive → Device Adapter → Vendor Command.

The Execution Engine handles timing, validation, commitments, dynamic allocation, retries, timeouts, acknowledgement and replan requests.

## Core principle
> PicoT remains committed to actions it has started and optimises around them. It may change only the parts that are technically and explicitly flexible, and always respects anti-flipper limits.
