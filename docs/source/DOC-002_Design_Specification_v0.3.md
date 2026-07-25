# DOC-002 Design Specification

| Field | Value |
|---|---|
| Status | Draft |
| Version | 0.3 |
| Date | 2026-07-25 |
| Approved chapters | 1, 2 and 3.1 |

## 1. Document Information

### Purpose

This document defines the functional and architectural design of HEMS Core.

### Audience

- Project Owner
- Developers
- Testers
- Future Contributors

### Related Documents

- DOC-001 README
- DOC-003 Architecture
- DOC-004 Data Dictionary
- DOC-005 Entity Registry
- DOC-006 Design Decisions
- DOC-007 Project Status
- DOC-008 Roadmap
- DOC-009 Test Plan
- DOC-010 Project Rules

## 2. Purpose & Vision

### 2.1 Purpose

HEMS Core is an intelligent, modular and reliable Home Energy Management System. It continuously determines the best overall operating strategy for the residential energy ecosystem while balancing safety, cost, battery lifetime, self-consumption and user preferences.

### 2.2 Vision

HEMS Core acts as the central intelligence layer above Home Assistant integrations. Every significant decision must be explainable and traceable. Safety always takes precedence over optimisation.

### 2.3 Mission Statement

To continuously determine the best possible energy decision while balancing safety, reliability, cost, comfort, battery lifetime, solar self-consumption and user preferences.

### 2.4 Success Criteria

- Reliable autonomous operation.
- Explainable decisions.
- Minimal unnecessary battery relay switching.
- Protection of connected equipment.
- Graceful handling of integration failures.
- Future-proof modular architecture.

### 2.5 Guiding Principles

- Safety First
- Modular Architecture
- Hardware Independence
- Transparency & Explainability
- Reliability

### 2.6 Transparency & Explainability

HEMS Core shall never operate as a black box.

For every significant decision it shall be possible to determine:

- What decision was made.
- Why the decision was made.
- Which inputs and policies were used.
- Which alternatives were rejected.
- What outcome was expected.
- The confidence level.
- Whether execution was successful.

The user should always be able to answer the question **“Why is HEMS Core doing this?”** without inspecting YAML, automations or source code.

### 2.7 Decision Hierarchy

1. Safety
2. System Integrity
3. Equipment Protection
4. User Policies
5. Energy Optimisation
6. Comfort

## 3. Architecture

Chapter 3 defines the architecture of HEMS Core itself. Home Assistant is the runtime platform and user interface, but it is not the architecture.

### 3.1 Architecture Vision

#### 3.1.1 Purpose

HEMS Core is designed as a modular, scalable and extensible Home Energy Management System. It determines the best energy decision at any moment using current data, forecasts, user policies and safety rules.

The architecture is deliberately independent of specific hardware, energy suppliers and Home Assistant integrations. New technologies and changing market conditions must be accommodated without redesigning the core architecture.

Home Assistant acts as the runtime platform and user interface. Energy logic and decision-making remain inside HEMS Core.

#### 3.1.2 Architecture Goals

- Safety always has priority.
- Decisions are transparent, traceable and explainable.
- Functionality is modular and loosely coupled.
- New devices and integrations can be added through defined interfaces.
- Failures remain isolated where possible.
- The system remains maintainable throughout its lifecycle.
- The architecture scales from resource-constrained hosts such as a Raspberry Pi to more capable systems.

#### 3.1.3 Design Philosophy

##### Safety First

No optimisation may compromise user safety, equipment safety or installation integrity. When safety and optimisation conflict, safety always wins.

##### Explainable by Design

HEMS Core is not a black box. Every significant decision must be explainable, reproducible and auditable.

For every significant decision, HEMS Core must be able to answer:

- What was decided?
- Why was this decision made?
- Which data was used?
- How current and reliable was that data?
- Which policies were active?
- Which Safety Guards were evaluated?
- Which alternatives were considered?
- Why were alternatives rejected?
- What confidence level was assigned?
- What outcome was expected?
- What was the actual execution result?
- Did the result differ from the expectation, and why?
- Which module made the decision?
- Which HEMS Core version and configuration were active?
- Was the action executed successfully, or was a fail-safe activated?

##### Separation of Responsibilities

Each module has one clear responsibility and does not take over responsibilities assigned to another module.

