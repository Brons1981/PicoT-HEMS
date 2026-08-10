# PEP-RP-001 — Plan Deviation & Replanning

- **Status:** Accepted
- **Type:** Planner architecture and decision policy
- **Implementation:** Phased

## 1. Purpose

PicoT must continuously compare the expected energy plan with the actual behaviour of the home. A forecast deviation or unexpected energy flow must not automatically cause a control action. It must first trigger a deterministic review of whether the current plan is still feasible and economically sensible.

The governing principle is:

> PicoT does not react to a deviation; PicoT re-evaluates the plan.

This policy exists to prevent unnecessary switching, local optimisations and flip-flopping while still allowing PicoT to adapt when the real energy situation meaningfully diverges from the assumptions used by the planner.

## 2. Replan candidate is not an action

A signal such as `replan_candidate: true` is only a request to re-evaluate the current plan. It is not permission to immediately switch the battery, change a mode or replace the current schedule.

The replan flow is:

1. detect a meaningful deviation;
2. open a plan review;
3. determine whether the current plan is still feasible;
4. if feasible, keep the current plan;
5. if not feasible or materially suboptimal, calculate deterministic alternatives;
6. compare the alternatives over the remaining planning horizon;
7. change the plan only when the new plan is materially better or required to keep a target achievable;
8. record why the plan was kept or changed.

## 3. Deviation signals

Replanning must be driven by the observed effect on the complete energy balance, not by PV forecast deviation alone.

Relevant signals include:

- **PV deviation** — actual PV production differs structurally from the current forecast;
- **P1/grid deviation** — actual grid import or export differs structurally from the balance expected by the current plan;
- **load deviation** — observed or derived household demand differs structurally from the demand assumed by the plan;
- **battery deviation** — actual charge/discharge power or operating mode differs from the planned behaviour;
- **SoC trajectory deviation** — battery SoC is ahead of or behind the expected SoC trajectory;
- **known flexible-load changes** — for example an EV becoming connected or another large load becoming available, when this information is available to PicoT.

Signals may reinforce or cancel each other. A large PV deviation does not necessarily require action when the grid balance and SoC trajectory still indicate that the current plan remains achievable.

## 4. Current-plan feasibility first

Before calculating a replacement plan, PicoT must first test whether the current plan can still achieve its intended outcome.

The review should consider at least:

- current battery SoC;
- actual battery charge/discharge power;
- remaining time in the current price opportunity;
- future price opportunities still available;
- remaining expected PV production;
- actual and expected household demand;
- actual grid import/export;
- target SoC or other planner objectives;
- relevant system and user constraints.

A valid outcome is explicitly:

`current_plan_still_feasible`

In this case PicoT takes no control action even when a deviation signal is active.

Example:

- PV is materially below Solcast because of a large cloud;
- the battery is already charging under NOM;
- household demand remains normal;
- the target SoC is still expected to be reached within the remaining available time.

The correct result is to keep the existing plan.

## 5. P1 and energy-balance evidence

P1/grid behaviour is a primary validation signal for whether the current energy plan is still working in practice.

Examples:

- PV is below forecast, but grid import remains near the expected level and the SoC target remains feasible: no change is required;
- PV is below forecast and there is persistent unexpected grid import: review is strengthened because the real energy balance is no longer matching the plan;
- PV is near forecast but persistent extra grid import appears: this may indicate that household demand has increased or a new load has appeared;
- a large new load appears and SoC falls behind the planned trajectory: PicoT must re-evaluate the remaining charging and discharge opportunities.

PicoT does not need to identify the exact appliance before recognising that the energy balance has changed materially.

## 6. Anti-flip and stability policy

PicoT must avoid unnecessary switching between charge, discharge, NOM and standby states.

A temporary cloud, short load spike or single measurement must not cause a control change. Deviation evaluators may use rolling windows and minimum-history requirements to distinguish short-lived disturbances from persistent changes.

After a real planner action, a stability/cooldown mechanism may prevent repeated immediate reversals unless a materially stronger condition appears.

A recovery signal must also be treated with hysteresis: PicoT must not immediately reverse a previous decision because one sunny measurement or one normal P1 sample appears.

