# PEP-PS-001 — Morning Protection Strategy

**Status:** Accepted  
**Date:** 2026-08-02

## Goal

Validate PicoT step by step inside the live Home Assistant environment with one deterministic strategy, one Zendure installation and two explicitly allowed outcomes.

The first strategy prevents the existing Zendure automation from charging the battery too early in the morning. It does not replace the existing Zendure control automation. PicoT selects the desired operating mode through Home Assistant; the existing automation remains responsible for translating that mode into Zendure REST commands.

## Inputs

Version 1 consumes only:

- a timezone-aware current timestamp;
- an enabled flag;
- one configurable local switch time.

No price forecast, PV forecast, state of charge or household-load forecast is used in version 1.

## Deterministic decision

When the strategy is enabled:

```text
current local time < switch time
→ BALANCE_DISCHARGE_ONLY

current local time >= switch time
→ BALANCE_BIDIRECTIONAL
```

The boundary is inclusive: at the configured switch time PicoT chooses `BALANCE_BIDIRECTIONAL`.

When the strategy is disabled, it produces no execution primitive.

## Home Assistant mapping

The Planner remains independent of Home Assistant names. The accepted adapter mappings are:

```text
BALANCE_DISCHARGE_ONLY
→ input_select.select_option
→ input_select.zendure_2400_ac_modus_selecteren
→ Alleen slim ontladen
```

```text
BALANCE_BIDIRECTIONAL
→ input_select.select_option
→ input_select.zendure_2400_ac_modus_selecteren
→ Nul op de meter
```

No other Zendure mode is permitted in validation phase 1. In particular, no Dynamic NOM mode is used.

## Traceability

Every decision records at least:

- strategy identifier and version;
- evaluated timestamp;
- configured switch time;
- selected execution primitive or disabled outcome;
- deterministic reason;
- next material evaluation time.

## Runtime behaviour

The runtime may dispatch only when the desired primitive differs materially from the current effective mode. Re-evaluating the same state must not create repeated Home Assistant commands.

The first live dashboard must expose the active strategy, desired mode, actual Home Assistant mode, reason, last decision time, next evaluation time, last command identifier, pipeline timing, CPU, memory, uptime and error state.

## Validation boundary

Phase 1 is successful when the complete PicoT pipeline can repeatedly and traceably choose between the two accepted primitives, dispatch at most one command per real transition, and run inside the Home Assistant NUC without unexplained CPU, memory or control conflicts.

Price-driven scheduling may be added as the next validation phase once this behaviour is sufficiently stable. The timing is evidence-based, not calendar-based.
