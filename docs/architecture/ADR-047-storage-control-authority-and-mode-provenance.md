# ADR-047 — Storage Control Authority and Mode Provenance

**Status:** Accepted  
**Date:** 2026-08-13

## Context

Live flow validation exposed an ambiguity between three different concepts that must not be collapsed:

1. the selected device-facing operating mode;
2. the canonical PicoT control regime used for flow validation;
3. the observed instantaneous device activity state.

Zendure may report `Standby` as its actual activity while a delegated mode such as `Alleen slim ontladen` remains selected. In that situation the battery is simply idle because there is nothing to discharge; the selected control regime has not changed.

A second and more important ambiguity concerns control authority. A selector value can have fundamentally different origins:

- PicoT may have set it as the result of a valid Execution Plan;
- a user or another external actor may have manually selected a mode after PicoT's last command.

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

### PicoT-owned state

When PicoT successfully writes a selector value through the normal Execution -> Adapter -> Dispatch path, it records that write as the authoritative `last_picot_selected_mode` for the scope.

If the currently observed selector continues to equal that PicoT-owned state and no later manual or external mode selection is detected, `control_authority = picot`.

This remains true for every mode value, including `Standby`.

```text
PicoT sets Standby
-> current selector remains Standby
-> control_authority = picot
-> later valid planning/execution may change the selector again
```

`Standby` is therefore not intrinsically a permanent lock-out state.

## Manual mode takeover

**Any manual mode selection by the user or another external actor transfers normal mode-control authority away from PicoT.**

This rule is independent of which mode is selected. It applies equally to `Standby`, `Alleen slim ontladen`, `Slim laden`, any future delegated mode, or any other mode exposed through the storage mode selector.

Examples:

```text
PicoT last set: Alleen slim ontladen
User selects: Standby
-> control_authority = external
-> PicoT may not alter mode select
```

```text
PicoT last set: Standby
User selects: Slim laden
-> control_authority = external
-> PicoT may not alter mode select
```

```text
PicoT last set: Slim laden
User selects: Alleen slim ontladen
-> control_authority = external
-> PicoT may not alter mode select
```

The semantic trigger is the manual/external selection event itself, not a particular target mode string.

A later planner result does not silently reacquire authority merely because it prefers another mode. Time, prices, forecasts, flow mismatch, battery activity, restart, selector coincidence, or a new planning winner must not restore authority automatically.

## Scope of suppression

When `control_authority != picot` because of a manual mode takeover:

- PicoT may still collect telemetry;
- PicoT may still build snapshots, forecasts and plans;
- PicoT may still evaluate candidates;
- PicoT may still expose what it would have preferred;
- PicoT may still produce diagnostics and replan evidence;
- PicoT must not emit or dispatch any normal command that changes the storage mode selector for that scope;
- no planner result, fallback policy, adapter behavior or flow-observer recommendation may silently restore mode-control authority.

This suppression concerns **mode select authority** for the affected storage scope. Safety-layer semantics remain separate and retain their accepted priority and best-effort behavior.

## Reacquiring authority

Automatic reacquisition after manual takeover is forbidden.

The implementation must provide an explicit user-facing **Reset control authority / Give control back to PicoT** action per affected storage scope.

When the user invokes the reset:

1. PicoT records the reset request with timestamp and execution scope ID;
2. the current selector and current device state are observed again before authority is restored;
3. stale PicoT write provenance from before the takeover is not reused as if no takeover occurred;
4. `control_authority` may transition from `external` to `picot` only through this explicit reset path or another higher-priority accepted contract;
5. the reset itself does not immediately issue a battery mode or setpoint command;
6. after authority is restored, the next normal valid Planner -> Evaluation -> Execution cycle may decide whether the selector should change;
7. the authority restoration is logged and exposed in diagnostics.

