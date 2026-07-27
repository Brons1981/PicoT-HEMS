# ADR-008 — Canonical Domain Models

**Status:** Accepted

## Decision

PicoT HEMS introduces **Canonical Domain Models** as the stable abstraction between external integrations and the decision core.

## Rule

Changes in market structures, tariff resolutions, providers or devices must be absorbed by adapters and canonical models, not by the decision core.

## Consequences

- Stable Decision Layer
- Future-proof against market changes
- Easier testing
- Hardware and provider independence
