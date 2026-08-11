# ADR-027 — Execution Plan Commitment and Dynamic Power Allocation

## Status
Accepted

**Amended:** 2026-08-11 by ADR-037

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
PicoT keeps commitments stable while continuously optimising the remaining controllable energy space.

Dynamic Power Allocation must respect the ownership of instantaneous power defined by the selected Execution Primitive and control chain.

For integration-managed storage balance commitments using:

- `BALANCE_BIDIRECTIONAL`;
- `BALANCE_CHARGE_ONLY`;
- `BALANCE_DISCHARGE_ONLY`;

PicoT does **not** continuously set battery watts. The battery integration or local controller determines instantaneous charge/discharge power from its own balancing logic. PicoT may project the expected power and energy flow for planning, observe actual battery power and SoC, and request replanning when reality materially diverges from the committed path.

For explicit-power storage commitments using:

- `CHARGE_AT_POWER`;
- `DISCHARGE_AT_POWER`;

PicoT may apply the committed requested power only when the scenario is explicitly accepted as power-controlled. Under ADR-037 the initial such storage scenario is Dynamic Trading. The requested power must come from the accepted trading-power policy and remain within hard technical, phase, grid and system limits.

For other controllable resources, power may be adjusted only where the accepted capability and control-chain contract explicitly grants PicoT that authority.

Within these boundaries, PicoT may:

- choose or preserve integration-managed battery balance behaviour;
- apply explicit battery power for accepted power-controlled trading commitments;
- place the battery in standby when the committed plan allows it;
- allocate available PV surplus across controllable resources;
- minimise or deliberately use export according to the committed plan;
- use available grid capacity;
- schedule newly available flexible loads;
- trigger replanning after a material change.

Core distinction:

- Execution Commitment defines what task remains in force.
- Dynamic Power Allocation determines how the remaining controllable energy and power are used **within the control authority of the active primitive and capability**.
- Projected power is not automatically commanded power.

## Storage control ownership

ADR-037 defines the storage-specific boundary:

> For normal household storage control, PicoT chooses intent and timing while the battery integration controls instantaneous power.

Therefore a `BALANCE_*` commitment may include projected expected battery flow and projected SoC, but must not acquire a `requested_power_w` merely because live conditions change.

If the projected SoC trajectory or expected time-to-target becomes materially wrong, PicoT reviews/replans the complete path. It does not silently seize low-level power control from the integration.

Dynamic Trading is the initial intentional exception. A trading commitment may contain explicit power because controlled grid import/export is itself part of the committed action.

## Example
If EV charging is committed and PV production increases, PicoT does not stop the EV merely to start the battery. It keeps the EV commitment and may use the remaining PV surplus according to the accepted control-chain capabilities.

If the battery is in `BALANCE_CHARGE_ONLY`, the additional PV may cause the battery integration to increase charging power automatically. PicoT observes and projects that effect; it does not send a new battery watt setpoint.

If the EV charger supports dynamic power control and its capability contract grants PicoT explicit power authority, the task may remain committed while its power is adjusted. If the charger is only on/off and interruption is not allowed, the Planner must optimise around the fixed EV load.

## No separate orchestrator layer
Execution coordination remains an internal responsibility of the existing Execution Engine.

The pipeline remains:

Execution Plan → Execution Engine → Execution Primitive → Device Adapter → Vendor Command.

The Execution Engine handles timing, validation, commitments, permitted dynamic allocation, retries, timeouts, acknowledgement and replan requests.

## Relationship to ADR-037

ADR-037 is authoritative for storage control intent, NOM projection and trading-power ownership. Where the earlier wording of this ADR broadly stated that PicoT may adjust battery charge/discharge power, that authority is now narrowed:

- integration-managed `BALANCE_*` storage: PicoT predicts/observes power but does not command watts;
- accepted power-controlled storage scenarios such as Dynamic Trading: PicoT may command the explicit power contained in the committed plan.

## Core principle
> PicoT remains committed to actions it has started and optimises around them. It may change only the parts that are technically and explicitly flexible, respects control ownership and anti-flipper limits, and never confuses projected battery power with commanded battery power.