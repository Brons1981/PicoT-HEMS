# ADR-047 — Selected mode control authority and device activity

- Status: Accepted
- Date: 2026-08-13
- Decision scope: Storage control authority, runtime flow validation and execution suppression
- Related: ADR-015, ADR-016, ADR-033, ADR-034, ADR-037, ADR-042, ADR-046

## Context

Live validation showed that three different concepts were being conflated around storage control:

1. the user-selected storage mode exposed through the configured Home Assistant selector;
2. PicoT's canonical intended control regime used for execution and closed-loop validation;
3. the storage device's instantaneous activity/status, which may report Standby whenever the battery has nothing to do even though the selected mode remains active.

For the Zendure integration used during live validation, a selected delegated mode such as `Alleen slim ontladen` may legitimately report an actual device state of `Standby` whenever PV surplus exists and there is nothing to discharge. The same transient Standby activity can occur under other selected modes. Therefore an observed device activity of Standby must not automatically replace the selected or canonical control regime.

A second issue was found in the opposite direction: when the user explicitly selects `Standby` in the configured storage mode selector, PicoT must not continue or initiate control flow for that storage scope. In that case the selected mode is an explicit control-authority boundary, not merely an observed device activity state.

Accepted ADR-042 remains frozen. This ADR adds the missing relationship between selected mode, canonical control regime and observed device activity state.

## Decision

PicoT distinguishes the following concepts explicitly.

### Selected mode

The selected mode is the authoritative user/device-facing mode selected through the configured storage mode selector.

It is not the same as instantaneous device activity.

The adapter layer is responsible for translating vendor-specific selector values into the canonical selected-mode semantics required by Core.

### Canonical control regime

The canonical control regime expresses the intended behavioral contract used by PicoT execution and closed-loop validation, for example:

- `delegated_bidirectional`;
- `delegated_discharge_only`;
- `delegated_charge_only`;
- `forced_charge`;
- `forced_discharge`;
- `standby`.

The selected mode may establish or constrain the canonical control regime, but observed device activity may not silently replace it.

### Observed device activity state

Observed device activity describes what the storage hardware is physically doing at the current instant, for example:

- charging;
- discharging;
- standby/idle;
- unavailable/unknown.

A device activity state of standby/idle is normal when the active selected mode currently has no work to perform. It is evidence about physical activity only and does not by itself mean that the selected or canonical control regime changed.

## Selected Standby is a control-authority boundary

When the configured storage mode selector is explicitly set to `Standby`, PicoT has no control authority for that storage execution scope.

For that scope PicoT may continue to:

- read telemetry;
- record evidence and history;
- build forecasts and planning snapshots;
- generate and evaluate plans for observability;
- expose diagnostics and explanations.

But PicoT must not:

- emit an executable storage control request;
- change the storage mode;
- issue charge or discharge setpoints;
- dispatch a storage command;
- use flow-validation mismatch as a reason to force the storage out of selected Standby.

Execution for that scope is suppressed fail-closed until the selected mode is no longer Standby and normal execution authority is re-established through the accepted execution path.

This suppression must be represented explicitly in execution evidence and must not be implemented as a vendor-specific exception inside a planner or Device Adapter.

## Delegated modes with idle device activity

A delegated selected mode remains the active control regime even when the device reports standby/idle because no action is currently necessary.

Example:

- selected mode: `Alleen slim ontladen`;
- canonical regime: `delegated_discharge_only`;
- PV exceeds household demand;
- charging is not allowed by the selected mode;
- storage device activity: standby;
- grid export: positive.

This is not a control failure merely because the grid baseline is non-zero. Export caused by contemporaneous PV surplus is compatible with `delegated_discharge_only` when the storage is not allowed to charge.

Closed-loop validation must therefore evaluate whether observed flow is physically compatible with the active regime and allowed directions, rather than blindly forcing every delegated regime toward a zero-watt grid baseline.

## Flow-validation implications

ADR-042's regime-aware validator remains the governing closed-loop contract, extended by this ADR as follows:

- control-regime intent and observed device activity are separate evidence fields;
- standby/idle device activity does not override an active delegated or forced regime;
- selected Standby suppresses storage execution authority entirely;
- grid import/export is interpreted in the context of the active regime and its allowed flow directions;
- a mismatch may only be raised where measured activity contradicts what the active regime actually requires or permits;
- when selected Standby is active, flow observation may report physical anomalies but may not request a corrective storage mode change.

## Execution implications

Before an Execution Plan for a storage scope may progress to an executable primitive request, runtime composition must verify that selected-mode authority permits control for that scope.

If selected mode is Standby:

- the plan may remain observable;
- execution evaluation for that storage scope returns an explicit suppressed/not-authorized result;
- no Device Adapter or dispatch path is invoked;
- no fallback policy may be used to escape selected Standby;
- a fresh user or system mode selection is required before storage control authority can resume.

## Observability

Diagnostics should expose at least:

- selected storage mode;
- canonical control regime;
- observed device activity state;
- control authority allowed/suppressed;
- suppression reason;
- measured grid flow;
- measured storage charge/discharge power;
- flow-validation status and recommendation.

These fields must refer to the same live snapshot when presented together.

## Fail-closed behavior

If the selected storage mode cannot be determined with sufficient confidence, PicoT must not assume storage control authority.

If selected mode is explicitly Standby, suppression is mandatory regardless of planner preference, candidate score, price opportunity or fallback policy.

## Consequences

### Positive

- transient Zendure Standby activity no longer corrupts the intended control regime;
- explicit user-selected Standby cannot be overridden through another execution path;
- delegated-discharge-only behavior can correctly tolerate PV export when charging is forbidden;
- flow validation becomes based on physical compatibility rather than a universal zero-watt baseline;
- selected user control boundaries remain traceable and fail-closed.

### Trade-offs

- runtime composition must carry selected-mode authority separately from device activity;
- execution validation requires an explicit authority check per storage scope;
- adapters must map vendor-specific mode/status fields into the separate canonical concepts.

## Non-goals

This ADR does not define:

- the economic strategy that chooses delegated, forced or standby modes;
- the vendor-specific Home Assistant service calls;
- the exact planner scoring for PV export or dynamic trading;
- user-rule precedence outside the existing accepted User Rules contract;
- a new safety function.
