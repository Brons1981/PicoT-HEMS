# ADR-047 — Storage Control Authority and Mode Provenance

**Status:** Proposed  
**Date:** 2026-08-13

## Context

Live flow validation exposed an ambiguity between three different concepts that must not be collapsed:

1. the selected device-facing operating mode;
2. the canonical PicoT control regime used for flow validation;
3. the observed instantaneous device activity state.

Zendure may report `Standby` as its actual activity while a delegated mode such as `Alleen slim ontladen` remains selected. In that situation the battery is simply idle because there is nothing to discharge; the selected control regime has not changed.

A second and more important ambiguity concerns control authority. A selector value such as `Standby` can have two fundamentally different origins:

- PicoT may have set it as the result of a valid Execution Plan;
- a user or another external actor may have changed it after PicoT's last command.

The selector value alone therefore cannot determine whether PicoT is still allowed to modify that storage scope.

Accepted ADR-042 remains frozen. This ADR adds the missing authority and provenance contract without modifying ADR-042.

## Decision

PicoT introduces explicit per-storage-scope control provenance and authority state.

The runtime must distinguish at least:

- `selected_mode`: the current device-facing selector value;
- `selected_mode_origin`: who last established the currently observed selected mode;
- `last_picot_selected_mode`: the last selector value successfully written by PicoT;
- `last_picot_mode_write_id`: traceable identity of that successful PicoT write;
- `control_authority`: whether PicoT currently owns the right to alter the storage selector;
- `control_regime`: the canonical intended control regime for flow validation;
- `device_activity_state`: the currently observed physical activity such as charging, discharging or standby.

These are separate facts and must not be inferred from one another by string equality alone.

## Authority rule

PicoT retains control authority over a storage scope only while the currently observed selector state remains attributable to PicoT's own latest valid write, or while an explicit higher-priority accepted contract grants PicoT authority.

For the initial implementation:

### PicoT-owned state

When PicoT successfully writes a selector value through the normal Execution -> Adapter -> Dispatch path, it records that write as the authoritative `last_picot_selected_mode` for the scope.

If the currently observed selector continues to equal that PicoT-owned state and no later external change is detected, `control_authority = picot`.

This remains true even when the selected value is `Standby`.

Therefore:

```text
PicoT sets Standby
-> current selector remains Standby
-> control_authority = picot
-> later valid planning/execution may change the selector again
```

`Standby` is not intrinsically a permanent lock-out state.

### External/user takeover

If the current selector changes after PicoT's last successful write and the change is not attributable to a current PicoT dispatch, PicoT must treat that as an external takeover.

For example:

```text
PicoT last set: Alleen slim ontladen
User changes selector to: Standby
-> control_authority = external
-> PicoT may not alter the selector through normal planner/execution control
```

The same rule applies to any user/external change, not only Standby.

A later planner result does not silently reacquire authority merely because it prefers another mode.

## Reacquiring authority

Automatic reacquisition after an external takeover is forbidden.

The initial implementation must remain fail-closed until an explicit accepted mechanism restores PicoT control authority for that storage scope. That restoration mechanism may be a dedicated user action or another explicit contract, but it must not be inferred from time, price, a new planner winner, device activity or selector coincidence.

A future user-facing authority control requires its own implementation decision if not already covered by an accepted contract.

## Selected mode versus device activity

`selected_mode` represents the persistent operating selection presented to the device/integration.

`device_activity_state` represents what the battery is physically doing now.

Examples:

```text
selected_mode = Alleen slim ontladen
device_activity_state = standby
control_regime = delegated_discharge_only
```

is valid when PV surplus means there is nothing to discharge.

Likewise, an integration may report temporary standby activity while another delegated mode remains selected. The flow observer must not replace the canonical control regime merely because the physical device is currently idle.

## Flow validation consequence

ADR-042 remains authoritative for regime-aware flow validation, but its runtime inputs must respect this ADR:

- canonical `control_regime` comes from current PicoT-owned execution intent when PicoT has authority;
- otherwise the observer may continue to observe device state and flow, but must not manufacture corrective PicoT control from stale intent;
- `device_activity_state = standby` is not itself a regime change;
- an externally selected Standby state with `control_authority = external` must never trigger a planner-driven selector change.

A separate follow-up decision may refine delegated-discharge-only baseline semantics for PV-surplus export; this ADR does not redefine ADR-042's tracking equations.

## Execution suppression boundary

When `control_authority != picot` for a storage scope:

- PicoT may still collect telemetry;
- PicoT may still build snapshots, forecasts and plans;
- PicoT may still expose what it would have preferred;
- PicoT may still produce diagnostic/replan evidence;
- PicoT must not emit a selector-changing or setpoint-changing Execution Primitive for that scope;
- Device Adapters must not dispatch a normal PicoT control command for that scope;
- no fallback policy may silently restore control authority.

Safety-layer semantics remain separate and retain their accepted priority and best-effort behavior.

## Provenance requirements

Every PicoT-originated selector write that can establish or retain control authority must be traceable with at least:

- execution scope ID;
- requested selector/control target;
- execution request ID;
- dispatch/write ID;
- requested at timestamp;
- acknowledgement/observation timestamp where available;
- resulting observed selector value;
- whether the write successfully established PicoT authority.

When external takeover is detected, PicoT records at least:

- previous PicoT-owned selector value;
- newly observed selector value;
- takeover detection timestamp;
- `control_authority = external`;
- reason such as `selector_changed_outside_picot_dispatch`.

## Restart behavior

Control authority must not be guessed after restart.

If PicoT cannot prove from persisted provenance that the currently observed selector state is still the result of its own last valid write, the storage scope starts fail-closed with no normal PicoT control authority until the accepted authority-restoration path explicitly grants it.

Persisted provenance must therefore be sufficient to distinguish a PicoT-owned state from an unverified selector state after restart.

## Layer responsibilities

- **Planner / Evaluation:** may express the preferred Energy Path but does not own selector authority.
- **Execution layer:** must validate that PicoT has authority before producing an executable scope action.
- **Control Authority / Provenance component:** owns last-writer provenance and authority state per execution scope.
- **Device Adapter:** translates validated requests only and does not infer authority from vendor state strings.
- **Flow Observer:** observes selected mode, control regime and device activity separately; it never grants authority.
- **Presentation/Diagnostics:** exposes provenance and authority without changing them.

## Non-goals

This ADR does not:

- change accepted ADR-042;
- define economic mode selection;
- define vendor-specific mode names as Core concepts;
- declare every actual `Standby` report to be a user override;
- allow planner output alone to reacquire control authority;
- define the final user-interface mechanism for handing authority back to PicoT;
- change Safety Layer priority.

## Consequences

Positive:

- a user/manual selector change cannot be silently overwritten by a later planner run;
- PicoT can legitimately leave a battery in Standby and later change it again when PicoT itself owns that state;
- transient device `Standby` activity no longer destroys the intended control regime;
- authority becomes deterministic, persisted and explainable;
- selector value, regime and device activity no longer carry overloaded meanings.

Costs:

- execution needs a persisted per-scope authority/provenance record;
- dispatch acknowledgement and selector observation must be correlated;
- restart behavior becomes intentionally fail-closed when provenance cannot be proven.

## Core principle

> PicoT may change a storage control state only when it can prove that it still owns control authority for that scope. The current selector value says what is selected; provenance says who is allowed to change it next.
