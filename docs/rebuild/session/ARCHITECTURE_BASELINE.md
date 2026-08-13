# PicoT v2 Session Architecture Baseline

Status: **AUTHORITATIVE SESSION BOOTSTRAP**

This file is the first architecture document to read at the start of every PicoT v2 development session.

## Historical baseline

The rebuild is anchored to the original PicoT Core v0 Architecture Map:

- file: `docs/architecture/ARCHITECTURE_MAP.md`
- commit: `8197abbefd969f10da5a8f27244862be07998299`
- created: `2026-08-01T21:12:40Z`
- commit message: `docs(architecture): add PicoT Core v0 architecture map`

Accepted ADR-001 through ADR-039 are the architectural foundation for the rebuild. Later ADRs do not retroactively redefine this baseline unless deliberately reviewed and accepted into v2 after the original pipeline is reconstructed and proven.

## Canonical rebuild contract

Read next:

`docs/rebuild/CANONICAL_PIPELINE_CONTRACT.md`

That contract freezes the single canonical pipeline, ownership, immutability, traceability and nine-card live-validation rules.

## Core invariants

- Planner consumes logical capabilities, never vendor-specific entities.
- Planning uses immutable atomic snapshots.
- One canonical fact has one owner.
- One canonical derivation has one owner.
- No downstream component silently mutates, reinterprets or replaces upstream canonical data.
- No parallel planner/runtime/control path may be added to test or implement functionality.
- Execution Plan Builder converts the Winning Energy Path without reinterpretation.
- Execution Engine validates/executes; it does not make new energy decisions.
- Vendor translation occurs only at the Device Adapter boundary.
- Every decision and execution request remains end-to-end traceable.
- Only one Planner Run may be active; material changes create a fresh snapshot/replan after the accepted stabilisation interval.
- Safety and hard physical constraints override optimisation.

## Version line

PicoT v2 rebuild versions start at:

`2.0.0-dev.x`

The v1 implementation is legacy/reference only and has no architectural authority over v2.

## Session rule

Do **not** begin a session by syncing or reading the full repository.

At session start read only:

1. this file;
2. `docs/rebuild/CANONICAL_PIPELINE_CONTRACT.md`;
3. `docs/rebuild/session/DEVELOPMENT_LOG.md`;
4. `docs/rebuild/session/SESSION_PROTOCOL.md`.

Only after the exact current position is known may GitHub be queried for the specific files needed for the next approved step.
