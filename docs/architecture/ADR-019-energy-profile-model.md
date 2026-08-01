# ADR-019 — Energy Profile Model

## Status

Accepted

## Context

PicoT must be able to anticipate future energy demand and supply caused by native Device Adapters, User Rules, explicit Home Assistant automations, Homey flows, manual actions, and future modules.

The logic that determines when an action is triggered is different from the data that describes the expected energy impact of that action.

External automations and flows remain black boxes. PicoT never assumes their internal behaviour.

## Decision

User Rules and Energy Profiles remain separate Core concepts.

A User Rule primarily defines:

- when;
- under which conditions;
- which action;

is executed.

In Expert mode, a User Rule may additionally contain an optional Planning Hint describing user-declared expected energy impact.

The Planning Hint affects planning only. It does not change IF, AND, OR, THEN evaluation.

## Planning Hint

Example:

```yaml
planning_hint:
  expected_power_w: 2400
  expected_duration_minutes: 300
  expected_energy_wh: 11500
  source: USER_DECLARED
```

A Planning Hint is intended for external actions whose impact PicoT cannot know in advance, including:

- explicitly selected Home Assistant automations;
- explicitly selected Homey flows;
- external scripts;
- custom user logic.

The Planning Hint is optional.

## No Planning Hint

When no Planning Hint exists:

```text
User Rule becomes true
→ explicit external action is triggered
→ energy impact is UNKNOWN before execution
→ actual system state changes
→ material capability changes trigger replanning
```

PicoT does not invent an energy profile.

## Planning Hint present

When a Planning Hint exists:

```text
User Rule becomes relevant
→ Planner anticipates declared impact
→ action is triggered
→ actual effect is observed
→ material deviation triggers replanning
```

The UI must clearly state that the profile is user-declared and not verified by PicoT.

## Managed Energy Profile

A Planning Hint may later evolve into a Managed Energy Profile when:

- learning is enabled;
- sufficient observations exist;
- a native Device Adapter provides reliable data.

A Managed Energy Profile is an independent, versioned Core object containing, where available:

- expected power;
- expected duration;
- expected energy;
- time-varying power shape;
- confidence;
- sample count;
- source;
- learning state;
- history.

The User Rule itself remains unchanged.

## Learning boundary

Learning may only update the energy profile or its confidence.

Learning must never modify:

- IF conditions;
- AND/OR grouping;
- THEN action;
- selected Home Assistant automation;
- selected Homey flow;
- User Rule enable state.

PicoT learns only observed energy effects, never the internal logic of an external automation or flow.

## External actions

PicoT may trigger only external actions explicitly selected by the user.

PicoT knows:

- the selected target;
- the trigger moment;
- the acknowledged execution result, where available.

PicoT does not know or infer:

- the internal automation logic;
- which devices it controls;
- whether internal conditions suppress actions;
- the actual energy impact before observation.

## Sources

Supported profile sources include:

```text
USER_DECLARED
LEARNED_OBSERVED
DEVICE_ADAPTER
```

No default device-category profile may be assumed for an external action merely because the user labels it as an EV, washing machine, dryer, boiler, or other appliance.

## Explainability

Every planning decision using a Planning Hint or Managed Energy Profile must expose:

- profile or hint identifier;
- source;
- confidence;
- declared or observed values;
- whether actual impact materially deviated;
- whether replanning followed.

## Core principle

> A User Rule defines the logic of an action. A Planning Hint optionally describes the expected energy impact of that action. Learning may evolve this hint into a Managed Energy Profile without modifying the User Rule.

> An Energy Profile describes an expected energy flow over time, not the internal behaviour of a device, automation, or flow.
