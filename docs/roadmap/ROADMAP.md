# PicoT HEMS Roadmap

## Status

Active

## Current direction

PicoT HEMS follows a Core-first development strategy. The architecture and Core Framework are stabilized before optimization features and broad device support are expanded.

## Phase 1 — Architecture Baseline

Status: Completed and frozen as Architecture Baseline v1.0.

Purpose:

- establish component responsibilities;
- define the capability-driven architecture;
- define records, interfaces and boundaries;
- prevent vendor-specific planner design.

## Phase 2 — Core Framework

Status: Active.

Primary deliverables:

- repository and package structure;
- immutable records and stable interfaces;
- strict dependency rules;
- Shared Kernel governance;
- logging and diagnostics foundations;
- lifecycle and event infrastructure;
- automated tests and contract tests;
- formal ADR, CFD and PEP administration.

Optimization logic is not the first priority. Infrastructure and contracts come first.

## Phase 3 — Supporting Product Capabilities

Planned supporting work may include:

- Forecast integration;
- dashboards;
- Preferences and Configuration Wizard;
- diagnostics export;
- documentation;
- Device Pack development;
- explainability interfaces.

These additions must not destabilize the Core.

## Phase 4 — Operational Validation

### Phase 4A — Private Alpha

Indicative duration: 0–6 months.

Scope:

- one installation;
- real Home Assistant environment;
- Core stabilization;
- recovery and failure-path validation;
- no uncontrolled major feature expansion.

Permitted parallel work:

- Forecast;
- dashboards;
- Config Wizard;
- diagnostics;
- documentation.

### Phase 4B — Trusted Validation Partners

Indicative duration: 6–12 months.

Scope:

- approximately two to three selected users;
- deliberately varied hardware;
- validate capability abstraction;
- collect additional real-world diagnostics;
- verify architecture and recovery behaviour outside the original installation.

Diagnostics exports must make problems reproducible without requiring unsafe sharing of private Home Assistant data.

### Phase 4C — Stable Core

Target: after at least one year of practical operation.

Minimum conditions:

- no unresolved critical bugs;
- explainable and reproducible decisions;
- proven recovery behaviour;
- usable diagnostics and export tooling;
- current documentation;
- stable supported-device contracts;
- operational experience across the primary installation and trusted validation partners.

## Long-term platform direction

PicoT may expand into a wider ecosystem, for example:

- PicoT HEMS;
- PicoT Zendure;
- PicoT Marstek;
- PicoT Remeha heat-pump modules;
- other capability-providing Device Packs.

Device Packs register discovery, semantic rules, capability mappings and adapters. PicoT HEMS consumes capabilities without requiring planner changes for each vendor.

## Roadmap principle

Stable Core before broad expansion. Transparency, diagnostics and reproducibility remain release requirements, not optional refinements.
