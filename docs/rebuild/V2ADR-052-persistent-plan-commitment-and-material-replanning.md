# V2ADR-052 — Persistent Plan Commitment and Material Replanning

Status: **Accepted for PicoT v2 rebuild**

## Context

PicoT currently rebuilds a planning outcome when normalized source content
changes. During an active storage-acquisition phase, ordinary progress such as
an increasing SOC or varying PV power can therefore produce a new plan even
though no accepted material condition changed.

Process-local execution memory can prevent an immediate vendor-mode switch,
but it is not Planning Context, is lost on restart and cannot be considered by
Candidate Evaluation. That violates the commitment and material-change rules
of ADR-027 and ADR-034.

V2ADR-051 also refers to ADR-047. ADR-040 through ADR-047 are excluded from the
authoritative v2 architecture baseline and cannot be used as authority.

## Decision

V2ADR-052 supersedes the plan-continuity portion of V2ADR-051. The storage-mode
lifecycle and BMS-calibration decisions of V2ADR-051 remain valid where they
are independently supported by ADR-001 through ADR-039 and accepted V2 ADRs.

### One durable plan context

PicoT persists one immutable current plan context per execution scope. It
contains at least the stable plan and revision identity, active phase bounds,
canonical primitive, source policy, target and remaining energy, lifecycle
status, selection evidence and explicit replacement or completion reason.

The context is supplied to every subsequent Planning Input Snapshot. Restart
recovery validates time, capability and source evidence before restoring it.
Invalid state fails closed and is reported; it is never silently accepted.

### Progress is not replanning

Raw telemetry updates observations and plan progress. It does not directly
request a Planner Run. The Runtime Monitor from ADR-034 is the sole authority
that classifies an accepted material change.

Expected SOC progress, ordinary PV-power variation and changes within explicit
forecast/load/price hysteresis remain non-material. Safety, hard constraints,
manual authority, active capability loss, target completion and producer-owned
accepted material thresholds may request replanning.

### Incumbent-first evaluation

The Candidate Engine always represents the valid remaining incumbent plan as
a complete Energy Path. Challengers also cover the complete remaining horizon.
The Evaluation Engine retains the incumbent unless a higher-priority necessity
or an explicit total-objective improvement exceeding the switching margin is
proven. The record exposes incumbent, challenger, objective difference, margin
and reason.

An active phase is fixed until completion unless Safety, a hard constraint,
manual authority, capability loss or technically unavoidable recovery requires
an abort. Material evidence may revise future phases without rewriting the
active phase.

### Canonical ownership

- Candidate Engine owns complete alternative Energy Paths.
- Evaluation Engine exclusively selects and replaces plans.
- Execution Plan Builder converts the winning Energy Path exactly once and may
  not invent baseline or transition segments.
- Execution Engine owns plan lifecycle and due-segment validation.
- Device Adapter only translates an approved Execution Primitive.
- Vendor feedback records execution progress and never performs planning.

There is one live control path. Parallel logic may exist only as explicitly
observer-only verification and must not dispatch.

## Migration rule

Migration proceeds as one compatibility line: persist current execution
commitments, include them in Planning Input, gate Planner Runs through the
Runtime Monitor, move incumbent/challenger selection to the canonical engines,
then remove the superseded v2 selection and runtime hold logic. Intermediate
states must remain fail-closed and must not add a second live authority.

## Verification

Release acceptance requires deterministic incident replay proving:

- one stable plan identity and revision throughout ordinary SOC progress;
- no replan for non-material PV, load or price variation;
- explicit revision for accepted material future changes;
- explicit abort only for the allowed hard reasons;
- restoration of an active commitment after restart;
- exact Energy Path to Execution Plan conversion;
- no Core dependency on vendor mode strings.

## Authority

This decision derives from ADR-015, ADR-016, ADR-017, ADR-027, ADR-028,
ADR-031 through ADR-039, V2ADR-048 and V2ADR-050. It does not use ADR-040
through ADR-047 as architectural authority.
