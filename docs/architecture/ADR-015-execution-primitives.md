# ADR-015 — Execution Primitive Architecture

**Status:** Accepted  
**Date:** 2026-07-31

## Context

Device vendors and integrations expose their own modes, services and command names. If the PicoT Planner knows those names, the Core becomes vendor-specific and difficult to replace or extend.

The Zendure analysis confirmed that PicoT needs generic execution behaviour rather than direct knowledge of modes such as `Nul op de meter`, `Alleen slim opladen`, `Alleen slim ontladen`, `Snel opladen` or `Snel ontladen`.

## Decision

The PicoT Core knows no vendor-specific modes. It works only with generic Execution Primitives that describe desired energy behaviour.

Initial primitives:

- `STANDBY`
- `STOP_ALL`
- `BALANCE_BIDIRECTIONAL`
- `BALANCE_CHARGE_ONLY`
- `BALANCE_DISCHARGE_ONLY`
- `CHARGE_AT_POWER`
- `DISCHARGE_AT_POWER`

The Device Adapter translates each primitive into vendor-specific commands.

Example:

```text
BALANCE_BIDIRECTIONAL
→ Zendure adapter
→ Nul op de meter
```

```text
CHARGE_AT_POWER(1200 W)
→ Zendure adapter
→ vendor command with 1200 W input limit
```

## Responsibilities

The Planner determines desired behaviour, timing, power and applicable constraints.

The Device Adapter translates a primitive into a vendor-specific implementation and records that translation.

Explainability uses the generic primitive as the user-facing planner action. Vendor-specific translation is logged separately.

## Consequences

- Planner, Explainability and Diagnostics remain vendor-independent.
- A later PicoT ZenSDK adapter can replace the current Zendure execution layer without changing the Planner.
- Vendor mode names are confined to Device Adapters.
- New device support is added through capability and adapter contracts, not planner conditionals.

## Core principle

> PicoT does not control devices by naming vendor modes. PicoT describes desired energy behaviour, and Device Adapters translate that behaviour into device-specific commands.
