# ADR-046 — Execution Fallback Policy Registry and Selection

**Status:** Accepted  
**Date:** 2026-08-13

## Context

ADR-016 requires every Execution Plan to reference a fallback policy and requires validation to confirm fallback availability. ADR-033 requires the `ExecutionPlanBuilder` caller to supply one explicit non-empty `fallback_policy_id` and explicitly forbids the builder from inventing or selecting that policy.

During live recovery step 2, PicoT can now preserve the real typed `EvaluationResult`, but no canonical fallback-policy record, registry, runtime selection rule or configured policy identity exists. Supplying an arbitrary string would therefore satisfy only the type contract while bypassing the architectural intent of ADR-016 and ADR-033.

This ADR defines the missing contract without modifying the accepted ADRs.

## Decision

PicoT introduces a vendor-independent Execution Fallback Policy Registry. A fallback policy is an immutable, versioned execution-domain record referenced by `fallback_policy_id` from an `ExecutionPlan`.

A fallback policy is not a second planner and may not make a new energy optimisation decision. It defines only the deterministic execution-layer response when the current plan or segment cannot continue normally and no higher-priority Safety or User Rule action already determines the outcome.

The normal chain remains:

```text
EvaluationResult
→ ExecutionPlanSet
→ Execution Plan Store
→ Execution Engine
→ ExecutionPrimitiveRequest
→ Device Adapter
→ Vendor Command
```

Fallback handling occurs only inside the existing Execution layer and never bypasses replanning.

## Initial canonical policy

The first canonical policy is:

`execution-fallback:hold-and-replan:v1`

Its semantics are:

1. do not invent, mutate or substitute an energy action;
2. do not reinterpret the failed segment into another Execution Primitive;
3. do not emit a vendor command solely because fallback was entered;
4. preserve the currently observed device state unless a higher-priority accepted contract requires a different action;
5. record the failure/rejection reason and the fallback-policy identity;
6. request replanning through the accepted runtime/replan path with fresh evidence;
7. keep the affected plan/segment non-executable until a valid replacement plan or accepted higher-priority action exists.

This policy is intentionally fail-closed with respect to new PicoT control. It does not mean that the physical device is guaranteed to remain electrically unchanged; it means PicoT does not create a new unplanned command as fallback behaviour.

Safety Layer behaviour remains separate and has priority over this policy.

## Registry

The registry owns immutable policy definitions and resolves a `fallback_policy_id` to exactly one known policy version.

The registry must reject:

- unknown policy IDs;
- duplicate IDs with differing contents;
- empty IDs;
- policies without an explicit version;
- policies whose semantics require planner optimisation or vendor-specific commands.

The initial implementation may use an in-process static registry because the initial policy set is code-owned and versioned. A future configurable registry requires a separate accepted architectural decision.

## Plan construction input

For the initial live execution path, runtime composition supplies the canonical policy ID explicitly to `ExecutionPlanBuilder`:

`execution-fallback:hold-and-replan:v1`

This is not a hidden Plan Builder default. The builder remains policy-agnostic and receives the policy identity as an explicit atomic input exactly as ADR-033 requires.

Before a plan may progress beyond `PROPOSED`, the Execution layer must resolve the referenced policy in the registry. An unresolved reference fails validation closed.

## Baseline paths

A valid baseline Winning Energy Path with no controllable segments still produces an empty `ExecutionPlanSet` under ADR-033. The explicit fallback policy input remains required for deterministic construction, but no fallback action exists because no plan segment exists to execute.

The builder does not invent a standby segment or vendor command.

## Replanning ownership

Fallback policy execution may request replanning but does not itself build a replacement Energy Path or Execution Plan.

The replacement route remains:

```text
execution failure/rejection
→ fallback evidence
→ accepted runtime/replan mechanism
→ fresh Planning Input Snapshot
→ normal Planner pipeline
→ new EvaluationResult
→ new ExecutionPlanSet
```

## Layer responsibilities

- **Planner / Evaluation:** selects the Winning Energy Path; no fallback semantics.
- **ExecutionPlanBuilder:** copies the explicit fallback policy reference into scope-specific plans; no policy selection or interpretation.
- **Fallback Policy Registry:** resolves immutable policy identity and semantics.
- **Execution Engine:** applies the resolved policy only after a relevant execution failure/rejection condition.
- **Device Adapter:** translates only validated Execution Primitive Requests; it does not interpret fallback policies.
- **Runtime composition:** supplies the configured/canonical policy identity and records evidence; it does not invent fallback behaviour.

## Explainability

When fallback is invoked, PicoT records at least:

- plan ID and segment ID where applicable;
- fallback policy ID and version;
- triggering validation/execution outcome;
- evidence IDs;
- whether replanning was requested;
- whether a fresh snapshot is required;
- whether a higher-priority Safety or User Rule action superseded fallback handling.

## Non-goals

This ADR does not:

- create a new Planner or optimiser;
- define vendor-specific mode strings;
- define Zendure-specific fallback behaviour;
- allow direct planner-to-device commands;
- change accepted Safety Layer semantics;
- define retries, acknowledgements or commitment state transitions beyond existing ADR ownership;
- authorise automatic standby as a generic fallback command.

## Relationship to existing ADRs

- ADR-015 remains authoritative for generic Execution Primitives and adapter separation.
- ADR-016 remains authoritative for Execution Plan structure, validation and execution boundaries.
- ADR-027 remains authoritative for commitments and dynamic allocation.
- ADR-033 remains authoritative for deterministic Winning Energy Path to ExecutionPlanSet conversion and explicit caller-supplied fallback references.
- ADR-034 remains authoritative for runtime material-change replanning where applicable.
- ADR-035 remains authoritative for Home Assistant adapter/dispatch control.

## Consequences

Positive:

- step 2 can supply a meaningful fallback reference without a magic string;
- fallback availability becomes genuinely validateable;
- the ExecutionPlanBuilder remains free of hidden policy;
- failure behaviour remains deterministic, vendor-independent and traceable;
- no workaround or parallel control path is required.

Costs:

- a small fallback-policy domain model/registry must exist before the live Execution chain can progress beyond plan construction;
- Execution Engine integration must later record and apply the policy consistently.

## Core principle

> A fallback reference is an executable contract reference, not a placeholder string. When normal execution cannot continue, PicoT records the failure and returns to the accepted planning path instead of inventing a new device action inside the Execution layer.
