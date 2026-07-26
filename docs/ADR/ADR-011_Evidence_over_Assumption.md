# ADR-011 — Evidence over Assumption

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Status | Approved & Frozen |
| Date | 2026-07-26 |
| Decision scope | Principle |

## Context

PicoT must distinguish hard facts from calculations, estimates and unknowns. Hidden assumptions undermine trust, explainability and verification.

## Decision

PicoT shall base every significant decision on measured, verified or explicitly qualified information.

Information priority:

1. Measured
2. Verified
3. Calculated
4. Estimated with confidence
5. Unknown

When certainty is unavailable, PicoT shall expose confidence and provenance rather than present assumptions as facts.

Every significant input and result shall identify, where relevant:

- source;
- timestamp;
- freshness;
- evidence type;
- confidence;
- reason codes.

## Consequences

- Decisions become auditable and reproducible.
- Forecasts and learned models remain explicitly qualified.
- Dashboards can show why information is trusted or degraded.
- Users do not need to guess why PicoT behaves in a particular way.
