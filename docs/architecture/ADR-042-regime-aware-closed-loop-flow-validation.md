# ADR-042 — Regime-aware closed-loop flow validation

- Status: Proposed
- Date: 2026-08-12
- Decision scope: Planner feedback, runtime flow validation and replan evidence
- Related: ADR-015, ADR-016, ADR-017, ADR-037, ADR-038, ADR-039, ADR-041

## Context

PicoT continuously observes real household power flows after and during planning. Live testing showed that a generic rule such as "battery discharging while the grid is exporting" is not sufficient to decide that control is wrong.

Some storage modes deliberately delegate fast balancing to the storage integration. In those modes short import/export excursions are normal, especially when a large household load switches on or off. Other modes deliberately request a fixed direction or neutral battery state. Negative-price operation can intentionally create large grid import, disable PV generation, increase household demand and charge storage at high power.

Therefore the same measured P1, PV and battery flow can be correct in one control regime and contradictory in another.

The runtime validator must know the intended control regime before interpreting live flow. It must also use time and hysteresis rather than reacting to individual telemetry samples.

## Decision

PicoT introduces a canonical `control_regime` for closed-loop validation. The Core remains vendor-independent. Adapters translate generic regimes to vendor-specific modes.

The initial regimes are:

| Control regime | Meaning | Typical Zendure mapping |
|---|---|---|
| `delegated_bidirectional` | External controller performs fast balancing; charge and discharge are allowed | NOM |
| `delegated_discharge_only` | External controller performs fast balancing; discharge is allowed but charging is not | Slim ontladen |
| `forced_charge` | PicoT deliberately requests charging at a planned power/setpoint | Handmatig laden |
| `forced_discharge` | PicoT deliberately requests discharge at a planned power/setpoint | Handmatig ontladen |
| `standby` | PicoT requests storage to remain neutral | Standby |

Vendor mode names are not part of the Core contract.

## Regime-specific interpretation

### Delegated bidirectional

Short P1 import/export oscillations around the balance point are expected and are not a planner error.

A contradiction may be raised only when the regime-specific unwanted condition persists beyond its temporal threshold. For the first implementation, the important NOM condition is sustained PV availability together with battery discharge and grid export. This is evidence that stored energy may be consumed while contemporaneous PV is already exceeding household demand.

The validator must not treat a transient excursion caused by load switching as a contradiction.

### Delegated discharge-only

The external controller still performs the fast regulation. Therefore individual P1 samples are not evaluated as failures.

Tracking is evaluated against the intended grid baseline using hysteresis and elapsed time. The first implementation assumes a zero-watt baseline unless a candidate explicitly supplies another baseline.

### Forced charge

Grid import can be intentional and must not be interpreted using delegated-balancing rules. Validation checks whether storage is actually charging in the requested direction and, when a setpoint is available, whether actual charge power tracks the requested setpoint within the applicable tolerance.

A negative-price strategy may intentionally combine forced charging, PV curtailment or shutdown, and increased household demand. Those conditions are expected when they are part of the selected Energy Path and must not create false flow conflicts.

### Forced discharge

Grid export can be intentional. Validation checks whether storage is discharging in the requested direction and, when a setpoint is available, whether actual discharge power tracks the requested setpoint within the applicable tolerance. Export alone is not a contradiction.

### Standby

P1 import or export is not itself relevant. Validation checks battery power around zero. Household load and PV may freely create grid import or export while storage remains neutral.

## Hysteresis and temporal validation

The initial v1 tracking bands are fixed defaults:

- **green:** absolute regime-specific tracking deviation `< 50 W`;
- **grey:** deviation `50–150 W`;
- **red:** deviation `> 150 W`.

The bands are interpreted with independent timers:

- entering green resets grey and red persistence;
- red must persist for **120 seconds** before it becomes actionable evidence;
- grey is tolerated longer, but grey persisting for **300 seconds** becomes actionable evidence;
- moving between grey and red does not manufacture an immediate action; elapsed persistence is tracked explicitly according to the active band;
- telemetry frequency must not change the semantic duration. The decision is based on elapsed time, not a fixed sample count.

For regime-specific boolean contradictions, such as sustained PV + battery discharge + grid export under delegated bidirectional operation, the contradiction must persist for **120 seconds** before intervention. Brief recovery caused only by measurement noise must not cause rapid timer flapping; the implementation may use the same 50/150 W hysteresis concepts where an appropriate measured deviation exists.

The initial values `50 W`, `150 W`, `120 s` and `300 s` are deterministic v1 defaults. They may become configurable later, but configurability is not required for initial live control.

## Planner integration

The validator is evidence-producing, not an actuator.

The closed-loop path remains:

`telemetry -> current flow observation -> Planning Input Snapshot -> Candidate Generation -> Evaluation -> Execution/Dispatch -> new telemetry`

When a temporal threshold is reached, the observation produces canonical evidence and a replan reason. Candidate Generation and Evaluation decide the corrective Energy Path. The validator must never directly switch a vendor mode.

A regime change resets validation state because the expected physical behavior has changed.

## Initial NOM / Slim-ontladen live-control behavior

The first live-control slice may expose only `delegated_bidirectional` and `delegated_discharge_only`.

PicoT may switch between those regimes only through a valid winning candidate and the normal execution/dispatch contract.

For `delegated_discharge_only`, sustained baseline tracking outside the accepted bands becomes replan evidence:

- `> 150 W` for 120 s -> action/replan;
- `50–150 W` for 300 s -> action/replan;
- `< 50 W` -> tracking healthy and timers reset.

For `delegated_bidirectional`, normal NOM oscillation is accepted. Sustained contradictory PV + battery discharge + grid export for 120 s becomes replan evidence; transient excursions do not.

## Observability

The Planner Inspector and diagnostic entities should expose at least:

- active `control_regime`;
- responsibility (`delegated` or `picot_setpoint`);
- measured tracking deviation where applicable;
- current validation band (`green`, `grey`, `red`);
- grey elapsed/limit seconds;
- red elapsed/limit seconds;
- active contradiction, if any;
- proposed planner intervention;
- selected candidate;
- requested action;
- executed action and result when live control is enabled.

All values shown for one Planner Run must refer to the same snapshot ID.

## Fail-closed behavior

If PicoT cannot determine the active control regime with sufficient certainty, it must not infer a corrective live-control action from generic P1 flow alone. It may continue observing and expose the uncertainty in diagnostics.

If required telemetry for the active regime is missing or stale, the corresponding validation result is unavailable rather than assumed healthy.

## Consequences

### Positive

- normal NOM regulation no longer creates false planner conflicts;
- Slim ontladen can be assessed without reacting to individual P1 spikes;
- standby, forced charge and forced discharge have explicit and different physical expectations;
- negative-price strategies can intentionally import power without fighting the flow observer;
- validation behavior is deterministic and independent of telemetry sample rate;
- future storage adapters can reuse the same Core regimes.

### Trade-offs

- the runtime must maintain temporal state per execution scope and control regime;
- candidate/execution state must expose the intended regime to the observer;
- regime-specific validation requires more explicit contracts than a single generic mismatch rule.

## Non-goals

This ADR does not define:

- the economic rule that selects NOM, Slim ontladen, forced charge, forced discharge or standby;
- the negative-price strategy itself;
- vendor service calls or Home Assistant entity IDs;
- configurable end-user thresholds;
- dynamic trading policy.

Those decisions remain in their respective planner, strategy and adapter layers.
