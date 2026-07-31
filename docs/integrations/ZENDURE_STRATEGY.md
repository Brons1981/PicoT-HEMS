# Zendure Integration Strategy

**Status:** Accepted  
**Date:** 2026-07-31

## Decision

PicoT HEMS v1 will build on the existing @gielz Zendure integration as the primary Zendure execution layer.

The current integration provides the capabilities PicoT needs for v1, including:

- telemetry;
- standby and stop control;
- bidirectional NOM behaviour;
- charge-only NOM behaviour;
- discharge-only NOM behaviour;
- explicit charge power;
- explicit discharge power.

PicoT will not adopt the integration's dynamic strategies as Core planner logic. PicoT will make the HEMS decisions itself and use the integration as the execution and communication layer.

## Mode mapping

The adapter may translate generic PicoT Execution Primitives to @gielz modes or commands:

- `STANDBY` → Standby
- `BALANCE_BIDIRECTIONAL` → Nul op de meter
- `BALANCE_CHARGE_ONLY` → Alleen slim opladen
- `BALANCE_DISCHARGE_ONLY` → Alleen slim ontladen
- `CHARGE_AT_POWER` → Handmatig or explicit charge command
- `DISCHARGE_AT_POWER` → Handmatig or explicit discharge command
- `STOP_ALL` → stop all command

The exact technical route must be validated through adapter tests and practical operation.

## PicoT ZenSDK option

A dedicated PicoT ZenSDK adapter is deferred until PicoT v1 and the Core are stable, unless an earlier structural limitation is proven.

The option moves forward when any of the following becomes a material limitation:

- required commands or capabilities are missing;
- explicit power control is unreliable;
- acknowledgements or state feedback are insufficient;
- latency or update frequency constrains PicoT;
- integration maintenance stops or becomes unstable;
- vendor updates cause repeated structural breakage;
- required behaviour cannot remain explainable or reproducible;
- vendor-specific HEMS logic cannot be bypassed by the PicoT adapter.

## Architectural boundary

The Planner, Execution Plan, Explainability and Diagnostics remain independent of @gielz and ZenSDK. Only the Device Adapter knows the concrete integration.

## Consequence

PicoT gains a pragmatic path to v1 without giving up the option of a future first-party Zendure adapter.
