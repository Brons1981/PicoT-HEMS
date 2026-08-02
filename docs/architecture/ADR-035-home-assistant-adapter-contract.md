# ADR-035 — Home Assistant Adapter and Controlled Dispatch Contract

**Status:** Accepted  
**Date:** 2026-08-02

## Context

PicoT Core now produces validated, vendor-independent `ExecutionPrimitiveRequest` records. The next implementation step is a controlled Home Assistant integration for dry-run and one-capability live testing.

ADR-001 and ADR-015 require the Core and Planner to remain independent of Home Assistant entity IDs, service names and vendor modes. ADR-016 requires execution to validate current reality before dispatch, while ADR-034 requires runtime outcomes to remain observable and capable of requesting replanning.

A concrete adapter contract is still missing:

- how one logical capability is mapped to a Home Assistant service call;
- which fields belong to configuration and which belong to an execution request;
- how dry-run and live dispatch differ without changing translation logic;
- how unsupported primitives and incomplete mappings are rejected;
- how command traceability is preserved;
- how secrets and Home Assistant authentication remain outside stored domain records.

Implementing these decisions directly in adapter code would hide architecture in the implementation.

## Decision

PicoT introduces a Home Assistant Device Adapter at the existing adapter boundary.

The first implementation supports exactly one generic Execution Primitive:

- `CHARGE_AT_POWER`

and translates it through one explicit mapping to one of these Home Assistant service forms:

- domain: `number`, service: `set_value`; or
- domain: `input_number`, service: `set_value`.

Both forms use:

- service data key: `value`;
- target key: `entity_id`.

This is a deliberately narrow first slice for controlled dry-run and live validation. It does not make Zendure modes part of PicoT Core.

## Explicit mapping

A `HomeAssistantCommandMapping` is immutable and contains at least:

- mapping identifier;
- mapping version;
- logical capability identifier;
- execution scope identifier;
- supported Execution Primitive;
- Home Assistant domain;
- Home Assistant service;
- target entity identifier;
- service data value key;
- optional scale factor;
- optional minimum and maximum accepted numeric value;
- enabled flag.

Mappings are configuration records. The adapter never discovers, guesses or silently replaces an entity during execution.

The initial `CHARGE_AT_POWER` mapping converts `requested_power_w` to the configured numeric service value. The default scale factor is `1.0`, so watts remain watts unless an explicitly accepted mapping states otherwise.

## Translation output

Translation produces one immutable `HomeAssistantServiceCall` containing:

- command identifier;
- source execution request identifier;
- plan-set, plan, segment, execution-scope and capability references;
- mapping identifier and version;
- Home Assistant domain and service;
- target mapping;
- service data mapping;
- creation timestamp;
- dispatch mode;
- implementation version.

The adapter does not call Home Assistant while translating.

## Dispatch modes

Supported dispatch modes are:

- `DRY_RUN` — produce and log the exact service call but do not send it;
- `LIVE` — allow the already translated service call to be sent by the Home Assistant dispatcher.

Dry-run and live mode use identical translation and validation. Switching to live mode may not alter domain, service, target or service data.

The operational default is `DRY_RUN`. Live mode must be selected explicitly by the caller.

The HTTP transport has its own explicit runtime mode and also defaults to `DRY_RUN`. A network request is permitted only when both conditions are true:

1. the immutable `HomeAssistantServiceCall` is marked `LIVE`;
2. the HTTP transport is explicitly constructed in `LIVE` mode.

A dry-run transport refuses all network sends. A live transport refuses service calls that are not marked `LIVE`. This creates two independent, visible gates without changing the service-call contents.

## Validation

Translation is rejected when:

- the mapping is disabled;
- the capability or execution scope does not match the execution request;
- the mapping version is invalid;
- the primitive is not supported by the mapping;
- `CHARGE_AT_POWER` has no requested power;
- the resulting numeric value is outside configured mapping bounds;
- the domain/service pair is not `number.set_value` or `input_number.set_value`;
- domain, service, target or service-data key is empty;
- timestamps are not timezone-aware.

Transport dispatch is rejected when:

- the HTTP transport is not explicitly in `LIVE` mode;
- the supplied service call is not explicitly in `LIVE` mode.

No partial or fallback command is produced.

## Dispatch result

A dispatcher returns an immutable `HomeAssistantDispatchResult` with at least:

- command identifier;
- dispatch mode;
- dispatch status;
- attempted timestamp;
- response status where available;
- error reason where applicable.

Initial statuses are:

- `DRY_RUN_ONLY`;
- `DISPATCHED`;
- `REJECTED`;
- `FAILED`.

Transport authentication, base URL and access tokens are runtime configuration and may never be stored in ADRs, mappings, logs or repository files.

## Runtime feedback

A rejected or failed live dispatch becomes an `EXECUTION_OUTCOME_CHANGED` Runtime Observation. The Runtime Monitor determines whether replanning is required according to ADR-034.

The Home Assistant adapter and dispatcher do not invoke the Planner directly.

## Determinism and traceability

For identical immutable inputs and implementation version, translation produces the same command identifier, target and service data.

Every Home Assistant command remains traceable through:

```text
HomeAssistantDispatchResult
→ HomeAssistantServiceCall
→ HomeAssistantCommandMapping
→ ExecutionPrimitiveRequest
→ ExecutionRecord
→ ExecutionPlanSegment
→ ExecutionPlan
→ EvaluationRecord
→ PlanningInputSnapshot
```

## Initial implementation boundary

The first implementation includes:

1. immutable mapping, service-call and dispatch-result records;
2. deterministic `CHARGE_AT_POWER` translation to an accepted `set_value` service;
3. explicit `DRY_RUN` and `LIVE` modes;
4. strict mapping and numeric-bound validation;
5. dispatcher and HTTP transport with explicit dry-run defaults;
6. dual live gating at service-call and transport level;
7. unit tests and CI coverage.

It does not include:

- entity discovery;
- access-token storage;
- automatic entity replacement;
- vendor mode selection;
- retries or batching;
- acknowledgement polling;
- support for additional primitives;
- direct Planner invocation.

## Relationship to existing ADRs

- ADR-001: the Planner continues to consume logical capabilities only;
- ADR-004 and ADR-007: mappings remain persistent and are never silently replaced;
- ADR-010: mapping versions remain traceable;
- ADR-011: Home Assistant configuration ownership remains explicit;
- ADR-015: only Device Adapters translate Execution Primitives;
- ADR-016: execution validation precedes vendor-specific dispatch;
- ADR-027: adapter dispatch does not change execution commitments;
- ADR-034: failed execution outcomes feed deterministic runtime monitoring and replanning.

## Core principle

> PicoT translates one validated generic execution request through one explicit, versioned Home Assistant mapping. Dry-run and live dispatch use the same immutable service call; live mode changes only whether that call is sent, never what it means.
