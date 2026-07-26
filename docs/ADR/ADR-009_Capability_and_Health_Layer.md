# ADR-009 — Capability & Health Layer

Copyright © 2026 Alex Brons. All rights reserved.

| Field | Value |
|---|---|
| Status | Approved & Frozen |
| Date | 2026-07-26 |
| Decision scope | Architecture |

## Context

PicoT must not optimize solely because data or a device is technically present. It must determine whether information, integrations and devices are sufficiently trustworthy and capable under current conditions.

## Decision

PicoT shall include a dedicated Capability & Health Layer that answers:

> Can PicoT responsibly optimize in the current situation?

The layer produces a `CapabilityReport` and is responsible for:

- Data Health;
- Forecast Health;
- Device Health;
- Integration Health;
- Capability Resolution;
- Overall System Confidence.

A common health-assessment framework evaluates freshness, completeness, consistency, plausibility, source reliability and observed performance where applicable.

Health and Capability are separate concepts:

- Health describes technical condition or trustworthiness.
- Capability describes which functions remain responsibly available.

## Dynamic capability

Device capability is dynamic. Nominal specifications are never guaranteed real-time availability. Current capability is determined from observed state, operational conditions and verified device behavior.

Thermal derating is represented as degraded but potentially available capability, not automatically as device failure.

## Forecast reliability

Original forecasts remain immutable. PicoT derives separate reliability, confidence and conservative operational estimates from comparison with observed reality.

## Trends and retention

Short-term trends may be used to anticipate degradation. Relevant history is retained for explainability, reliability assessment and future learning.

## Consequences

- Decision components receive explicit capability and confidence information.
- Degradation remains explainable and localized.
- PicoT can continue operating at a reduced capability level.
- Future self-learning can be added without redesigning this layer.
