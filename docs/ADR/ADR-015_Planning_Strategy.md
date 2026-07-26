# ADR-015 — Planning Strategy

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Project | PicoT HEMS |
| Status | Approved & Frozen |
| Version | 1.0-RC3 |
| Date | 2026-07-26 |

## Context

A HEMS that continuously recalculates the economically best result can become operationally unstable. Small changes in prices, forecasts or measurements may otherwise cause unnecessary switching, plan churn, relay wear and unpredictable behaviour.

PicoT therefore requires a planning strategy that optimises within operational stability constraints.

## Decision

The Planner shall create the most stable executable plan for the selected strategy.

The planning strategy includes:

### Planning Horizon

The planning horizon defines how far into the future PicoT creates an execution plan. It may vary with forecast availability, forecast reliability and device characteristics.

### Replanning Triggers

A new planning cycle may be triggered by material changes in measurements, energy prices, forecasts, device availability, capability, health, user controls, policy or other operational context.

Minor fluctuations should not automatically replace the active plan.

### Plan Stability

Where plans produce comparable outcomes, PicoT shall prefer the plan requiring the fewest changes to the current execution strategy.

### Hysteresis

Thresholds may prevent oscillation caused by measurement noise, small forecast changes or marginal economic differences.

### Minimum Benefit Threshold

A replacement plan should be committed only when its expected improvement exceeds a configurable minimum benefit.

### Switching Penalty

Every state transition has an explicit or implicit planning cost. This may represent relay or contactor wear, compressor wear, communication overhead, reduced predictability, user disruption or another device-specific operational impact.

### Planning Commitment

Once committed, a plan should be preserved whenever reasonably possible.

Committed actions should not be revoked unless a significant event or a change in the operational context justifies replanning.

The Planner shall balance the expected benefit of replanning against the impact of changing an already committed execution plan.

### Predictability

Stable and predictable execution is preferred over marginal optimisation gains when alternatives are otherwise comparable.

## Consequences

- PicoT avoids unnecessary switching between charging and discharging.
- Device wear can influence plan ranking.
- A small economic gain is not sufficient by itself to replace a stable plan.
- Replanning remains explainable because triggers, benefit and impact are recorded.
- Planning behaviour becomes more predictable for the user.

## Status

Approved and frozen for PicoT HEMS v1.0-RC3.