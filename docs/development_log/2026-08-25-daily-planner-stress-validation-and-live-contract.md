# Development Log — 2026-08-25 — Daily planner stress validation and live contract

## Purpose

This log closes the 2026-08-25 live observation session. It records the
evidence from the canonical-versus-daily comparison, the storage incident and
recovery, the controlled household-load tests, and the agreed direction for a
future live execution slice.

No grid-charging, storage-export or planner-promotion production change is part
of this log.

## Controlling user decision: freeze the proven daily-planner behaviour

The current independent daily planner behaviour is accepted and must be treated
as a frozen behavioural baseline.

Future work must not change, reinterpret or replace its:

- authoritative full-horizon simulation;
- lower, central and upper PV scenario handling;
- physical completeness gates;
- target-reached and reserve-respected admission rules;
- PV-first source preference;
- rule that grid supplementation is excluded while PV-only remains proven;
- average charge-window price comparison;
- continuously recalculated, quarter-hour-aligned window selection;
- response to measured SoC, household load, PV and tariff changes;
- ability to widen, narrow or shift a window while preserving the energy goal;
- observer evidence, lineage and explainability.

In particular, no planner-level commitment or window hysteresis may be added to
silence quarter-hour movement. Such a change could suppress the adaptive
behaviour proven today. Stability for live device commands belongs after the
winning daily result, at Commitment and Execution boundaries.

Any future change that touches the daily simulation, strategy generation,
candidate construction or evaluation requires a separate user decision and
must first replay the acceptance evidence described in this log.

## Test configuration

The canonical planner remained the live planner. The independent daily planner
remained observer-only. Home Assistant and the @gielz Zendure integration
continued to own device telemetry and physical protection.

Controlled disturbances included:

1. manual fast battery discharge;
2. disabling the GoodWe entity in Home Assistant while P1 still measured the
   real grid flow;
3. placing the physical GoodWe inverter in standby, producing an exact 0 W PV
   period;
4. restoring PV;
5. removing PV during an active charge session;
6. injecting approximately 600 W additional household load;
7. increasing the injected household load to approximately 2,000 W;
8. restoring the original household load.

The artificial load used the same Shelly/P1 source consumed by PicoT and the
@gielz integration. The resulting physical grid flow was allowed and remained
visible at P1.

## Planner findings

### Canonical planner

The canonical planner retained a committed PV-only window. During disturbances
it did not widen the active window sufficiently and ended one tested day without
reaching the intended SoC. The comparison is not completely symmetric because
the canonical planner does not yet have an equivalent grid-charge route.

The result nevertheless demonstrates the material limitation of committing the
exact window too early: a valid strategy can become physically insufficient as
SoC, household load or PV changes.

### Independent daily planner

The daily planner showed the desired closed-loop planning behaviour throughout
the session:

- it kept the energy goal and PV-first strategy stable;
- it recalculated from current Planning Input snapshots;
- it widened the PV window when measured conditions required more opportunity;
- it narrowed and shifted the remaining window when conditions recovered;
- it admitted grid supplementation only when PV-only was proven insufficient;
- it returned from grid supplementation to PV-only after recovery;
- it continued household support after a completed 100% charge when the reserve
  remained protected;
- it did not treat GoodWe availability as a special planning rule; it responded
  to the resulting measured energy balance instead.

The observed strategy sequence during the PV disturbance was:

`PV-only -> widened PV-only -> PV plus grid supplementation -> recovered PV-only`

This is the intended adaptive behaviour.

## Controlled household-load evidence

At approximately 19:11 local time an additional 600 W load was introduced.
PicoT measured about 849 W instead of the preceding approximately 250 W,
confirming an effective increase of roughly 598 W.

At approximately 19:31 the injected load was increased to 2,000 W. Measured
household power became approximately 2.26 kW. The daily planner responded
progressively rather than treating one sample as authoritative:

- 19:31: 12:00-15:00;
- 19:35: 12:00-15:15;
- 19:40: 11:30-15:15;
- 19:45: 11:30-15:30;
- 19:50: 11:30-15:45;
- 19:55: 11:30-16:15;
- 20:05: 11:00-16:00;
- 20:10: 10:30-15:45.

The load was removed at approximately 20:13. P1 immediately returned to about
168 W. The daily window did not immediately collapse because the measured load
history and resulting forecast still contained the sustained high-load period.

The final diagnostic evidence showed a 10:30-15:45 local PV-only window of 21
quarter-hours. Its width had a physical reason:

- lower PV scenario reached the target at 15:45, exactly at window end;
- central scenario reached the target at 12:45;
- upper scenario reached the target at 12:30;
- every scenario was physically complete;
- every scenario reached the target;
- every scenario respected reserve.

The wider window was therefore required by the lower scenario and was not an
arbitrary price preference.

## Quarter-hour window movement

After load recovery, several equivalent or near-equivalent windows moved one
quarter forward and backward. Diagnostics prove that:

