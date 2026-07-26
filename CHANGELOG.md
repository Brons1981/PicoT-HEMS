# Changelog

All notable PicoT HEMS project changes are recorded in this file.

## [Unreleased]

### RC3 Architecture Freeze

PicoT HEMS v1.0-RC3 architecture is approved and frozen. The project now moves into Implementation Architecture.

### Changed

- Renamed the project and repository terminology from HEMS Core to PicoT HEMS.
- Established `picot_hems.*` as the technical namespace convention.
- Defined Markdown as the source format for controlled documentation.
- Updated DOC-000, DOC-001 and DOC-002 for the RC3 architecture.
- Established Home Assistant as the primary and only target platform during design, implementation and stabilisation.
- Defined the User Layer as strictly read-only and moved all intentional user influence into the User Control Layer.
- Standardised `ActiveUserControls` as the canonical decision input for active user directives.
- Promoted Transparency from a reporting feature to a cross-cutting architectural property.

### Added

- Canonical operational lifecycle: Observe → Decide → Plan → Execute → Verify → Explain.
- Capability & Health Layer as an approved and frozen architecture layer.
- Learning Layer as an optional pass-through architecture component.
- Evidence over Assumption as an approved and frozen principle.
- Dynamic Device Capability and Thermal Derating rules.
- Extensible Components rule with transparent pass-through behaviour.
- User Control Layer with preferences, constraints, temporary overrides, manual commands, automation locks and release controls.
- Planning Strategy with planning horizon, replanning triggers, hysteresis, minimum benefit threshold, switching penalty, planning commitment and predictability.
- Execution Philosophy: execute the approved plan without optimisation or reinterpretation.
- Verification Philosophy: determine what actually happened from observable evidence without selecting the next action.
- Reporting Philosophy with layered explanations for status, reason and technical detail.
- Operational Timeline covering verified history, current operation and planned future actions across generic time intervals.
- No-surprise principle: when PicoT changes its behaviour, it also explains why.
- ADR-013 User Control Layer.
- ADR-014 Canonical Operational Lifecycle.
- ADR-015 Planning Strategy.
- ADR-016 Transparency and Operational Timeline.
- Copyright requirement for official documentation.

### Next phase

- Define component interfaces and canonical input/output models.
- Define services, events, transaction flow and state machines.
- Define the `picot_hems.*` package structure.
- Define the Home Assistant runtime architecture.
- Define persistence, retention and test architecture.
- Define the dashboard implementation model.

### Documentation follow-up

- Final consistency validation of DOC-000 through DOC-002 against ADR-001 through ADR-016.
- Update DOC-010 Project Rules.
- Update documentation indexes.
- Add architecture diagrams.
- Generate controlled Word and PDF publication artefacts from Markdown.

## Initial repository foundation

- Initial GitHub repository structure.
- Central project status file.
- Project inbox.
- Project board.