```text
PicoT last set: Alleen slim ontladen
User selects: Standby
-> control_authority = external
-> PicoT mode control suppressed

User selects: Give control back to PicoT
-> authority reset recorded
-> control_authority = picot
-> no immediate mode command is implied
-> next valid planning/execution cycle may change the selector
```

The reset must be idempotent: invoking it while `control_authority = picot` must not create a synthetic device command or duplicate ownership transition.

If PicoT cannot obtain sufficient current evidence when the reset is requested, authority restoration fails closed and remains `external` until a later explicit reset can be validated.

## Selected mode versus device activity

`selected_mode` represents the persistent operating selection presented to the device/integration.

`device_activity_state` represents what the battery is physically doing now.

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
- otherwise the observer may continue to observe device state and flow, but must not manufacture corrective PicoT mode control from stale intent;
- `device_activity_state = standby` is not itself a regime change;
- any manually selected mode with `control_authority = external` must never trigger a planner-driven mode-selector change.

A separate follow-up decision may refine delegated-discharge-only baseline semantics for PV-surplus export; this ADR does not redefine ADR-042's tracking equations.

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

When manual/external takeover is detected, PicoT records at least:

- previous PicoT-owned selector value;
- newly observed selector value;
- takeover detection timestamp;
- `control_authority = external`;
- reason such as `manual_mode_selection_detected` or `selector_changed_outside_picot_dispatch`.

When authority is reset by the user, PicoT records at least:

- execution scope ID;
- reset request timestamp;
- authority before reset;
- authority after reset;
- current observed selector value;
- current observed device activity state where available;
- reset result (`restored` or fail-closed reason).

## Restart behavior

Control authority must not be guessed after restart.

If PicoT cannot prove from persisted provenance that the currently observed selector state is still the result of its own last valid write and that no later manual/external selection occurred, the storage scope starts fail-closed with no normal PicoT mode-control authority until the explicit user authority-reset path or another accepted authority-restoration path grants it.

Persisted provenance must therefore be sufficient to distinguish a PicoT-owned selector state from a manually selected or otherwise unverified selector state after restart.

## Layer responsibilities

- **Planner / Evaluation:** may express the preferred Energy Path but does not own selector authority.
- **Execution layer:** must validate that PicoT has authority before producing an executable mode change.
- **Control Authority / Provenance component:** owns last-writer provenance, manual takeover detection, reset validation and authority state per execution scope.
- **Device Adapter:** translates validated requests only and does not infer authority from vendor state strings.
- **Flow Observer:** observes selected mode, control regime and device activity separately; it never grants authority.
- **Presentation/Diagnostics:** exposes provenance and authority and provides the explicit user reset action, but does not bypass authority validation.

## Non-goals

This ADR does not:

- change accepted ADR-042;
- define economic mode selection;
- define vendor-specific mode names as Core concepts;
- declare every actual `Standby` activity report to be a user override;
- permit planner output alone to reacquire control authority;
- let the reset action itself choose or dispatch a new operating mode;
- change Safety Layer priority.

## Consequences

Positive:

- any user-selected mode is respected until the user explicitly gives control back to PicoT;
- no special-case behavior is tied only to `Standby`;
- PicoT can legitimately set any mode itself and later change it while it still owns authority;
- transient device `Standby` activity no longer destroys the intended control regime;
- authority becomes deterministic, persisted and explainable;
- selector value, selector origin, control regime and device activity no longer carry overloaded meanings.

Costs:

- execution needs a persisted per-scope authority/provenance record;
- dispatch acknowledgement and selector observation must be correlated;
- manual selector changes must be detected reliably;
- a user-facing authority reset action and diagnostics are required;
- restart behavior becomes intentionally fail-closed when provenance cannot be proven.

## Core principle

> PicoT may change a storage mode only when it can prove that it still owns mode-control authority for that scope. Any manual mode selection transfers that authority away from PicoT, regardless of which mode was selected. Only an explicit reset may hand normal mode control back to PicoT.
