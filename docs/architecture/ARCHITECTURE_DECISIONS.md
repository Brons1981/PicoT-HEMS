# PicoT HEMS Architecture Decisions

This index contains accepted architectural decisions. Detailed ADR files may be added when a decision requires more context.

## Accepted decisions

### ADR-001 — Planner uses capabilities only
The planner consumes logical capabilities and never vendor-specific entities or integration details directly.

### ADR-002 — Discovery is not a runtime fallback mechanism
Discovery is used to identify candidate sources during setup or targeted rediscovery. It is not continuously rerun because a source is temporarily unavailable.

### ADR-003 — Semantic validation precedes selection
A source may only be selected after it has passed deterministic semantic validation.

### ADR-004 — Capability mappings are persistent
A validated mapping remains selected until objective evidence proves it permanently invalid.

### ADR-005 — Temporary unavailability is not invalidity
`TEMPORARILY_UNAVAILABLE` must not trigger automatic replacement or rediscovery.

### ADR-006 — Rediscovery is capability-scoped
Rediscovery affects only the invalid capability. Unrelated domains and capabilities remain untouched.

### ADR-007 — Source replacement is never silent
PicoT may propose an alternative source and explain its advantages and disadvantages, but user confirmation is required when a change can affect behaviour.

### ADR-008 — Primary meter and realtime power source are distinct roles
A primary P1 meter may remain authoritative while a separate CT meter is deliberately selected for faster realtime power measurements.

### ADR-009 — Mapping history is retained
Selection reasons, rejected candidates, timestamps, lifecycle changes, and historical mapping versions must remain traceable.

### ADR-010 — Planner decisions reference mapping versions
Every stored decision must identify the capability mapping version and source data used.

### ADR-011 — Configuration ownership is explicit
Externally managed configuration is read-only for PicoT unless ownership is explicitly assigned to PicoT.

### ADR-012 — Missing expected information triggers diagnosis
PicoT must not merely state that information was not recorded when required layers should have recorded it. The surrounding available data and layer statuses must be exportable for diagnosis.

### ADR-013 — Runtime contains no AI or LLM
The future PicoT bot and runtime interfaces are deterministic and may only retrieve and present stored historical data, decision records, and available forecasts.

### ADR-014 — Architecture is future-proof; v0.1 implementation remains minimal
Necessary structural contracts are designed now, while non-essential functionality is deferred to the roadmap.