- charge-window confidence remained constant at 37.57%;
- minimum horizon confidence remained 0%;
- the strategy remained PV-only;
- small household measurements changed the physical admissibility boundary;
- Evaluation then selected the admitted window with the lowest average charge
  price;
- differences between the best and next admitted window were commonly only
  EUR 0.00024-EUR 0.00095 per kWh.

The movement is therefore caused by the combination of a discrete physical
feasibility boundary and extremely small average-price differences. It is not a
confidence change or a strategy change.

This behaviour is acceptable at the planner boundary. A future live execution
layer may avoid repeating equivalent device commands, but it must not freeze or
distort the planner result.

## Storage incident and recovery

Before dev.156, `picot_v2_planner_comparison_state.json` grew to 1,453,833,327
bytes and the add-on was killed. Dev.156 quarantined the oversized state and
recovered without changing planner behaviour.

Dev.157 bounded daily-observer persistence:

- latest result maximum: 16 MiB;
- history maximum: 128 MiB;
- full winning detail: 48 hours, at most one per hour;
- compact run evidence: up to 14 days subject to the hard byte ceiling;
- losing candidate trajectories are no longer duplicated in full.

Live evidence after dev.157:

- `picot_v2_daily_observer_latest.json` fell from about 140.5 MB to approximately
  166-178 kB;
- no latest-result truncation was required;
- the planner comparison state remained below its 64 MiB ceiling;
- the add-on remained operational throughout the load test.

Remaining storage observation: compact daily history still grew by several MB
per hour because every run retains all compact evaluation records. The hard
128 MiB limit prevents unbounded growth, but the practical time retention may be
shorter than 14 days at the current run rate. Further compaction is permitted
only as a storage-only change that preserves all decision evidence needed for
diagnosis; it must not touch planner behaviour.

## Session conclusion

The 2026-08-25 stress test is considered successful. The independent daily
planner is the clear behavioural winner. It adapts to actual conditions while
remaining close to the original energy goal and source preference. The canonical
planner's exact-window commitment is a demonstrated limitation.

The next comparison should include grid charging and dynamic trading because a
planner that only proposes but never executes those actions cannot be validated
as a closed loop: execution changes SoC and therefore every subsequent plan.

## Proposed future live contract

The next implementation is proposed as one live, closed-cycle capability rather
than a separate observer-only trial.

### Planner roles

- promote the independent daily planner to the sole live planner;
- demote the canonical planner to observer-only comparison;
- technically prevent both planners from dispatching at the same time.

### Acquisition and trading semantics

- permit `grid_requirement` for proven target acquisition and for a complete,
  profitable trading cycle;
- generate `storage_export` candidates only as part of a complete horizon
  simulation;
- permit export only above proven reserve and future household/storage need;
- evaluate sale and later replacement together;
- require the complete cycle to remain net positive after import price, export
  value and conversion losses;
- replan from measured SoC and energy flows after every executed interval;
- do not introduce an arbitrary fixed price-margin rule without a separate user
  decision.

### Device execution mapping

PicoT must retain ownership of planning and timing and use normal @gielz modes as
the execution boundary:

- `household_support_only` -> `Alleen slim ontladen`;
- PV-only `nom` -> `Nul op de meter`;
- `grid_requirement` -> `Snel opladen`;
- `storage_export` -> `Snel ontladen`;
- explicit safe idle -> `Standby` only when the winning plan requires it.

Zendure's vendor-provided dynamic trading modes remain excluded. PicoT must not
delegate its planning decision to `Dynamisch Handelen`, `Dynamisch NOM` or their
variants.

The @gielz integration remains responsible for physical operational limits,
including minimum and maximum SoC and configured charge/discharge power. PicoT
must never invent unavailable device capabilities.

### Commitment boundary

- the daily planner remains free to calculate a new best window every run;
- a started quarter-hour execution command is not repeatedly replaced by an
  equivalent command;
- commitment applies to the active acquisition or trading task, not to freezing
  the future planner window;
- hard safety, loss of capability, explicit user control or physical
  infeasibility may interrupt execution;
- after the active interval, the next decision uses current measured state.

This execution stability is not planner hysteresis and must not be implemented
inside the frozen daily-planner calculation.

## Required acceptance evidence for the future implementation

Before release, tests must prove at minimum:

1. the current daily-planner regression scenarios remain byte-for-byte or
   semantically unchanged at the planner result boundary;
2. only one planner has dispatch authority;
3. a proven PV-only path still excludes unnecessary grid charging;
4. a proven PV deficit can dispatch `Snel opladen` in the selected interval;
5. a complete profitable cycle can dispatch `Snel ontladen` and later reacquire
   energy without violating reserve;
6. an unprofitable or incomplete cycle cannot dispatch;
7. mode feedback, restart, stale snapshots and missing capabilities fail closed;
8. execution returns to `Alleen slim ontladen` after completion;
9. diagnostics preserve the planned-versus-measured closed-loop evidence.

Implementation must begin in a new session. This log does not authorise a
late-evening production release.
