# PEP — Phase Load and Voltage Monitoring

## Status
Proposed — Future Core Enhancement

## Priority
High

## Purpose
PicoT should in the future monitor load and, where available, voltage per grid phase to improve planning, diagnostics, runtime protection and installation insight.

## Scope
When supported by the connected meter or integration, PicoT may use:

- current per phase;
- power per phase;
- voltage per phase;
- total import and export;
- phase loss;
- voltage deviation;
- phase imbalance;
- PV inverter curtailment or shutdown correlated with phase voltage.

## Functional goals
The feature may support:

- Household Power Capacity Management;
- per-phase planning constraints;
- dynamic power reduction;
- EV load balancing where supported;
- battery power reduction;
- phase-imbalance detection;
- high- and low-voltage warnings;
- phase-loss handling;
- installation insight and installer advice;
- explainability and diagnostics.

## Voltage insight
Where voltage measurements are available, PicoT may detect sustained high or low voltage, large differences between phases and repeated PV inverter shutdown associated with high grid voltage.

PicoT is not an electrical protection system. It observes and reports the data, applies Planner constraints where defined, and provides evidence-based advice.

## Installation advice
When long-term measurements show a structural imbalance or disadvantageous phase connection, PicoT may advise the user to ask a qualified installer to assess a physical change.

Examples:

- a heavily loaded phase while another phase remains lightly loaded;
- PV connected to the phase with structurally highest voltage;
- repeated PV shutdown caused by high voltage on one phase.

PicoT never changes wiring or phase connections and never presents such work as safe without professional assessment.

## Dependencies
This feature depends on:

- suitable hardware;
- integration support;
- reliable phase measurements;
- a configured household electrical profile.

If data is missing, PicoT must not estimate or invent it. The baseline HEMS remains operational without this enhancement.

## Design principle
> PicoT uses phase-load and voltage information only when objectively available. Missing measurements are never guessed. Physical electrical changes are always advisory and require qualified installer assessment.