##### Loose Coupling

Modules communicate through defined interfaces and events. Functional modules do not depend directly on hardware integrations.

##### Vendor Independence

HEMS Core must not depend on one manufacturer, supplier or integration. New adapters must be addable without changing core decision logic.

##### Event-Driven Architecture

HEMS Core reacts to relevant events such as price changes, battery-state changes, forecast updates, policy changes and health changes. Periodic validation remains available as a configurable safety net.

##### Deterministic by Design

Under equivalent inputs, policies, configuration and system state, HEMS Core should reach the same decision. This improves predictability, testing and auditability.

##### Progressive Degradation

When data or integrations are unavailable, HEMS Core remains safe and deliberately falls back to a lower capability level instead of failing unpredictably.

#### 3.1.4 Architecture Principles

- One central decision-maker: the Decision Engine.
- One central safety validation layer: the Safety Layer.
- Controllers are the only modules permitted to translate approved decisions into device actions.
- Integrations contain no energy strategy.
- The dashboard presents information and captures user intent, but does not make energy decisions.
- Every significant decision creates an explainability and audit record.
- Rejected alternatives are recorded with a reason.
- HEMS Core shall never make a silent decision.
- Unnecessary switching between charging and discharging must be prevented.

#### 3.1.5 Non-Goals

HEMS Core is not:

- A replacement for Home Assistant.
- A collection of unrelated Home Assistant automations.
- A device-specific battery controller.
- A mandatory cloud platform.
- A closed vendor ecosystem.

HEMS Core is a modular decision layer that runs on Home Assistant and makes energy decisions using objective data, user policies and safety controls.

#### 3.1.6 Functional Dependencies and Capability Assessment

HEMS Core is vendor-independent, but the quality and scope of its decisions depend directly on the availability, freshness and quality of input data. Missing data must reduce capability, never safety.

Minimum data for safe basic operation:

- Current household import/export power from a P1 meter or equivalent source.
- Current battery state, including State of Charge, operating mode and availability.
- A supported battery integration exposing safe control entities or services.
- Basic PV-system status.

Recommended data for effective optimisation:

- PV-production forecast, for example Helios or Solcast.
- Dynamic electricity prices.
- Actual PV inverter power.
- Historical consumption and production data.
- Relevant weather information.
- Integration-specific diagnostics, including the estimated Zendure relay-switch count where available.

HEMS Core distinguishes three independent system views:

| View | Question | Meaning |
|---|---|---|
| System Health | Is the system technically working? | Status of integrations, sensors, data freshness and execution feedback. |
| Safety Status | May this action be executed safely? | Result of Safety Guards and fail-safe conditions. |
| Capability Level | Which functions can currently be offered responsibly? | Available functionality based on required healthy inputs and integrations. |

Capability levels:

- **Full** — all required integrations and data are available; all supported functions are enabled.
- **Advanced** — all core functions are available; one or more advanced optimisations are unavailable.
- **Basic** — safe operation remains available, but predictive or market-driven optimisation is restricted.
- **Limited** — only safe fallback behaviour and essential monitoring are available.

Capability is reassessed at startup and whenever relevant health or data-quality events occur. HEMS Core activates only those functions for which all required inputs and integrations are available and healthy.

#### 3.1.7 Explainability Retention

Explainability is mandatory, but retention duration and detail level are configurable so HEMS Core remains suitable for resource-constrained systems such as a Raspberry Pi.

The configuration shall support at least:

- Retention duration for detailed decision records.
- Retention duration for compact decision summaries.
- A separate retention duration for safety incidents, errors and execution deviations.
- A configurable purge interval.
- Storage profiles such as minimal, balanced, extended and custom.

Retention settings must never remove information required for current safety decisions, and audit storage must not endanger host stability.

### 3.2 Architecture Overview

Status: Planned. The approved high-level structure will include:

- Dashboard / UI
- Safety Layer
- Decision Engine
- Planner
- Policy Engine
- Optimizer
- Explainability & Audit Layer
- Battery Controller
- Integration Layer
- Cross-cutting Core Services and Health Monitor

## Chapter Status

| Chapter | Status |
|---|---|
| Chapter 1 | Approved |
| Chapter 2 | Approved |
| Chapter 3.1 | Approved |
| Document | Draft |
