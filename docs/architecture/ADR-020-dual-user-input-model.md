# ADR-020 — Dual User Input Model

## Status

Accepted

## Context

PicoT must remain accessible to non-technical users while still offering meaningful additional expressiveness to advanced users.

A second rule engine or unrestricted scripting interface would create inconsistent validation, unsafe behaviour, and duplicated architecture.

## Decision

Where functionally appropriate, PicoT provides two input modes:

- Simple mode;
- Expert mode.

Both modes produce the same validated internal configuration model and use the same execution path.

## Simple mode

Simple mode is the default and uses visual, guided input similar to a block or flow editor.

Characteristics:

- limited to common combinations;
- only valid options are offered;
- understandable labels;
- immediate validation;
- no technical syntax required.

## Expert mode

Expert mode is explicitly opt-in and offers additional expressiveness, including where applicable:

- nested AND/OR groups;
- more detailed time windows;
- confidence and forecast conditions;
- Planning Hints;
- compound conditions;
- advanced comparisons;
- multiple validated actions.

Expert mode never receives additional authority.

> More expressiveness does not mean more rights.

## Shared internal model

```text
Simple visual input
or
Expert PicoT DSL
        ↓
Parser and semantic validator
        ↓
Immutable internal configuration record
        ↓
Shared rule, planning and execution pipeline
```

Expert text is never executed directly.

## Hard boundaries

Expert mode must not provide direct access to:

- Python, shell, YAML execution, Jinja or arbitrary code;
- filesystem or database;
- arbitrary network requests;
- Event Bus internals;
- Planner internals;
- Safety state mutation;
- Device Adapters or raw vendor commands;
- arbitrary Home Assistant services;
- arbitrary Homey flows;
- unapproved external targets.

Only an allowlisted, versioned PicoT DSL and validated action catalogue may be used.

## External actions

In both modes, Home Assistant automations, scripts and Homey flows must first be explicitly selected and approved by the user.

PicoT never chooses an external automation or flow on its own.

## Conversion between modes

A Simple rule may be shown as Expert representation.

An Expert rule may only be converted to Simple mode when all used constructs can be represented without information loss.

PicoT must never silently simplify or discard Expert logic.

## Planning Hints

Both modes may produce the same internal Planning Hint:

- Simple mode through guided fields where exposed;
- Expert mode through the PicoT DSL.

The Planning Hint remains planning metadata and does not alter rule evaluation.

## Core principle

> Simple mode offers the most common combinations. Expert mode offers the full supported PicoT configuration language within the same hard system boundaries.

> Expert mode adds precision and expressiveness, never permission to bypass PicoT Core, Safety, validation, conflict handling or the Execution Pipeline.