The objective is stable control with the minimum number of meaningful state changes required to achieve the planner objective.

## 7. Full-horizon battery decisions

A battery action is not an isolated local action. Every battery decision must be evaluated as part of a projected SoC trajectory over the remaining planning horizon.

If PicoT decides to discharge the battery now, it must simultaneously determine:

- how much energy may be discharged;
- the expected SoC after the discharge;
- whether that SoC remains within hard and user-defined constraints;
- how much energy must later be restored;
- which later PV or grid opportunities can restore that energy;
- whether the required recovery remains feasible;
- the expected economic result of the full discharge-and-recharge sequence.

The planner principle is:

> No discretionary battery discharge without a feasible recovery plan.

If a recovery path cannot be identified, or the recovery would make the full sequence economically unattractive, PicoT must not perform the discretionary discharge.

## 8. Economic discharge threshold

Battery discharge for price optimisation is permitted only when the complete expected cycle has sufficient positive value.

The economic comparison must include at least:

- avoided grid purchase or export value at the discharge moment;
- the expected future cost or opportunity cost of recharging;
- energy losses caused by battery round-trip efficiency;
- configured battery degradation/wear cost;
- a minimum profit or decision margin that prevents switching for negligible theoretical gains.

The governing rule is:

> Discharge for price optimisation only when expected benefit exceeds recharge cost, conversion losses, battery wear and the configured minimum margin.

A nominal price spread alone is insufficient. PicoT must compare the complete expected sequence.

## 9. Avoid local optimisation

PicoT must not select an action because it looks profitable at the current instant if the later recovery makes the total result worse.

For example, avoiding an expensive grid-import period by discharging the battery is not economically valid if the battery must later be recharged at a price that, after losses and wear, costs more than the avoided import.

The planner therefore evaluates alternatives over the remaining horizon rather than optimising only the current quarter-hour.

## 10. Explainability and decision records

Every plan review must be explainable even when PicoT decides to do nothing.

Decision records should be able to express outcomes such as:

- `current_plan_still_feasible`;
- `replan_not_materially_better`;
- `replan_economically_better`;
- `soc_target_at_risk`;
- `unexpected_grid_import_persistent`;
- `load_deviation_detected`;
- `discharge_not_profitable_after_losses`;
- `discharge_blocked_no_feasible_recharge_plan`;
- `replan_deferred_stability_window`.

The record should preserve the relevant evidence, including the state of PV forecast/actual production, P1/grid balance, load estimate, battery power, SoC, price opportunities and the comparison between the current and proposed plan.

A no-action decision is a first-class planner decision and must be traceable just like an active control change.

## 11. Interaction with hard constraints

This PEP does not override PicoT hard constraints, Safety Layer behaviour or valid higher-priority User Rules.

Any replan remains bounded by:

- hardware limits;
- minimum/maximum SoC constraints;
- battery and inverter operating constraints;
- Safety Layer state;
- valid PicoT User Rules and their defined priority behaviour;
- source availability and data-quality requirements.

## 12. Phased implementation

### Phase 1 — Plan review foundation

Connect existing deviation signals to a deterministic plan-review step rather than directly to an action.

Required outcome:

- `replan_candidate` triggers a review;
- PicoT can explicitly decide `current_plan_still_feasible`;
- no battery action is changed when the current plan remains feasible.

### Phase 2 — P1/load and SoC trajectory deviation

Add structural comparison between expected and actual grid balance, household load and battery SoC trajectory.

### Phase 3 — Alternative-plan comparison

Calculate deterministic alternatives when the current plan is no longer feasible or materially suboptimal. Add anti-flip, stability and minimum-improvement rules.

### Phase 4 — Full economic battery cycling

Allow discretionary discharge/recharge sequences only when a complete recovery plan exists and the sequence remains profitable after recharge cost, RTE losses, battery wear and minimum margin.

## 13. Design statement

> PicoT continuously verifies whether reality still supports the current plan. Deviations trigger a review, not an impulsive action. PicoT keeps a valid plan when possible, changes it only when necessary or materially better, and never performs a discretionary battery action without considering the complete SoC trajectory, recovery path and economic result.