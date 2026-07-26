# PicoT HEMS Project Board

## Current phase

**RC3 Architecture Frozen**

The normative architecture is complete. New work shall conform to the approved RC3 lifecycle, layers, authority model and transparency obligations.

## Approved & Frozen

- PicoT identity: Planning, Intelligence, Coordination, Orchestration & Transparency
- Canonical operational lifecycle: Observe → Decide → Plan → Execute → Verify → Explain
- Canonical architecture layer order
- Authority hierarchy
- User Layer as strictly read-only
- User Control Layer and `ActiveUserControls`
- Integration Layer boundaries
- Learning Layer with pass-through behaviour
- Capability & Health Layer
- Decision Layer
- Planning Strategy and Planning Commitment
- Execution Philosophy
- Verification Philosophy
- Reporting Philosophy
- Operational Timeline
- Safety Layer boundary
- Canonical Domain Models
- Evidence over Assumption
- Extensible Components

## Implementation Architecture — Next

- Define component interfaces
- Define canonical input and output models
- Define services and application boundaries
- Define events and transaction flow
- Define component state machines
- Define `picot_hems.*` package structure
- Define Home Assistant runtime architecture
- Define persistence and retention interfaces
- Define test strategy and architecture conformance tests
- Define dashboard implementation model

## Documentation follow-up

- Final consistency pass across DOC-000, DOC-001, DOC-002 and ADR-001 through ADR-016
- Add architecture and component interaction diagrams
- Update DOC-010 Project Rules
- Update documentation indexes for ADR-014 through ADR-016
- Generate controlled Word and PDF publication artefacts from Markdown

## Backlog

- Automated documentation validation
- Learning Engine implementation milestones
- Home Assistant dashboard implementation
- Optional Homey support only after the Home Assistant version is stable and maintenance-light