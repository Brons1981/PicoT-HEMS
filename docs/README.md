# PicoT HEMS Documentation

This directory contains the controlled architecture and design documentation for PicoT HEMS.

## Source policy

Markdown is the editable source of truth. Word and PDF files are generated publication artefacts.

## Controlled documents

- DOC-000 Architecture Overview
- DOC-001 Vision & Principles
- DOC-002 Design Specification
- DOC-010 Project Rules
- ADR-001 and following Architecture Decision Records

## Current status

**PicoT HEMS v1.0-RC3 architecture is approved and frozen.**

The project is ready to start the Implementation Architecture phase.

The canonical operational lifecycle is:

```text
Observe → Decide → Plan → Execute → Verify → Explain
```

## RC3 architecture set

RC3 includes:

- the PicoT HEMS identity and `picot_hems.*` namespace;
- Home Assistant as the primary and only target platform during design, implementation and stabilisation;
- the canonical architecture layer order;
- the Authority Hierarchy;
- the read-only User Layer;
- the User Control Layer and `ActiveUserControls`;
- the Integration Layer boundary;
- the Learning Layer;
- the Capability & Health Layer;
- the Decision Layer;
- the Planning Strategy and Planning Commitment;
- the Execution Philosophy;
- the Verification Philosophy;
- the Reporting Philosophy;
- the Operational Timeline;
- Evidence over Assumption;
- Dynamic Device Capability and Thermal Derating;
- Extensible Components and pass-through behaviour;
- the final Safety Layer scope; and
- Transparency as a cross-cutting architectural property.

## Latest ADRs

- ADR-013 User Control Layer
- ADR-014 Canonical Operational Lifecycle
- ADR-015 Planning Strategy
- ADR-016 Transparency and Operational Timeline

## Copyright

Copyright © 2026 Alex Brons. All rights reserved.